#!/usr/bin/env python3
"""Write one project's view of the graph into that project's own repo.

    cairn export --project polyid --dest ~/repos/polyid/docs/research

This is the answer to the question every newcomer asks — *can my project's nodes
live in my project's repo?* No, and this is what they get instead: the nodes stay
in one central graph, and the project repo carries a **generated view** of the
part that concerns it. See 2026-08-27-cairn-onboarding-and-node-location.

The reasons the files themselves cannot move are in that node; the shortest one
is that a finding where mplastic informed polycrystal has no repo to live in, and
those are the most valuable nodes in the graph.

What lands in `--dest`
----------------------

- `graph.html` — the map, filtered to this project, self-contained, no server.
- `graph.md`   — a Mermaid fallback that renders on GitHub.
- `README.md`  — the index: live threads, what is already settled and why, and
  every edge that leaves this project.

Three things this does that a file copy would not
-------------------------------------------------

**It says what is not here.** Filtering drops `parents`, `relates` and
`[[links]]` whose other end is in another project — silently, because the
renderer already filters unresolvable parents. A dropped edge and an absent edge
must never look the same, so every outbound edge is listed in the index by name.
That is the same rule the webapp node sets for per-project access control, and it
is the whole reason absence can be trusted anywhere in this graph.

**It stamps its own provenance.** A committed snapshot of a live graph is a lie
with a date on it, so the date, the graph's commit and the node count go at the
top of every file it writes. A reader can tell how stale the view is without
asking anyone.

**It refuses to clobber.** A file in `--dest` that does not carry the generated
marker is somebody's hand-written documentation, and this stops rather than
overwrite it.

No scrubbing, deliberately: this is a view for people who already have access to
the work. `export_example` is the one that publishes outward, and it refuses to
write until a human has read what it flags.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_graph  # noqa: E402
import lib  # noqa: E402

#: Every file this writes carries it, and it is what makes overwriting safe.
MARKER = "cairn:generated"

#: A node id, so `[[wikilinks]]` in prose about the syntax is not read as an edge.
NODE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def graph_head() -> str:
    """The graph's current commit, so a reader can date the view exactly."""
    try:
        out = subprocess.run(
            ["git", "-C", str(lib.REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=30, check=True)
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def outbound_edges(selected: dict, everything: dict) -> list[tuple[str, str, str, str]]:
    """(from-id, kind, target-id, target-project) for every edge leaving the set.

    Includes body wikilinks, not just frontmatter: a cross-project dependency is
    supposed to live in the body per the conventions, so leaving those out would
    miss exactly the edges the rule puts there.
    """
    out: list[tuple[str, str, str, str]] = []
    for nid, node in sorted(selected.items()):
        seen: set[str] = set()
        # Order is the precedence: lineage, then a typed relation, then a bare
        # mention. Deduped by *target*, so a node that both relates to another and
        # names it in prose reports one edge — which is what the renderer does with
        # a doubled edge too, styling it by the more specific claim.
        candidates = [("parent", p) for p in node.parents]
        candidates += [(str(r.get("type", "relates")), str(r.get("to", "")))
                       for r in node.relates]
        candidates += [("mentions", m.group(1)) for m in WIKILINK.finditer(node.body)]
        for kind, target in candidates:
            if not target or target in selected or not NODE_ID.match(target):
                continue
            if target in seen:
                continue
            seen.add(target)
            other = everything.get(target)
            out.append((nid, kind, target,
                        other.project if other else "not in the graph"))
    return out


def first_sentence(section: str, cap: int = 220) -> str:
    """The opening sentence of a `## Next`, as one clean line.

    Bodies are hand-wrapped markdown, so the first *line* is usually half a
    sentence and often carries an unclosed `**`. Taking it raw produced entries
    like "...rather than a pretraining target.** The raw value already" — a
    truncation that reads as a typo and undermines the whole index.

    So: join the wrapped continuation lines of the first item, drop emphasis
    markers, then cut at the first sentence end.
    """
    lines = [l.strip() for l in section.splitlines()]
    collected: list[str] = []
    for line in lines:
        if not line:
            if collected:
                break
            continue
        starts_item = re.match(r"^(?:[-*+]|\d+[.)])\s", line)
        if collected and starts_item:
            break
        collected.append(re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", line))
    text = re.sub(r"\s+", " ", " ".join(collected)).strip()
    text = text.replace("**", "").replace("`", "")
    # `[[id]]` is the graph's own link syntax and resolves nowhere in a project
    # repo. Keep the id, which is what you search the graph for; drop the brackets.
    text = WIKILINK.sub(lambda m: f"`{m.group(1)}`", text)
    match = re.search(r"(?<=[.!?])\s", text)
    if match:
        text = text[:match.start()]
    if len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0] + "…"
    return text.strip()


def index_md(project: str, selected: dict, outbound: list, stamp: str) -> str:
    live, settled, parked = [], [], []
    for node in sorted(selected.values(),
                       key=lambda n: (n.updated or dt.date.min), reverse=True):
        (settled if node.is_terminal
         else parked if node.status == "parked" else live).append(node)

    def entry(node) -> str:
        note = ""
        if node.history:
            note = str(node.history[-1].get("note", "")).strip()
            note = WIKILINK.sub(lambda m: f"`{m.group(1)}`", note)
        line = (f"- **{node.title}**  \n"
                f"  `{node.id}` · {node.type} · **{node.status}**"
                f"{f' · updated {node.updated.isoformat()}' if node.updated else ''}")
        if note:
            line += f"  \n  {note}"
        nxt = first_sentence(lib.body_section(node.body, ["next"]))
        if nxt:
            line += f"  \n  *Next:* {nxt}"
        return line

    parts = [
        f"<!-- {MARKER} -->",
        f"# Research record — {project}",
        "",
        f"_{stamp}_",
        "",
        "Generated from the central Cairn graph. **Do not edit** — edits are lost on",
        "the next export, and the node files are the record. Open `graph.html` for the",
        "map, with the time axis, the lineage view and the history replay.",
        "",
    ]

    if live:
        parts += [f"## Live threads ({len(live)})", "",
                  *[entry(n) for n in live], ""]
    if settled:
        parts += [
            f"## Already settled ({len(settled)})",
            "",
            "**Read this before proposing work.** A `dead` node is a claim someone",
            "already refuted, with the reason attached — citing it beats re-running it.",
            "",
            *[entry(n) for n in settled], "",
        ]
    if parked:
        parts += [f"## Parked ({len(parked)})", "",
                  "Paused, not decided — parking is a pause, closing is a decision.", "",
                  *[entry(n) for n in parked], ""]

    if outbound:
        parts += [
            f"## Connected to other projects ({len(outbound)})",
            "",
            "These edges leave this project, so the other end is **not in this view**.",
            "They are listed rather than dropped: a missing edge and a hidden edge must",
            "never look the same, or absence in the graph stops meaning anything.",
            "Follow them in the full graph.",
            "",
            "| from | relation | to | that project |",
            "| --- | --- | --- | --- |",
            *[f"| `{a}` | {k} | `{t}` | {p} |" for a, k, t, p in outbound],
            "",
        ]

    if not selected:
        parts += ["No nodes for this project yet.", ""]

    parts += [
        "---",
        "",
        "The graph is one graph across every project, because the edges between",
        "projects are the hardest part of a research record to reconstruct later.",
        "This directory is a projection of the part that concerns this repo.",
        "",
    ]
    return "\n".join(parts)


def refuse_to_clobber(paths: list[Path]) -> list[Path]:
    """Existing files that are not ours. Hand-written docs are not ours to replace."""
    return [p for p in paths
            if p.exists() and MARKER not in p.read_text(encoding="utf-8", errors="replace")]


def main() -> int:
    ap = argparse.ArgumentParser(prog="cairn export", description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True, help="project key to export")
    ap.add_argument("--dest", required=True, help="directory in the project's repo")
    ap.add_argument("--dry-run", action="store_true", help="say what would be written")
    args = ap.parse_args()

    nodes, errors = lib.load_nodes()
    for e in errors[:5]:
        print("warning: " + e, file=sys.stderr)

    selected = {i: n for i, n in nodes.items() if n.project == args.project}
    if not selected:
        keys = sorted({n.project for n in nodes.values() if n.project})
        print(f"cairn export: no nodes with project '{args.project}'.\n"
              f"  known: {', '.join(keys)}", file=sys.stderr)
        return 2

    dest = Path(args.dest).expanduser()
    targets = [dest / "graph.html", dest / "graph.md", dest / "README.md"]

    outbound = outbound_edges(selected, nodes)
    dates = sorted(n.created for n in selected.values() if n.created)
    stamp = (f"Generated {dt.date.today().isoformat()} from graph commit "
             f"`{graph_head()}` — {len(selected)} node(s)"
             + (f", {dates[0].isoformat()} to {dates[-1].isoformat()}" if dates else ""))

    print(f"cairn export — project '{args.project}', {len(selected)} node(s) -> {dest}")
    if outbound:
        print(f"  {len(outbound)} edge(s) leave this project; listed in README.md:")
        for a, k, t, p in outbound:
            print(f"    {a}  {k} -> {t}  ({p})")

    clash = refuse_to_clobber(targets)
    if clash:
        print("\ncairn export: refusing to overwrite files this did not write:",
              file=sys.stderr)
        for p in clash:
            print(f"    {p}", file=sys.stderr)
        print("  Move them, or pick a --dest of its own. Hand-written documentation is\n"
              "  not something a generator should replace.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\n  would write: " + ", ".join(p.name for p in targets))
        print("  dry run, nothing written.")
        return 0

    # The renderer's own functions, called with a filtered node set — so this
    # view inherits every improvement to the map without a second renderer to
    # maintain. `build_payload` already drops parents outside the set, which is
    # exactly why the index has to name them.
    papers, _ = lib.load_papers()
    positions, lanes, ticks, width, height = build_graph.compute_layout(selected)
    payload = build_graph.build_payload(selected, papers, positions, lanes,
                                        ticks, width, height)
    html = build_graph.render_html(payload)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "graph.html").write_text(
        html + f"\n<!-- {MARKER}: {stamp} -->\n", encoding="utf-8")
    (dest / "graph.md").write_text(
        f"<!-- {MARKER} -->\n# Research record — {args.project}\n\n_{stamp}_\n\n"
        + build_graph.render_mermaid(selected) + "\n", encoding="utf-8")
    (dest / "README.md").write_text(
        index_md(args.project, selected, outbound, stamp), encoding="utf-8")

    print("\n  wrote " + ", ".join(p.name for p in targets))
    print("  commit it in that repo. It is generated, and every file says so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
