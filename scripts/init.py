#!/usr/bin/env python3
"""Create a research graph: the repo a person's own record lives in.

The tool and the graph are separate repos (2026-08-27-cairn-repo-topology). This
is the command that makes the second one, so that "install Cairn" and "start my
graph" are two steps instead of one fork.

    cairn init ~/research-graph
    cairn init ~/research-graph --name "Jeff's research graph"

Deliberately importing nothing from lib: this runs before PyYAML is necessarily
installed, and the first thing a new machine does should not be able to fail on a
dependency. It creates directories, writes three files, and says what to export.

It never touches an existing graph. A directory that already has nodes/ is
refused rather than merged into — one graph per repo, and a merge here would be
the fork this design ruled out.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

DIRS = ["nodes", "papers", "meetings", "inbox", "assets", "build"]

GITIGNORE = """__pycache__/
*.pyc
.DS_Store
.venv/
build/.last-sync
"""

CLAUDE_MD = """# {name}

This repo is **the graph**: one person's record of research activity across
projects — experiments, dead ends, open threads, papers, milestones, tasks. It
holds no tooling. The tool lives in the `cairn` repo and reaches this one through
`$CAIRN_ROOT`.

**The one rule that overrides every other rule: capture wins.** A node with a
messy body beats a missing node, every time. A graph at 60% coverage is worse
than no graph, because you cannot trust a missing node to mean "not tried".

## What goes where

| path | contents |
|---|---|
| `nodes/<id>.md` | the graph. One file per node, never deleted, never moved |
| `papers/<doi-slug>.md` | one page per cited paper, CrossRef-verified metadata |
| `meetings/<date>-<who>.md` | meeting notes, raw |
| `inbox/<date>-<hhmm>.md` | unstructured capture, awaiting triage |
| `assets/` | small figures only — one per node |
| `build/` | generated. Never hand-edit |

Nothing heavy ever enters this repo. Big outputs are referenced by `host:/path`,
code by `repo` + `commit`, so the repo stays text-only and small forever.

## The conventions

Node rules, the schema, how to write a node, and what the agent should do at the
start and end of a session are documented **in the tool repo** — read
`$CAIRN_PATH/CLAUDE.md` and `$CAIRN_PATH/docs/schema.md`. They are versioned
with the code that enforces them, so they cannot drift from the validator.

## Project keys used here

Add a line when a project starts, so an agent can see the vocabulary without
grepping every node. `--project` is checked against the keys already in the
graph, because it is the one field whose typo validates cleanly.

<!-- e.g. `polyid` — polymer property prediction -->
"""

README_MD = """# {name}

A git-backed graph of research activity: experiments, dead ends, open threads,
papers, milestones. One file per node, append-only, never renamed.

It is read and written with [Cairn](../cairn), which lives in its own repo:

```sh
export CAIRN_PATH=/path/to/cairn            # the tool
export CAIRN_ROOT={root}   # this graph
$CAIRN_PATH/bin/cairn standup               # what to pick up today
$CAIRN_PATH/bin/cairn doctor                # is this machine set up?
```

`build/graph.html` is the map — a single self-contained file, opened from disk.
Regenerate it with `cairn build`.

## Why the record exists

So that six months from now, *"did we already try this, and what happened?"* has
an answer, and *"what should I do next?"* has a defensible one. Dead ends are the
most valuable nodes here: they are the ones ordinary git workflow is designed to
garbage-collect, and they are what makes a methods section writable.
"""


def run(args: list[str], cwd: Path) -> bool:
    try:
        subprocess.run(args, cwd=str(cwd), check=True, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="cairn init", description="create a research graph repo")
    ap.add_argument("path", help="where the graph should live")
    ap.add_argument("--name", default="", help="human name for the graph")
    ap.add_argument("--no-git", action="store_true",
                    help="skip git init and the pre-commit hook")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    name = args.name or f"{root.name}"
    tool = Path(__file__).resolve().parent.parent

    if (root / "nodes").is_dir():
        print(f"cairn init: {root} already has a nodes/ — refusing.\n"
              "  One graph per repo. To use it, export CAIRN_ROOT and stop here.",
              file=sys.stderr)
        return 2

    root.mkdir(parents=True, exist_ok=True)
    for d in DIRS:
        (root / d).mkdir(exist_ok=True)
        # Git tracks files, not directories, and an empty inbox/ that vanishes on
        # clone is a capture path that silently does not exist on the new machine.
        keep = root / d / ".gitkeep"
        if not any(p for p in (root / d).iterdir() if p.name != ".gitkeep"):
            keep.touch()

    wrote = []
    for rel, text in (
        (".gitignore", GITIGNORE),
        ("CLAUDE.md", CLAUDE_MD.format(name=name)),
        ("README.md", README_MD.format(name=name, root=root)),
    ):
        p = root / rel
        if p.exists():
            continue
        p.write_text(text, encoding="utf-8")
        wrote.append(rel)

    print(f"cairn init — {root}")
    print("  created " + ", ".join(f"{d}/" for d in DIRS))
    if wrote:
        print("  wrote   " + ", ".join(wrote))

    if not args.no_git:
        if (root / ".git").exists():
            print("  git     already a repo")
        elif run(["git", "init", "-q"], root):
            print("  git     initialised")
        else:
            print("  git     init failed — do it by hand")
        hooks = tool / "scripts" / "install_hooks.sh"
        if (root / ".git").exists() and run([str(hooks), str(root)], root):
            print("  hook    pre-commit validation enabled")
        else:
            print(f"  hook    not installed — run: {hooks} {root}")

    print()
    print("Add these to your shell profile:")
    print(f"  export CAIRN_PATH={tool}")
    print(f"  export CAIRN_ROOT={root}")
    print()
    print("Then, so every Claude session on this machine sees the graph:")
    print(f"  {tool}/bin/cairn install_context --apply")
    print()
    print("An empty graph means nothing for months, and during those months a")
    print("missing node means 'we had not started', not 'not tried'. Backfill")
    print("before trusting a gap — see $CAIRN_PATH/docs/backfill.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
