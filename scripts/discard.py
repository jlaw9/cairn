#!/usr/bin/env python3
"""Throw away a draft node that git has never seen.

    cairn discard 2026-10-14-polyid-half-written-idea
    cairn discard 2026-10-14-polyid-half-written-idea --dry-run

**This is not an exception to "never delete a node".** A node is in the graph
once git has seen it: the rule exists so that the record of what was tried
cannot be garbage collected, and a file git never saw was never part of that
record. Design decision 6 says nothing enters the graph unreviewed; a draft an
agent wrote and nobody wanted is the other outcome of that review. `cairn
review` admits a draft, `cairn discard` declines it.

The corollary is the whole safety story, so it is enforced rather than trusted:
this refuses anything git tracks (committed, or modified since), anything that
is not a bare node id, a graph that is not a git repo (then there is no way to
tell a draft from a record), and a draft some other node already points at
through `parents` or `relates`, since removing it would leave that node
dangling. `assets/<id>.*` goes with the draft, if untracked.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

# Same shape serve.py accepts. Copied rather than imported: serve pulls in a
# web server, and this must stay a bare, boring command.
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")


def git(*args: str) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(lib.REPO_ROOT), *args],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def untracked(rel: Path) -> bool:
    code, out = git("status", "--porcelain", "--", str(rel))
    return code == 0 and out.lstrip().startswith("??")


def referrers(nodes: dict, node_id: str) -> list[str]:
    found = []
    for other in nodes.values():
        if other.id == node_id:
            continue
        if node_id in other.parents:
            found.append(f"{other.id} (parent)")
        if any(r.get("to") == node_id for r in other.relates):
            found.append(f"{other.id} (relates)")
    return found


def refuse(message: str) -> int:
    print(f"cairn: {message}", file=sys.stderr)
    return 1


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn discard",
        description="Delete a node file git has never seen. Refuses anything committed.")
    p.add_argument("node", help="the full node id")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would be removed, remove nothing")
    args = p.parse_args()

    node_id = args.node
    if not ID_RE.match(node_id):
        return refuse(f"'{node_id}' is not a bare node id (YYYY-MM-DD-slug), "
                      "so it is not a file this will touch.")

    root = lib.REPO_ROOT
    code, out = git("rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return refuse("the graph is not a git repo, so there is no telling a draft "
                      "from a record; delete it by hand if you are sure.")

    path = root / "nodes" / f"{node_id}.md"
    if not path.is_file():
        return refuse(f"no such node file: nodes/{node_id}.md")
    rel = path.relative_to(root)
    if not untracked(rel):
        return refuse(f"{rel} is tracked by git (committed or modified), so it is part "
                      "of the graph; change its status instead of deleting it.")

    nodes, _errors = lib.load_nodes()
    refs = referrers(nodes, node_id)
    if refs:
        return refuse(f"{node_id} is referenced by {', '.join(refs)}; "
                      "discarding it would leave those dangling.")

    targets = [path]
    for asset in sorted((root / "assets").glob(f"{node_id}.*")):
        if untracked(asset.relative_to(root)):
            targets.append(asset)

    for target in targets:
        shown = target.relative_to(root)
        if args.dry_run:
            print(f"would remove {shown}")
        else:
            target.unlink()
            print(f"removed {shown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
