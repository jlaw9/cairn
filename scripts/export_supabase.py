#!/usr/bin/env python3
"""Mirror the published part of the graph into Supabase, read-only.

    cairn export_supabase                   # dry run: what would be sent, and what is held back
    cairn export_supabase --dump out.json   # ...and write the exact payload to read
    cairn export_supabase --apply           # send it

Why this exists: agents that cannot see this machine — on a phone, in another
repo, behind an IT policy that refuses remote control of the HPC — still need
to ask "did we already try this, and how is it going?". A Supabase copy of the
graph, read through Crello's MCP server, answers that without anything reaching
*in* to the machine that holds the graph. It is meant to run from a GitHub
Action on push, so the HPC never talks to anything new.

The rule that makes it safe is the one the webapp node set
(2026-08-05-cairn-webapp): **git stays the source of truth and this is a
projection of it.** Nothing here reads from Supabase, and nothing in Supabase is
ever merged back. Writes from Crello, when they exist, are requests that an
agent carries out through `bin/cairn` — a different path, not this one.

What crosses, and what does not
-------------------------------

Only projects listed in `published-projects.txt` at the graph root — one key per
line, `#` for comments, `*` for every project. **No file means nothing is
published.** Opting a project in is a deliberate act, and the diff of that file
is the audit trail. An unknown key is reported with its near-matches, because a
typo there silently withholds a project you meant to share.

- `cairn_nodes`  — every node of a published project: frontmatter, body, history,
  plus the two things git derives (who wrote it, whether a human has read it).
- `cairn_edges`  — lineage, typed relations and `[[mentions]]`. An edge into a
  project that is *not* published keeps its existence and loses its target:
  `target_state = 'hidden'`, `target = null`. A dropped edge and an absent edge
  must never look the same — that is the whole premise of the graph.
- `cairn_views`  — `standup`, `digest` (7 days), `report` and `coverage`, overall
  and per project, rendered by the same code as the terminal. Crello serves
  Cairn's own ranking instead of reimplementing it, so the two cannot drift.
- `cairn_exports` — one row per run: graph commit, projects, counts. Written
  last, so a reader can tell a finished mirror from one cut off half way.

A `[[link]]` to a hidden node is redacted in bodies and views alike, since the
id itself names the work. Free prose that mentions another project by name is
not scrubbed: this is a view for whoever can read the Supabase project, the same
audience `cairn export` serves. Publishing outward is `export_example`'s job.

Only committed state is mirrored. `--apply` refuses while `nodes/` has
uncommitted changes — a draft nobody has read must not reach other agents
before it reaches git — and drafts never committed are left out and counted.

Credentials come from the environment, never from flags, so they stay out of
shell history: `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. The schema is
`docs/supabase.sql`; apply it once per Supabase project.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import digest  # noqa: E402
import lib  # noqa: E402
import report  # noqa: E402
import standup  # noqa: E402
from build_graph import node_authors  # noqa: E402

ALLOWLIST = "published-projects.txt"

#: What a hidden `[[link]]` becomes, and what a bare hidden id in prose becomes.
#: Plain text, so neither reads as a dangling link to the validator or renderer.
REDACTED = "[[a node in an unpublished project]]"
REDACTED_BARE = "(a node in an unpublished project)"

WIKILINK = re.compile(r"\[\[\s*([^\]]+?)\s*\]\]")
NODE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")
BARE_ID = re.compile(r"(?<![\w-])\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*(?![\w-])")

#: Upsert keys, matching the primary keys in docs/supabase.sql.
CONFLICT = {
    "cairn_nodes": "graph,id",
    "cairn_edges": "graph,edge_id",
    "cairn_views": "graph,key",
}

BATCH = 200
WIDTH = 88
DIGEST_DAYS = 7


# ---------------------------------------------------------------------------
# What is published
# ---------------------------------------------------------------------------


def read_allowlist(root: Path) -> tuple[list[str], bool]:
    """(keys, file-exists). `*` is returned as-is and expanded by the caller."""
    path = root / ALLOWLIST
    if not path.is_file():
        return [], False
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("#", 1)[0].strip()
        if key and key not in keys:
            keys.append(key)
    return keys, True


def resolve_projects(keys: list[str], known: list[str]) -> tuple[list[str], list[str]]:
    """(published, warnings). Unknown keys are warned about, never guessed at."""
    if "*" in keys:
        return sorted(known), []
    warnings = []
    published = []
    for key in keys:
        if key in known:
            published.append(key)
            continue
        near = difflib.get_close_matches(key, known, n=3, cutoff=0.6)
        hint = f" — did you mean {', '.join(near)}?" if near else ""
        warnings.append(f"{ALLOWLIST}: no project '{key}' in the graph{hint}")
    return sorted(published), warnings


# ---------------------------------------------------------------------------
# The payload
# ---------------------------------------------------------------------------


def jsonable(value):
    """Frontmatter carries dates; PostgREST wants strings."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def iso(value) -> str | None:
    when = lib.as_date(value)
    return when.isoformat() if when else None


