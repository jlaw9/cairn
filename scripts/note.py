#!/usr/bin/env python3
"""Add a human sentence to a node after the fact, and read those back.

The gap this fills: the agent writes the record, and the person reading it later
has a reaction — a doubt, a correction, "this is the one that matters", "the
number here is wrong". Until now the only places to put that were a status
change, which lies about what happened, and the inbox, which detaches the
thought from the node it is about.

    cairn note 2026-07-20-polyid-run-variance "the spread looks bimodal — seeds?"
    cairn note 2026-08-02-prekd-cosmo-baseline          # opens $EDITOR
    cairn note --list                                   # every note, newest first
    cairn note --list --project polyid --days 30

**It is a body edit, not a status change.** `status`, `updated` and `history` do
not move, because a note is not a claim about the state of the work — see the
design note above `NOTES_HEADING` in lib.py. That is also why it needs no new
field: the note line carries its own date, so `standup` and `digest` can find it
by reading the body, exactly as they already read `## Next`.

**It commits by default**, which is the one place this deliberately differs from
`capture`. Design decision 6 refuses to commit a node *Jeff hasn't seen*; a
sentence he just typed is the definition of seen, and the whole value of a note
is that it is visible from the other machine tomorrow. The note is written to
the file before the commit is attempted, so a commit that fails on unrelated
schema drift costs the note nothing — it is already on disk, and the message
says so.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib


def git(*args: str, cwd: Path | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(
            ["git", "-C", str(cwd or lib.REPO_ROOT), *args],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def whoami() -> str:
    """A short handle for the note line, derived rather than configured.

    Same argument as authorship: `git log --diff-filter=A` already answers "whose
    node is this", so a note should not introduce a name to keep in sync either.
    The local part of the git email is short, stable, and the thing a second
    reader will recognise.
    """
    code, email = git("config", "user.email")
    if code == 0 and "@" in email:
        return email.split("@", 1)[0]
    code, name = git("config", "user.name")
    if code == 0 and name:
        return name.split()[0].lower()
    return os.environ.get("USER", "")


def from_editor(node: lib.Node) -> str:
    """Open $EDITOR with the node's title as a comment, so the context is visible."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    preamble = (
        f"\n# Note on {node.id}\n"
        f"# {node.title}\n"
        f"# status: {node.status}   project: {node.project}\n"
        "# Lines starting with # are dropped. One note, one thought.\n"
    )
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as handle:
        handle.write(preamble)
        scratch = Path(handle.name)
    try:
        subprocess.run([*editor.split(), str(scratch)])
        text = scratch.read_text(encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cairn: editor failed ({exc}); nothing written", file=sys.stderr)
        return ""
    finally:
        scratch.unlink(missing_ok=True)
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#")).strip()


def resolve(nodes: dict, wanted: str) -> lib.Node | None:
    """Exact id, else a unique suffix/substring match.

    Typing a full `2026-07-20-polyid-run-variance` to leave a one-line note is
    the kind of friction that stops notes being left, so `polyid-run-variance`
    and `run-variance` both work. Ambiguity is reported, never guessed at.
    """
    if wanted in nodes:
        return nodes[wanted]
    hits = [n for n in nodes.values() if wanted.lower() in n.id.lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        print(f"cairn: no node matching '{wanted}'", file=sys.stderr)
        return None
    print(f"cairn: '{wanted}' matches {len(hits)} nodes:", file=sys.stderr)
    for node in sorted(hits, key=lambda n: n.id)[:10]:
        print(f"  {node.id}  {node.title}", file=sys.stderr)
    return None


def list_notes(nodes: dict, project: str, days: int) -> int:
    """Every note in the graph, newest first. This is the read path for notes."""
    cutoff = dt.date.today() - dt.timedelta(days=days) if days else None
    rows = []
    for node in nodes.values():
        if project and node.project != project:
            continue
        for note in lib.read_notes(node):
            if cutoff and (not note["date"] or note["date"] < cutoff):
                continue
            rows.append((note["date"] or dt.date.min, node, note))
    if not rows:
        window = f" in the last {days} days" if days else ""
        print(f"No notes{window}." if not project else f"No notes on {project}{window}.")
        return 0

    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"{len(rows)} note(s), newest first\n")
    for date, node, note in rows:
        who = f" ({note['who']})" if note["who"] else ""
        print(f"  {date}{who}  {node.id}")
        print(f"      {node.title}")
        print(f"      {note['text']}\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn note",
        description="Add a dated note to a node's body, or read notes back.",
    )
    p.add_argument("node", nargs="?", default="",
                   help="node id, or enough of one to be unambiguous")
    p.add_argument("text", nargs="*", help="the note; omit to open $EDITOR")
    p.add_argument("--list", action="store_true", help="print notes instead of adding one")
    p.add_argument("--project", default="", help="with --list, one project only")
    p.add_argument("--days", type=int, default=0,
                   help="with --list, only notes this recent (0 = all)")
    p.add_argument("--who", default="", help="override the derived handle")
    p.add_argument("--date", default="", help="ISO date for the note; default today")
    p.add_argument("--no-commit", action="store_true",
                   help="write the note but leave it uncommitted")
    # parse_intermixed_args, not parse_args: the natural way to type this is
    # `cairn note <id> --no-commit "the text"`, and with a trailing nargs="*"
    # plain parse_args rejects that as an unrecognised argument. The error names
    # the note text, which reads as "your sentence is wrong" — a bad way to find
    # out about a flag-ordering rule you shouldn't have to know.
    args = p.parse_intermixed_args()

    nodes, errors = lib.load_nodes()
    for error in errors:
        print(f"cairn: {error}", file=sys.stderr)

    if args.list:
        return list_notes(nodes, args.project, args.days)

    if not args.node:
        p.error("which node? (`cairn note --list` to read notes instead)")

    node = resolve(nodes, args.node)
    if node is None:
        return 1

    text = " ".join(args.text).strip() or from_editor(node)
    if not text:
        print("cairn: empty note, nothing written", file=sys.stderr)
        return 1

    when = lib.as_date(args.date) if args.date else dt.date.today()
    if args.date and when is None:
        p.error(f"--date {args.date!r} is not an ISO date")

    line = lib.append_note(node, text, who=args.who or whoami(), when=when)
    node.write()
    rel = node.path.relative_to(lib.REPO_ROOT)
    print(f"{rel}\n  {line}")

    if args.no_commit:
        print("\n  not committed (--no-commit). It won't reach your other machine "
              "until you push.")
        return 0

    # --only so a note never drags an unreviewed node draft into the same commit.
    code, text_out = git("commit", "--only", str(rel), "-m",
                         f"note on {node.id}: {' '.join(text.split())[:60]}")
    if code == 0:
        print("  committed. `cairn sync --push` to make it visible elsewhere.")
    else:
        print("\n  The note is written, but the commit failed — nothing is lost:")
        for out_line in text_out.splitlines()[:10]:
            print(f"    {out_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
