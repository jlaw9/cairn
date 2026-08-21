#!/usr/bin/env python3
"""Append an unstructured note to inbox/. No schema, no validation, no refusal.

This is the junk drawer, and the junk drawer is load-bearing. Design decision 7
says capture is not structure: the moment capture asks you which project this
belongs to, or what type of node it is, the answer becomes "later" and later
never comes. So this command has exactly one failure mode worth engineering
against — not writing the file.

Which means: **it never validates, never prompts, and never exits non-zero for a
content reason.** An empty note, a note with no project, a note that is three
words of nonsense at 11pm: all written. `/triage` sorts it out later, when
sorting it out is the task you have chosen to do rather than a toll on the task
you were actually doing.

What it *does* record, because these are free and they are what makes triage
possible weeks later: when, where, which host, and which repo at which commit if
the note was written inside one. That is the context you cannot reconstruct from
the text, and it is exactly the context you will wish you had.

    cairn capture "the CG block-size distribution might be bimodal"
    cairn capture --project mdegrade "check whether q depends on stack size"
    cairn capture                       # opens $EDITOR
    somecommand | cairn capture --title "why the run died"
    cairn capture --from-file ~/notes.org --title "meeting with Dave"

The `--from-file` form is how org-mode reaches this. Org markup lands verbatim:
inbox/ has no schema, so a .md file containing org syntax is not a problem to be
solved, it is a file with text in it. Do not convert anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Deliberately NOT importing lib. lib imports PyYAML and exits the process if it
# is missing, and capture is the one command that must work on a machine where
# Cairn is otherwise broken — losing a thought to a dependency error is the exact
# failure this file exists to prevent. Hence the hand-rolled root lookup below.
REPO_ROOT = Path(os.environ.get("CAIRN_ROOT") or Path(__file__).resolve().parent.parent)


def run(*cmd: str, cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=cwd)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def context(where: Path) -> list[str]:
    """Where this note was written, in the terms a node would use later.

    `repo` + `commit` rather than a path, because that is what a node needs and
    a path on a machine you are not currently on resolves to nothing.
    """
    lines = []
    host = run("hostname", "-s") or run("hostname") or os.environ.get("HOSTNAME", "")
    if host:
        lines.append(f"host: {host}")
    lines.append(f"cwd: {where}")
    top = run("git", "rev-parse", "--show-toplevel", cwd=where)
    if top:
        remote = run("git", "remote", "get-url", "origin", cwd=where)
        sha = run("git", "rev-parse", "HEAD", cwd=where)
        dirty = run("git", "status", "--porcelain", cwd=where)
        lines.append(f"repo: {remote or Path(top).name}")
        if sha:
            lines.append(f"commit: {sha}{' (dirty tree)' if dirty else ''}")
    return lines


def from_editor() -> str:
    """Open $EDITOR on a scratch file. Empty result is still a valid outcome."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as handle:
        scratch = Path(handle.name)
    try:
        subprocess.run([*editor.split(), str(scratch)])
        return scratch.read_text(encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cairn: editor failed ({exc}); nothing captured", file=sys.stderr)
        return ""
    finally:
        scratch.unlink(missing_ok=True)


def unique_path(folder: Path, stamp: dt.datetime) -> Path:
    """inbox/<date>-<hhmm>.md, suffixed if that minute is already taken.

    Two notes in one minute is a real thing — a burst of thoughts is the case
    this command is *for* — and silently overwriting the first would be the one
    unforgivable bug in a capture tool.
    """
    base = f"{stamp.date().isoformat()}-{stamp.strftime('%H%M')}"
    path = folder / f"{base}.md"
    serial = 2
    while path.exists():
        path = folder / f"{base}-{serial}.md"
        serial += 1
    return path


def main() -> int:
    p = argparse.ArgumentParser(
        description="Append an unstructured note to Cairn's inbox. Never refuses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("    cairn capture", 1)[-1] if __doc__ else None,
    )
    p.add_argument("text", nargs="*", help="the note; omit to read stdin or open $EDITOR")
    p.add_argument("--title", default="", help="one-line subject, for scanning inbox/ later")
    p.add_argument("--project", default="",
                   help="a hint for triage, not a validated key — typos are fine here")
    p.add_argument("--from-file", metavar="PATH",
                   help="capture a file's contents verbatim (org, md, anything)")
    p.add_argument("--tag", action="append", default=[], metavar="TAG",
                   help="freeform tag; repeatable")
    args = p.parse_args()

    if args.from_file:
        source = Path(args.from_file).expanduser()
        try:
            body = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # The one legitimate hard failure: the input does not exist, so there
            # is nothing to lose by saying so.
            sys.exit(f"cairn capture: cannot read {source}: {exc}")
    elif args.text:
        body = " ".join(args.text)
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        body = from_editor()

    if not body.strip():
        print("cairn: nothing to capture (empty note)", file=sys.stderr)
        return 0                      # not an error; you changed your mind

    stamp = dt.datetime.now()
    folder = REPO_ROOT / "inbox"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.exit(f"cairn capture: cannot write to {folder}: {exc}")

    # A plain markdown heading and a context block, not YAML frontmatter. Anything
    # that looks like frontmatter invites a validator, and the whole value of
    # inbox/ is that nothing here is ever validated.
    title = args.title.strip() or re.sub(r"\s+", " ", body.strip()).strip()[:72]
    header = [f"# {title}", "", f"captured: {stamp.isoformat(timespec='seconds')}"]
    if args.project:
        header.append(f"project (unverified): {args.project}")
    if args.tag:
        header.append(f"tags: {', '.join(args.tag)}")
    header += context(Path.cwd())
    if args.from_file:
        header.append(f"source: {Path(args.from_file).expanduser()}")

    path = unique_path(folder, stamp)
    try:
        path.write_text("\n".join(header) + "\n\n" + body.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        sys.exit(f"cairn capture: write failed: {exc}")

    print(f"captured: {path.relative_to(REPO_ROOT)}")
    # Deliberately does not commit. A capture that triggers a commit hook is a
    # capture that can fail on a validation error somewhere else in the graph,
    # and inbox/ exists precisely so that cannot happen. `/triage` commits.
    return 0


if __name__ == "__main__":
    sys.exit(main())