def redact(text: str, published: set[str], everything: set[str]) -> str:
    """Replace any id of a node that is in the graph but not published.

    An id is a date plus a slug that names the work, so it is content, not a
    pointer: `[[2026-10-07-cosmors-phase-composition-gate]]` says what the hidden
    node is about. Wikilinks first, then the same id written bare in prose.

    An id the graph does not have is left alone: it names nothing hidden, and
    redacting it would disguise a broken link as a private one.
    """
    def hidden(target: str) -> bool:
        return target in everything and target not in published

    def swap(match: re.Match) -> str:
        return REDACTED if hidden(match.group(1)) else match.group(0)

    def swap_bare(match: re.Match) -> str:
        return REDACTED_BARE if hidden(match.group(0)) else match.group(0)

    return BARE_ID.sub(swap_bare, WIKILINK.sub(swap, text))


def scrub(value, published: set[str], everything: set[str]):
    """`redact` applied to every string inside a JSON-shaped value."""
    if isinstance(value, str):
        return redact(value, published, everything)
    if isinstance(value, dict):
        return {k: scrub(v, published, everything) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, published, everything) for v in value]
    return value



def edges_of(node: lib.Node, nodes: dict[str, lib.Node],
             published: set[str]) -> list[dict]:
    """Every edge leaving `node`, deduped by (kind, target).

    Lineage and typed relations are kept even when they point at the same
    target, because they say different things; a bare `[[mention]]` of a target
    already linked another way is dropped, as the renderer does.
    """
    raw = [("parent", p, "") for p in node.parents]
    raw += [(str(r.get("type", "")), str(r.get("to", "")), str(r.get("note", "")))
            for r in node.relates]
    linked = {t for _, t, _ in raw}
    raw += [("mentions", m.group(1), "") for m in WIKILINK.finditer(node.body)
            if NODE_ID.match(m.group(1)) and m.group(1) not in linked]

    out, seen = [], set()
    for kind, target, note in raw:
        if not target or (kind, target) in seen:
            continue
        seen.add((kind, target))
        if target in published:
            state, shown = "visible", target
        elif target in nodes:
            state, shown = "hidden", None
        else:
            state, shown = "missing", target
        # The edge id hashes the real target, so a hidden edge is stable across
        # runs without the id itself saying what it points at.
        digest_ = hashlib.sha1(f"{node.id}|{kind}|{target}".encode()).hexdigest()[:16]
        out.append({
            "edge_id": f"{node.id}:{digest_}",
            "source": node.id,
            "kind": kind,
            "target": shown,
            "target_state": state,
            "note": redact(note, published, set(nodes)),
        })
    return out


