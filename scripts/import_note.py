#!/usr/bin/env python3
"""Bring an outside note into the graph verbatim: a meeting, a mail, a scrap.

`capture` exists for a thought you have at a terminal. This is for a *file* that
already exists somewhere else — the org-mode buffer from a meeting, a pasted
mail, a page of handwriting you typed up, the notes someone sent you. Two things
make it a separate command rather than a flag on `capture`:

    cairn import_note ~/notes/2026-08-26-dave.org --meeting --who dave
    cairn import_note ~/Downloads/scribbles.md --project polyid
    pbpaste | cairn import_note --meeting --who "dave, sarah" --title "CG handoff"

**Meetings have their own home and their own filename convention.**
`meetings/<date>-<who>.md` is in the repo layout because a meeting note is a
durable record you will want to find by who was in the room, not a queue item
that gets consumed. `inbox/<date>-<hhmm>.md` is a queue item. Sending both to the
inbox would lose that, and sending both to `meetings/` would mean the inbox never
sees them and nothing ever gets triaged out of them.

**So a meeting import writes two files, and that is the point.** The note itself
goes to `meetings/`, and a one-line pointer goes to `inbox/`. The record is
permanent; the *obligation to read it* is a queue item that `/triage` consumes.
Design decision 7 with the two halves kept apart.

Everything else is `capture`'s contract, deliberately: content lands verbatim
with no conversion (org markup in a `.md` file is not a problem to be solved), it
records host/cwd/repo/commit, `--project` is an unvalidated hint, it never
prompts, and it does not commit — because committing runs the validation hook,
and an import that can fail on unrelated schema drift is not an import.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# capture.py is lib-free by design and carries exactly the context-recording and
# collision-avoiding logic this needs; reusing it means there is one answer to
# "what does a captured note look like" rather than two that drift.
import capture

REPO_ROOT = capture.REPO_ROOT


def slug(text: str) -> str:
    """A filename-safe fragment. Never parsed back into anything."""
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:48] or "note"


def meeting_path(folder: Path, when: dt.date, who: str) -> Path:
    """meetings/<date>-<who>.md, suffixed if that name is taken.

    Suffixed rather than overwritten for the same reason capture suffixes: two
    meetings with the same person on the same day is a real thing, and silently
    replacing the morning's notes with the afternoon's is unforgivable.
    """
    base = f"{when.isoformat()}-{slug(who) if who else 'meeting'}"
    path = folder / f"{base}.md"
    serial = 2
    while path.exists():
        path = folder / f"{base}-{serial}.md"
        serial += 1
    return path


def read_source(paths: list[str]) -> tuple[str, list[str]]:
    """(text, names of the files it came from). stdin when no paths are given."""
    if not paths:
        if sys.stdin.isatty():
            return capture.from_editor(), []
        return sys.stdin.read(), []

    chunks, names = [], []
    for raw in paths:
        path = Path(raw).expanduser()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            # Report and carry on. Losing three good files because the fourth
            # was unreadable is the wrong trade for a capture tool.
            print(f"cairn: cannot read {path}: {exc}", file=sys.stderr)
            continue
        names.append(path.name)
        header = f"\n\n---\n\n## {path.name}\n\n" if len(paths) > 1 else ""
        chunks.append(header + text)
    return "".join(chunks), names


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn import_note",
        description="Bring an outside file into meetings/ or inbox/, verbatim.")
    p.add_argument("paths", nargs="*", help="files to import; omit to read stdin or $EDITOR")
    p.add_argument("--meeting", action="store_true",
                   help="file under meetings/ and queue a pointer in inbox/")
    p.add_argument("--who", default="", help="with --meeting: who was in the room")
    p.add_argument("--date", default="", help="ISO date of the note; default today")
    p.add_argument("--title", default="", help="one-line subject")
    p.add_argument("--project", default="", help="project hint for triage (unvalidated)")
    p.add_argument("--tag", action="append", default=[], metavar="TAG")
    p.add_argument("--move", action="store_true",
                   help="delete the source file(s) after a successful import")
    args = p.parse_intermixed_args()

    text, names = read_source(args.paths)
    if not text.strip():
        print("cairn: nothing to import (no text)", file=sys.stderr)
        return 1

    when = dt.date.today()
    if args.date:
        try:
            when = dt.date.fromisoformat(args.date)
        except ValueError:
            print(f"cairn: --date {args.date!r} is not an ISO date; using today",
                  file=sys.stderr)

    stamp = dt.datetime.now()
    title = args.title or (names[0] if names else "") or ("meeting" if args.meeting else "note")
    context = capture.context(Path.cwd())

    meta = [f"# {title}", ""]
    if args.meeting and args.who:
        meta.append(f"who: {args.who}")
    meta.append(f"date: {when.isoformat()}")
    if args.project:
        meta.append(f"project: {args.project}")
    if args.tag:
        meta.append(f"tags: {', '.join(args.tag)}")
    if names:
        meta.append(f"imported-from: {', '.join(names)}")
    meta += context + ["", "---", ""]
    body = "\n".join(meta) + "\n" + text.rstrip() + "\n"

    written: list[Path] = []

    if args.meeting:
        folder = REPO_ROOT / "meetings"
        folder.mkdir(parents=True, exist_ok=True)
        target = meeting_path(folder, when, args.who)
        target.write_text(body, encoding="utf-8")
        written.append(target)

        # The pointer, not a copy. A meeting note is a record; the thing that
        # belongs in a queue is "somebody should read this and decide what it
        # means", which is one line.
        inbox = REPO_ROOT / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        pointer = capture.unique_path(inbox, stamp)
        who = f" with {args.who}" if args.who else ""
        pointer.write_text(
            "\n".join([
                f"# triage: meeting{who} ({when.isoformat()})",
                "",
                f"project: {args.project}" if args.project else "",
                *context,
                "",
                "---",
                "",
                f"Meeting notes imported to `{target.relative_to(REPO_ROOT)}`.",
                "Read them and decide what becomes a node, a task, or nothing.",
                "",
                f"First lines:",
                "",
                *[f"> {line}" for line in text.strip().splitlines()[:8]],
            ]) + "\n",
            encoding="utf-8")
        written.append(pointer)
    else:
        inbox = REPO_ROOT / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        target = capture.unique_path(inbox, stamp)
        target.write_text(body, encoding="utf-8")
        written.append(target)

    for path in written:
        print(path.relative_to(REPO_ROOT))

    if args.move:
        for raw in args.paths:
            source = Path(raw).expanduser()
            try:
                source.unlink()
                print(f"removed {source}")
            except OSError as exc:
                print(f"cairn: kept {source} ({exc})", file=sys.stderr)

    print("\n  Not committed — `/triage` turns the inbox item into nodes, or discards it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
