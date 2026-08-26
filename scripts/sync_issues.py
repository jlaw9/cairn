#!/usr/bin/env python3
"""Mirror open `task` nodes into GitHub Issues, one way, per project repo.

Only tasks. Deliberately, and the restriction is the design rather than a first
increment: a task has a `due`, an owner and no scientific claim, so an issue is a
faithful container for it. An `experiment` is not — an issue is open or closed,
while the whole point of this graph is that `dead` is not `closed`, `parked` is
neither, and the status *event log* is what makes replay and provenance work.
Mirroring an experiment into an issue would silently discard the part worth
keeping.

One direction only. The graph is the source of truth; issues are a projection, the
same rule that governs any hosted view of this data. What issues buy that a
markdown file cannot: assignment, notification, and a phone.

    cairn sync_issues                      # dry run — prints, writes nothing
    cairn sync_issues --project mplastic
    cairn sync_issues --apply              # actually create/close

Dry run is the default because this writes to a service other people can see, and
a mistake there is not fixable by editing a file.

The target repo is *derived* from the project's other nodes rather than stored: an
experiment in the same project already carries `repo`, so a task inherits its
project's repo. No new field, same reasoning as authorship coming from `git log`.
Projects with no repo anywhere are reported and skipped, not guessed at.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

#: Lets a later run find the issue it already made for a node. In the body rather
#: than the title, because titles get edited by people and this must not break
#: when they do.
MARKER = "<!-- cairn-node: {node_id} -->"
MARKER_RE = re.compile(r"<!--\s*cairn-node:\s*(\S+?)\s*-->")

#: Enterprise is the normal case here, not the exception: as of 2026-08, 35 of the
#: 42 repo-bearing nodes in this graph are on a github.nrel.gov instance and only
#: 2 are on github.com. `gh` needs GH_HOST to talk to anything that isn't
#: github.com, so the host has to survive parsing. See docs/github.md.
REPO_RE = re.compile(
    r"^(?:git@(?P<h1>[^:/]+):|(?:ssh|https?)://(?:[^@/]+@)?(?P<h2>[^/]+)/)"
    r"(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$"
)


#: `owner/name` typed on the command line. Strict on purpose: the first version
#: accepted "any string with a slash and no scheme", which quietly turned
#: `repo: kestrel:/kfs2/projects/.../poly_image` — a host:/path for a project that
#: is not on GitHub at all — into the github.com repo `kestrel:/kfs2/...`, and
#: offered it as a plan. Guessing a write target is worse than refusing one.
SHORTHAND_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def parse_repo(url: str) -> tuple[str, str] | None:
    """`git@github.nrel.gov:jlaw/X.git` -> ("github.nrel.gov", "jlaw/X")."""
    m = REPO_RE.match(url.strip())
    if not m:
        return None
    return (m.group("h1") or m.group("h2")), m.group("slug")


def repo_for_project(nodes: dict[str, lib.Node]) -> dict[str, str]:
    """Most-used `repo` per project. Ties break toward the most recent node."""
    seen: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for node in sorted(nodes.values(), key=lambda n: n.id):
        url = str(node.meta.get("repo") or "").strip()
        if url:
            seen[node.project][url] += 1
    return {project: counter.most_common(1)[0][0] for project, counter in seen.items()}


def issue_body(node: lib.Node, graph_remote: str) -> str:
    """The node's own text, plus the provenance needed to get back to it."""
    facts = [f"**node** `{node.id}`", f"**project** `{node.project}`",
             f"**status** `{node.status}`"]
    if node.meta.get("due"):
        facts.append(f"**due** {node.meta['due']}")
    if node.meta.get("source"):
        facts.append(f"**from** `{node.meta['source']}`")

    tail = ["", "---",
            " · ".join(facts),
            "",
            f"Mirrored from the Cairn research graph (`nodes/{node.id}.md`"
            + (f" in {graph_remote}" if graph_remote else "") + ").",
            "The graph is the source of truth: change the status there, not here —",
            "this issue is a one-way projection and will be reconciled on the next sync.",
            "", MARKER.format(node_id=node.id)]
    return node.body.strip() + "\n" + "\n".join(tail) + "\n"


def gh(args: list[str], host: str, check: bool = True) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    if host and host != "github.com":
        env["GH_HOST"] = host
    done = subprocess.run(["gh", *args], capture_output=True, text=True, env=env, timeout=60)
    if check and done.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def existing_issues(host: str, slug: str) -> dict[str, dict]:
    """Map node id -> issue, for every issue this tool has ever opened here.

    `--state all` matters: a closed issue for a reopened task must be found rather
    than duplicated, and duplicates are the failure mode people notice.
    """
    done = gh(["issue", "list", "--repo", slug, "--state", "all", "--limit", "500",
               "--json", "number,title,body,state"], host)
    out = {}
    for issue in json.loads(done.stdout or "[]"):
        m = MARKER_RE.search(issue.get("body") or "")
        if m:
            out[m.group(1)] = issue
    return out