def render_views(selected: dict[str, lib.Node], states: dict[str, dict],
                 today: dt.date, inbox: int) -> list[dict]:
    """The terminal's own views, over the published nodes only."""
    views = []
    unread = sum(1 for s in states.values()
                 if s["state"] in ("unreviewed", "uncommitted"))
    rows = standup.survey(selected, today, standup.QUIET_AFTER, 14)
    views.append(("standup", None, standup.render(
        rows, today, standup.QUIET_AFTER, 14, True, WIDTH, inbox, unread), None))
    for row in rows:
        views.append((f"standup:{row['project']}", row["project"],
                      standup.render_packet(row, selected, today, True, WIDTH), None))

    start = today - dt.timedelta(days=DIGEST_DAYS)
    by_project: dict[str, dict[str, lib.Node]] = {}
    for nid, node in selected.items():
        by_project.setdefault(node.project, {})[nid] = node
    for project, members in [("", selected)] + sorted(by_project.items()):
        found = digest.gather(members, start, today, digest.STALE_DAYS,
                              digest.HORIZON_DAYS)
        key = f"digest:{DIGEST_DAYS}d" + (f":{project}" if project else "")
        views.append((key, project or None, digest.render(
            found, start, today, project, digest.HORIZON_DAYS, True), None))

    for project in [""] + sorted(by_project):
        key = "report" + (f":{project}" if project else "")
        views.append((key, project or None, report.build(selected, project), None))

    # Coverage as data as well as prose: it is the number an agent needs before
    # it may read a missing node as "not tried", so it should not have to parse
    # a markdown table to get it.
    commits = report.commit_dates()
    lag = {}
    for node in selected.values():
        if node.created and node.id in commits:
            lag[node.id] = max(0, (commits[node.id] - node.created).days)
    rows = report.coverage(selected, lag, states)
    views.append(("coverage", None, "", jsonable(rows)))
    return [{"key": k, "project": p, "content": c, "data": d} for k, p, c, d in views]


