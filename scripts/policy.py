#!/usr/bin/env python3
"""Read or set the graph's commit policy: does an agent ask before committing a node?

    cairn policy              # print the mode and what it means
    cairn policy auto         # agents commit the nodes they write, you edit after
    cairn policy ask          # agents draft, show, and wait (the default)

Where it lives, and why there. The mode is one line in the *graph* repo's own
`CLAUDE.md`:

    commit_mode: ask

Not a dotfile, not a YAML config. 2026-08-27-cairn-onboarding-and-node-location
settled that a stored preference is a second copy of a truth that can disagree
with the first — so Cairn derives rather than stores wherever it can, and the
one preference that genuinely cannot be derived goes where every agent already
reads, in git, reviewable in a diff, next to the prose that says *why*. A team
then shares the policy by sharing the repo, instead of each person configuring
identically.

It is policy over identical data (2026-08-27-cairn-review-policy): two people
with different modes still hold the same graph, and `cairn review --list` says
which nodes nobody has read in either mode. That is what makes `auto` safe to
offer at all — an unread node is *visible*, not absent.

Imports nothing from lib on purpose: the session hook reads this before
anything else in a session, on whatever machine that is, and it must not be
able to fail on PyYAML.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

MODES = ("ask", "auto")
DEFAULT = "ask"

#: The one machine-readable line. Flush-left, lowercase, nothing else on it, so
#: a sentence that happens to mention `commit_mode: auto` in passing is not read
#: as the setting.
LINE_RE = re.compile(r"(?m)^commit_mode:[ \t]*(ask|auto)[ \t]*$")

MEANING = {
    "ask": "an agent drafts a node, shows it, and commits only after you confirm",
    "auto": "an agent commits the nodes it writes about work it did, and tells you; "
            "you edit afterward, and `cairn review --list` shows what nobody has read",
}

SECTION = """## Commit policy

commit_mode: {mode}

`ask` — an agent drafts a node, shows it, and commits only after you confirm.
Nothing enters the graph unread. `auto` — an agent that writes a node about
work it just did commits it at once and tells you what it committed; you edit
afterward, and `cairn review --list` shows what nobody has read yet. Same graph
either way: the mode is policy over identical data, so two people with
different modes still hold one record. Switch with `cairn policy auto|ask`.
Whatever the mode, anything written unprompted still goes to `inbox/`.
"""


def graph_root() -> Path:
    tool = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("CAIRN_ROOT") or tool).expanduser()


def policy_file(root: Path | None = None) -> Path:
    return (root or graph_root()) / "CLAUDE.md"


def read_commit_mode(root: Path | None = None) -> str:
    """The mode in force for this graph. Unset, unreadable or malformed means
    `ask`, because the conservative reading is the one that cannot surprise."""
    try:
        text = policy_file(root).read_text(encoding="utf-8")
    except (OSError, ValueError):            # ValueError: not UTF-8
        return DEFAULT
    match = LINE_RE.search(text)
    return match.group(1) if match else DEFAULT


def write_commit_mode(mode: str, root: Path | None = None) -> Path:
    """Set the mode. Replaces the line if present, appends the section if not."""
    if mode not in MODES:
        raise ValueError(f"commit_mode must be one of {MODES}, not {mode!r}")
    path = policy_file(root)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if LINE_RE.search(text):
        text = LINE_RE.sub(f"commit_mode: {mode}", text, count=1)
    else:
        joiner = "" if (not text or text.endswith("\n\n")) else ("\n" if text.endswith("\n") else "\n\n")
        text = text + joiner + SECTION.format(mode=mode)
    path.write_text(text, encoding="utf-8")
    return path


def sentence(mode: str) -> str:
    """One line for a session's context, stating the policy an agent is under."""
    if mode == "auto":
        return ("Commit policy is `auto`: commit the nodes you write — a session's result "
                "via /log, a capture filed by /triage — then say what you committed; the "
                "user edits afterward. Never invent a node nothing recorded, never hand-edit "
                "`status:`, never write in the user's voice.")
    return ("Commit policy is `ask`: draft a node, show it, and commit only after the "
            "user confirms. Never commit a node they haven't seen.")


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn policy",
        description="Read or set the graph's commit policy (ask | auto).")
    p.add_argument("mode", nargs="?", choices=MODES, help="set the mode; omit to read it")
    p.add_argument("--quiet", action="store_true", help="print only the mode")
    args = p.parse_args()

    root = graph_root()
    if not (root / "nodes").is_dir():
        print(f"cairn policy: no graph at {root} — export CAIRN_ROOT or run cairn init",
              file=sys.stderr)
        return 2

    if args.mode:
        before = read_commit_mode(root)
        path = write_commit_mode(args.mode, root)
        if args.quiet:
            print(args.mode)
            return 0
        print(f"commit_mode: {before} -> {args.mode}  ({path})")
        print(f"  {args.mode}: {MEANING[args.mode]}.")
        print("  It is a line in the graph's CLAUDE.md, so it is a diff — commit it when you")
        print("  are happy with it. It takes effect in the next session.")
        return 0

    mode = read_commit_mode(root)
    if args.quiet:
        print(mode)
        return 0
    source = policy_file(root)
    try:
        stated = LINE_RE.search(source.read_text(encoding="utf-8")) if source.exists() else None
    except (OSError, ValueError):
        stated = None
    print(f"commit_mode: {mode}" + ("" if stated else "  (not stated — the default)"))
    print(f"  {MEANING[mode]}.")
    print(f"  set in {source} — change it with: cairn policy {'ask' if mode == 'auto' else 'auto'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
