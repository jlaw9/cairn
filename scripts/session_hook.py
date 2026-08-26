#!/usr/bin/env python3
"""What a Claude session is told about the graph, at its start and at its end.

This is the answer to "how does an agent in some other repo know Cairn exists".
The previous answer was one line pasted into each project's `CLAUDE.md`, which
fails the way every per-repo step fails: it covers the repos you remembered, and
sessions get started in directories that have no `CLAUDE.md` at all.

A `SessionStart` hook covers every session in every directory on this machine,
and it can do something a pointer cannot — it returns
`hookSpecificOutput.additionalContext`, so the session begins already knowing
what the graph says needs attention. The difference matters: a pointer has to be
*followed*, and an agent mid-task does not go looking. Two lines of state that
are already in context get used.

    cairn session_hook             # SessionStart: pull, then inject state
    cairn session_hook --end       # SessionEnd: warn about unpushed work
    cairn session_hook --dry-run   # print the block instead of the JSON

Three rules, all of them about not being annoying:

1. **It always exits 0 and always prints valid JSON.** A hook that errors is a
   hook that gets deleted, and then the graph is invisible again.
2. **The pull is throttled and time-boxed.** Starting a session should not wait
   on the network. Once every THROTTLE_MIN minutes is enough to close the habit
   gap it exists to close.
3. **The injected block is short.** It is paid for on every session in every
   repo, so it carries the pointer plus what actually needs a human, and stops.
   The full view is one command away and named in the block.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# No `import lib` — same reason as capture.py and sync.py. This runs before
# anything else in a session, on whatever machine that is, and it must not be
# able to fail. Everything it needs it gets by shelling out to bin/cairn.
REPO_ROOT = Path(os.environ.get("CAIRN_ROOT") or Path(__file__).resolve().parent.parent)

#: Don't pull more than this often. A session started every few minutes while
#: working shouldn't hit the network every time.
THROTTLE_MIN = 30

#: Hard ceiling on everything this hook does. Session start is latency the user
#: feels directly, so a slow remote must degrade to "no pull", never to a wait.
BUDGET_S = 20

STAMP = REPO_ROOT / "build" / ".last-sync"


def run(*cmd: str, timeout: int = 10) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(REPO_ROOT))
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, (done.stdout or "").strip()


def cairn(*args: str, timeout: int = 10) -> str:
    code, text = run(str(REPO_ROOT / "bin" / "cairn"), *args, timeout=timeout)
    return text if code == 0 else ""


def due_for_pull() -> bool:
    try:
        return (time.time() - STAMP.stat().st_mtime) > THROTTLE_MIN * 60
    except OSError:
        return True


def mark_pulled() -> None:
    try:
        STAMP.parent.mkdir(parents=True, exist_ok=True)
        STAMP.touch()
    except OSError:
        pass


def attention() -> list[str]:
    """The few lines worth spending session context on."""
    lines = []

    # `standup` is the ranked view and its first lines are the summary; take
    # those rather than re-deriving the ranking here, so there is one definition
    # of "needs attention" and not a second that can drift from it.
    text = cairn("standup", timeout=25)
    if text:
        body = [l for l in text.splitlines() if l.strip()]
        # Match the summary lines by what they say rather than by position: a
        # slice broke the moment a new count line was added above the projects,
        # and silently promoted the first project header into the counts.
        MARKERS = ("thread(s)", "note(s)", "inbox item(s)")
        for line in body[1:6]:
            if any(m in line for m in MARKERS):
                lines.append(line.strip())
        # Then the top-ranked project header — the "start here" hint. Headers are
        # flush-left and followed by a rule of dashes; entries are indented.
        for index, line in enumerate(body[1:], start=1):
            if (not line[:1].isspace() and any(m in line for m in MARKERS) is False
                    and index + 1 < len(body) and set(body[index + 1].strip()) == {"-"}):
                lines.append(f"most needs you: {line.strip()}")
                break

    lines += sync_summary()
    return lines


def sync_summary() -> list[str]:
    """`sync --check` reduced to its count lines.

    sync prints the offending filenames because at a terminal that is what you
    act on. Here it is noise: both callers want "how much is unshared", and a
    seven-line file listing inside a one-line system message reads as a fault.
    """
    out = []
    for line in cairn("sync", "--check", "--quiet", timeout=15).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("cairn:", "`cairn", "read the drafts",
                                "nodes/", "papers/", "…")):
            continue
        out.append(stripped.rstrip(":"))
    return out


def start_block() -> str:
    """The context injected at session start. Keep it tight; it is paid for often."""
    root = REPO_ROOT
    parts = [
        "# Cairn — the research record",
        "",
        f"Research activity across all of Jeff's projects is recorded in Cairn, a",
        f"git-backed graph of experiments, dead ends, open threads and deadlines at",
        f"`{root}`.",
        "",
        "**Before proposing work** in a project repo, read what is already settled:",
        f"`{root}/bin/cairn standup --project <key>`. A `dead` node is a claim already",
        "refuted, with the reason attached — cite it instead of re-running it.",
        "",
        "**After doing work**, record it with `/log` from inside the project repo.",
        "**A thought you don't want to file**: `cairn capture \"...\"` — never refuses,",
        "never prompts, goes to `inbox/` for later triage.",
        "**A reaction to an existing node**: `cairn note <node-id> \"...\"`.",
        "",
        "Never commit a node Jeff hasn't seen. Anything written unprompted goes to",
        f"`inbox/`. Conventions: `{root}/CLAUDE.md` and `{root}/skills/`.",
    ]
    state = attention()
    if state:
        parts += ["", "## State right now", ""] + [f"- {line}" for line in state]
    return "\n".join(parts)


def end_lines() -> list[str]:
    """At session end, the only thing worth saying is what isn't shared yet."""
    return sync_summary()


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn session_hook",
        description="Emit Claude Code session hook JSON for the graph.")
    p.add_argument("--end", action="store_true", help="SessionEnd instead of SessionStart")
    p.add_argument("--dry-run", action="store_true",
                   help="print the human-readable block instead of hook JSON")
    args = p.parse_args()

    # Hooks are handed JSON on stdin and nothing here needs it — but draining it
    # has to be non-blocking. `isatty()` is false whenever stdin is a pipe that
    # nobody is going to write to (a manual run, a `--dry-run` from a script), and
    # a bare read() there waits for an EOF that never comes: the hook hangs, and
    # so does every session start on the machine. select() first, always.
    try:
        import select
        while select.select([sys.stdin], [], [], 0.05)[0]:
            if not sys.stdin.read(65536):
                break
    except Exception:                              # noqa: BLE001 - draining is optional
        pass

    if not (REPO_ROOT / "nodes").is_dir():
        # No graph here. Say nothing at all rather than nagging about a path.
        print("{}")
        return 0

    if args.end:
        lines = end_lines()
        if args.dry_run:
            print("\n".join(lines) or "(nothing unshared)")
            return 0
        if not lines:
            print("{}")
            return 0
        message = "cairn: " + "; ".join(lines) + " — `cairn sync --push`"
        print(json.dumps({"systemMessage": message}))
        return 0

    if due_for_pull():
        run(str(REPO_ROOT / "bin" / "cairn"), "sync", "--quiet", timeout=BUDGET_S)
        mark_pulled()

    block = start_block()
    if args.dry_run:
        print(block)
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": block,
        },
        # suppressOutput so the block doesn't also print into the transcript —
        # it is context for the model, not a wall of text for the reader.
        "suppressOutput": True,
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                       # noqa: BLE001 - see module docstring
        # Rule 1: never fail. A traceback here would break every session start on
        # this machine, for a feature whose entire job is to be unobtrusive.
        print(json.dumps({"systemMessage": f"cairn: session hook failed ({exc})"}))
        sys.exit(0)