def graph_remote() -> str:
    try:
        done = subprocess.run(["git", "-C", str(lib.REPO_ROOT), "remote", "get-url", "origin"],
                              capture_output=True, text=True, timeout=15)
        parsed = parse_repo(done.stdout.strip())
        return parsed[1] if parsed else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default="", help="restrict to one project key")
    p.add_argument("--repo", default="",
                   help="target repo URL or owner/name, overriding what's derived")
    p.add_argument("--apply", action="store_true",
                   help="actually create and close issues; without it, nothing is written")
    p.add_argument("--label", action="append", default=[],
                   help="label to apply; must already exist in the target repo")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print the issue body too — in a dry run that is the point")
    p.add_argument("--only", action="append", default=[], metavar="NODE_ID",
                   help="just this task; repeatable. Use it for the first --apply, "
                        "so the first thing you write to a shared tracker is one issue")
    args = p.parse_args()

    nodes, errors = lib.load_nodes()
    for err in errors:
        print(f"  {err}", file=sys.stderr)

    derived = repo_for_project(nodes)
    tasks = [n for n in nodes.values() if n.type == "task"
             and (not args.project or n.project == args.project)
             and (not args.only or n.id in args.only)]
    if args.only:
        missing = set(args.only) - {n.id for n in tasks}
        if missing:
            sys.exit("--only: no task node with id " + ", ".join(sorted(missing)))
    if not tasks:
        print("no task nodes match")
        return 0

    if args.apply and shutil.which("gh") is None:
        print("cairn: --apply needs the `gh` CLI, which is not on PATH.\n"
              "  Dry run works without it. For an enterprise host you will also need\n"
              "  `gh auth login --hostname <host>` before --apply can work.", file=sys.stderr)
        return 1

    remote = graph_remote()
    plan: dict[tuple[str, str], list[lib.Node]] = collections.defaultdict(list)
    skipped: list[tuple[lib.Node, str]] = []

    for node in sorted(tasks, key=lambda n: n.id):
        url = args.repo or derived.get(node.project, "")
        if not url:
            skipped.append((node, f"no repo known for project '{node.project}'"))
            continue
        target = parse_repo(url)
        if target is None and SHORTHAND_RE.match(url):
            target = ("github.com", url)
        if target is None:
            why = ("repo is a host:/path, not a GitHub remote — that project is not "
                   "on GitHub") if lib.ARTIFACT_RE.match(url) else f"cannot parse repo: {url}"
            skipped.append((node, why))
            continue
        plan[target].append(node)

    verb = "" if args.apply else "would "
    for (host, slug), members in sorted(plan.items()):
        print(f"\n{host}/{slug}")
        found: dict[str, dict] = {}
        if args.apply:
            try:
                found = existing_issues(host, slug)
            except (RuntimeError, json.JSONDecodeError) as exc:
                print(f"  cannot read issues: {exc}", file=sys.stderr)
                continue

        for node in members:
            issue = found.get(node.id)
            want_open = not node.is_terminal
            if issue is None and not want_open:
                print(f"  skip    {node.id}  ({node.status}, no issue)")
                continue
            if issue is None:
                print(f"  {verb}create  {node.id}  \"{node.title}\"")
                if args.verbose:
                    body = issue_body(node, remote)
                    print("".join(f"          | {line}\n" for line in body.splitlines()), end="")
                if args.apply:
                    cmd = ["issue", "create", "--repo", slug, "--title", node.title,
                           "--body", issue_body(node, remote)]
                    for label in args.label:
                        cmd += ["--label", label]
                    try:
                        print(f"            {gh(cmd, host).stdout.strip()}")
                    except RuntimeError as exc:
                        print(f"            failed: {exc}", file=sys.stderr)
            elif want_open and issue["state"] != "OPEN":
                print(f"  {verb}reopen  #{issue['number']}  {node.id}")
                if args.apply:
                    gh(["issue", "reopen", str(issue["number"]), "--repo", slug], host, check=False)
            elif not want_open and issue["state"] == "OPEN":
                print(f"  {verb}close   #{issue['number']}  {node.id}  ({node.status})")
                if args.apply:
                    gh(["issue", "close", str(issue["number"]), "--repo", slug,
                        "--comment", f"Closed in the graph as `{node.status}`."], host, check=False)
            else:
                print(f"  ok      #{issue['number']}  {node.id}")

    if skipped:
        print("\nskipped")
        for node, why in skipped:
            print(f"  {node.id}  — {why}")
        print("\n  Give the project's repo with --repo, or record it on any node in that\n"
              "  project. It is derived, not stored per task.")

    if not args.apply:
        print("\nDry run. Nothing was written. Re-run with --apply to do it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
