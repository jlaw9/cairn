#!/usr/bin/env python3
"""Mark a node read, and see what has not been.

`reviewed` is derived from git, never stored — see the design note above
`REVIEW_TRAILER` in lib.py. This is the command that produces the signal:

    cairn review 2026-08-27-cairn-review-policy
    cairn review cairn-review-policy "the epoch trick is the good part"
    cairn review --list                      # what nobody has read
    cairn review --list --project polyid

**A note is preferred, not required.** With text it appends the note and stamps
the review in one commit, so the record says what you thought as well as that
you looked. Without, it is an empty commit carrying the trailer — "I read this
and had nothing to add" is a real outcome and it should be cheap to say.

**It commits the node if the node is uncommitted.** That is the point rather than
a side effect: design decision 6 holds that nothing enters the graph unreviewed,
and the queue that decision creates drains here. Reviewing a draft *is* admitting
it, so the file and the stamp land in the same commit and the derivation cannot
disagree with the history.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib
import note as note_cmd


#: The states worth chasing, worst first. `unclassified` is not one of them: it
#: means the node predates the convention, and nagging about history nobody can
#: reconstruct is how a report gets ignored.
CHASE = ("uncommitted", "unreviewed")


def working_state(rel: Path) -> str:
    """"" | "untracked" | "modified" — what the working tree has to say.

    The distinction matters because `git commit --only <path>` refuses a path git
    has never seen ("did not match any file(s) known to git"), which is exactly
    the draft case this command exists to clear. An untracked node needs `git add`
    first.
    """
    code, out = note_cmd.git("status", "--porcelain", "--", str(rel))
    if code != 0 or not out.strip():
        return ""
    return "untracked" if out.lstrip().startswith("??") else "modified"


def list_unreviewed(nodes: dict, project: str) -> int:
    states = lib.review_states(nodes)
    buckets: dict[str, list] = {name: [] for name in CHASE}
    for node_id, node in nodes.items():
        if project and node.project != project:
            continue
        state = states[node_id]["state"]
        if state in buckets:
            buckets[state].append(node)

    if not any(buckets.values()):
        scope = f" in {project}" if project else ""
        print(f"Nothing unread{scope}.")
        counts = {}
        for node_id, node in nodes.items():
            if project and node.project != project:
                continue
            counts[states[node_id]["state"]] = counts.get(states[node_id]["state"], 0) + 1
        if counts.get("unclassified"):
            print(f"  ({counts['unclassified']} node(s) predate the review "
                  f"convention — git cannot say either way.)")
        return 0

    labels = {
        "uncommitted": "never committed — invisible from your other machine",
        "unreviewed": "unreviewed — written since anyone last read them",
    }
    for name in CHASE:
        rows = sorted(buckets[name], key=lambda n: n.id, reverse=True)
        if not rows:
            continue
        print(f"\n{len(rows)} {labels[name]}\n")
        for node in rows:
            print(f"  {node.id}")
            print(f"      [{node.project}/{node.status}] {node.title}")
    print(f"\n  cairn review <id> \"what you thought\"")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn review",
        description="Mark a node read, or list the nodes nobody has read.")
    p.add_argument("node", nargs="?", default="",
                   help="node id, or enough of one to be unambiguous")
    p.add_argument("text", nargs="*",
                   help="an optional note — preferred, but not required")
    p.add_argument("--list", action="store_true",
                   help="print what is unread instead of marking anything")
    p.add_argument("--project", default="", help="with --list, one project only")
    args = p.parse_intermixed_args()

    nodes, errors = lib.load_nodes()
    for error in errors:
        print(f"cairn: {error}", file=sys.stderr)

    if args.list:
        return list_unreviewed(nodes, args.project)
    if not args.node:
        p.error("which node? (`cairn review --list` to see what is unread)")

    node = note_cmd.resolve(nodes, args.node)
    if node is None:
        return 1

    who = note_cmd.whoami()
    if not who:
        print("cairn: no git identity — `git config user.email` first, so the "
              "stamp says who read it.", file=sys.stderr)
        return 1

    rel = node.path.relative_to(lib.REPO_ROOT)
    text = " ".join(args.text).strip()
    if text:
        line = lib.append_note(node, text, who=who)
        node.write()
        print(f"{rel}\n  {line}")
        subject = f"note on {node.id}: {' '.join(text.split())[:60]}"
    else:
        subject = f"review {node.id}: {node.title[:60]}"

    message = f"{subject}\n\n{lib.review_trailer(who, node.id)}\n"

    state = working_state(rel)
    if state == "untracked":
        code, out = note_cmd.git("add", "--", str(rel))
        if code != 0:
            print(f"cairn: could not stage {rel}:\n  {out}", file=sys.stderr)
            return 1
    # --only, not -a: a review says something about *this* node, and sweeping a
    # neighbouring draft into the same commit would stamp it reviewed too.
    # --allow-empty when there is nothing to carry: "I read it and had nothing to
    # add" is a real outcome, and the trailer is the whole payload.
    if state:
        code, out = note_cmd.git("commit", "--only", str(rel), "-m", message)
    else:
        code, out = note_cmd.git("commit", "--allow-empty", "-m", message)

    if code != 0:
        if text:
            print("\n  The note is written, but the commit failed — nothing is "
                  "lost:")
        else:
            print("\n  Nothing was stamped — the commit failed:")
        for out_line in out.splitlines()[:10]:
            print(f"    {out_line}")
        return 1

    print(f"  reviewed by {who}. `cairn sync --push` to make it visible elsewhere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