def build_payload(root: Path, projects: list[str], graph: str,
                  today: dt.date | None = None) -> dict:
    """Everything one export sends, as table -> rows, plus what was held back."""
    today = today or dt.date.today()
    nodes, errors = lib.load_nodes(root)
    if errors:
        raise SystemExit("cairn: the graph does not parse; fix it before mirroring:\n  "
                         + "\n  ".join(errors))
    everything = set(nodes)

    states = lib.review_states(nodes, root)
    wanted = set(projects)
    drafts = sorted(nid for nid, n in nodes.items()
                    if n.project in wanted and states[nid]["state"] == "uncommitted")
    selected = {nid: n for nid, n in nodes.items()
                if n.project in wanted and nid not in drafts}
    published = set(selected)
    authors = node_authors()
    inbox = standup.inbox_count(root)

    node_rows, edge_rows = [], []
    for nid in sorted(selected):
        node = selected[nid]
        # Lineage and relations live in cairn_edges, which knows how to hide a
        # target; left in `meta` they would carry the hidden ids verbatim.
        meta = {k: v for k, v in node.meta.items()
                if k not in ("history", "parents", "relates")}
        node_rows.append({
            "id": nid,
            "project": node.project,
            "type": node.type,
            "status": node.status,
            "title": node.title,
            "created": iso(node.meta.get("created")),
            "updated": iso(node.meta.get("updated")),
            "author": authors.get(nid),
            "review_state": states[nid]["state"],
            "meta": scrub(jsonable(meta), published, everything),
            "history": scrub(jsonable(node.history), published, everything),
            "body": redact(node.body, published, everything),
        })
        edge_rows.extend(edges_of(node, nodes, published))

    views = render_views(selected, {n: states[n] for n in selected}, today, inbox)
    for view in views:
        view["content"] = redact(view["content"], published, everything)
        view["generated_on"] = today.isoformat()

    for rows in (node_rows, edge_rows, views):
        for row in rows:
            row["graph"] = graph

    held = sorted({n.project for n in nodes.values()} - wanted)
    return {
        "tables": {"cairn_nodes": node_rows, "cairn_edges": edge_rows,
                   "cairn_views": views},
        "projects": sorted(wanted),
        "held_back": held,
        "drafts": drafts,
        "hidden_edges": sum(1 for e in edge_rows if e["target_state"] == "hidden"),
    }


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def dirty_nodes(root: Path) -> list[str] | None:
    """Changed or untracked files under nodes/; None if this is not a git repo."""
    out = git(root, "status", "--porcelain", "--", "nodes")
    if out is None:
        return None
    return [line[3:] for line in out.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Supabase (PostgREST), stdlib only — PyYAML stays the one dependency
# ---------------------------------------------------------------------------


class Remote:
    def __init__(self, url: str, key: str, timeout: int = 60):
        self.base = url.rstrip("/") + "/rest/v1/"
        self.key = key
        self.timeout = timeout

    def call(self, method: str, table: str, query: dict | None = None,
             body=None, prefer: str = "return=minimal") -> None:
        url = self.base + table
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": prefer,
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise SystemExit(f"cairn: {method} {table} failed: HTTP {exc.code} {detail}")
        except urllib.error.URLError as exc:
            raise SystemExit(f"cairn: cannot reach Supabase ({exc.reason})")

    def upsert(self, table: str, rows: list[dict]) -> None:
        for i in range(0, len(rows), BATCH):
            self.call("POST", table, {"on_conflict": CONFLICT[table]}, rows[i:i + BATCH],
                      prefer="resolution=merge-duplicates,return=minimal")

    def prune(self, table: str, graph: str, export_id: str) -> None:
        """Drop rows this export did not write: a project taken off the list."""
        self.call("DELETE", table, {"graph": f"eq.{graph}",
                                    "export_id": f"neq.{export_id}"})


def send(remote: Remote, payload: dict, graph: str, source_sha: str) -> str:
    """Upsert, prune, then record the export. Returns the export id.

    The export row goes last on purpose: its presence is what says the mirror
    is complete at `source_sha`. A run that dies half way leaves the previous
    row as the latest, which is the truth — and the next push repairs it.
    """
    export_id = uuid.uuid4().hex
    tables = payload["tables"]
    for table, rows in tables.items():
        for row in rows:
            row["export_id"] = export_id
            row["source_sha"] = source_sha
        remote.upsert(table, rows)
    for table in tables:
        remote.prune(table, graph, export_id)
    remote.call("POST", "cairn_exports", body=[{
        "graph": graph,
        "export_id": export_id,
        "source_sha": source_sha,
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "projects": payload["projects"],
        "counts": {t: len(r) for t, r in tables.items()},
    }])
    return export_id


# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mirror the published projects of the graph into Supabase, read-only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Projects are listed in {ALLOWLIST} at the graph root; no file publishes "
               "nothing. Credentials: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.",
    )
    p.add_argument("--apply", action="store_true", help="send it; the default is a dry run")
    p.add_argument("--graph", default="",
                   help="name of this graph in Supabase; default: the graph directory's name")
    p.add_argument("--dump", metavar="FILE", help="write the payload as JSON, to read it")
    args = p.parse_args()

    root = lib.REPO_ROOT
    lib.require_graph(root)
    graph = (args.graph or root.name).lower()

    keys, have_file = read_allowlist(root)
    nodes, _ = lib.load_nodes(root)
    projects, warnings = resolve_projects(keys, lib.projects(nodes))
    for warning in warnings:
        print(f"  warning: {warning}", file=sys.stderr)

    if not have_file:
        # Not an error: "nothing published" is a real state, and --apply must
        # still run so that deleting the file empties the mirror.
        print(f"cairn: no {ALLOWLIST} in {root} — nothing is published.\n"
              "  List the project keys to mirror, one per line (or `*` for all).")

    payload = build_payload(root, projects, graph)
    tables = payload["tables"]
    sha = git(root, "rev-parse", "HEAD") or "unknown"

    print(f"graph {graph} @ {sha[:12]}")
    print(f"  published: {', '.join(payload['projects']) or '(none)'}")
    print(f"  held back: {len(payload['held_back'])} project(s)")
    for table, rows in tables.items():
        print(f"  {table:12} {len(rows):5} rows")
    print(f"  edges into unpublished projects, kept as hidden: {payload['hidden_edges']}")
    if payload["drafts"]:
        print(f"  never committed, left out: {', '.join(payload['drafts'])}")

    if args.dump:
        Path(args.dump).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        print(f"  payload written to {args.dump}")

    if not args.apply:
        print("dry run — nothing sent. --apply to send.")
        return 0

    dirty = dirty_nodes(root)
    if dirty is None:
        print("cairn: the graph is not a git repo; the mirror is a projection of git, "
              "so there is nothing to project.", file=sys.stderr)
        return 1
    if dirty:
        print("cairn: nodes/ has uncommitted changes — commit or stash them first, so the "
              "mirror matches a commit:\n  " + "\n  ".join(dirty[:10]), file=sys.stderr)
        return 1

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        print("cairn: set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to send.", file=sys.stderr)
        return 1

    export_id = send(Remote(url, key), payload, graph, sha)
    print(f"sent: export {export_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
