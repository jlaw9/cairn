#!/usr/bin/env python3
"""Mine Claude Code session transcripts for the raw material of a backfill.

Adopting Cairn into work that already happened is the difference between a
graph you can trust on day one and one that means nothing for six months —
"a graph at 60% coverage is worse than none, because you can't trust a missing
node to mean 'not tried'."

The transcripts under ~/.claude/projects/<slugified-cwd>/*.jsonl are the best
record of that work, and better than the repo for the thing that matters most:
they contain the dead ends. A commit log shows what was kept.

    scripts/mine_sessions.py                        # one line per session
    scripts/mine_sessions.py --project rotachrom    # filter by directory slug
    scripts/mine_sessions.py --detail --project rotachrom
    scripts/mine_sessions.py --summaries            # densest recap available
    scripts/mine_sessions.py --json sessions.json

This reads only. It never writes a node — see docs/backfill.md for why that
step stays manual.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

#: Harness chatter that is not the user talking. Mid-conversation these swamp
#: the actual instructions — task notifications alone outnumbered real messages
#: 4:1 in the 2026-08 backfill.
NOISE = re.compile(
    r"^\s*(<task-notification>|<local-command-caveat>|<command-args>|<command-message>"
    r"|<interrupted-output>|\[Request interrupted|Base directory for this skill:"
    r"|\(Re-invocation of"
    # Skill bodies arrive as user messages, verbatim and identical across
    # sessions. They read like instructions because they are — just not Jeff's.
    r"|Approach this as the design lead"
    r"|A chart is \*\*read by people)",
    re.I,
)
STRIP = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<local-command-stdout>.*?</local-command-stdout>", re.S),
]
CONTINUED = "This session is being continued"


def text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def clean(text: str) -> str:
    for pattern in STRIP:
        text = pattern.sub("", text)
    return text.strip()


def read_session(path: str) -> dict:
    title = cwd = first_ts = last_ts = None
    prompts: list[str] = []
    summaries: list[str] = []
    turns = 0

    with open(path, errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = record.get("type")
            if kind == "ai-title" and not title:
                title = record.get("aiTitle")
            if record.get("cwd") and not cwd:
                cwd = record["cwd"]
            stamp = record.get("timestamp")
            if stamp:
                first_ts = first_ts or stamp
                last_ts = stamp
            if kind == "assistant":
                turns += 1
            elif kind == "user":
                body = clean(text_of(record.get("message") or {}))
                if body.startswith(CONTINUED):
                    summaries.append(body)
                elif body and len(body) > 25 and not NOISE.match(body):
                    prompts.append(body)

    return {
        "project": os.path.basename(os.path.dirname(path)),
        "file": os.path.basename(path),
        "title": title,
        "cwd": cwd,
        "start": (first_ts or "")[:10],
        "end": (last_ts or "")[:10],
        "turns": turns,
        "prompts": prompts,
        # Only the last compaction matters: each one folds in its predecessors.
        "summary": summaries[-1] if summaries else "",
        "compactions": len(summaries),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    parser.add_argument("--project", help="substring match on the directory slug")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="sessions ending on or after")
    parser.add_argument("--detail", action="store_true", help="show prompts per session")
    parser.add_argument("--summaries", action="store_true", help="dump the last compaction summary")
    parser.add_argument("--json", metavar="PATH", help="write everything as JSON")
    parser.add_argument("--chars", type=int, default=2000, help="truncation width for --summaries")
    args = parser.parse_args()

    paths = sorted(glob.glob(os.path.join(args.root, "*", "*.jsonl")))
    if not paths:
        sys.exit(f"no transcripts under {args.root}")

    sessions = []
    for path in paths:
        if args.project and args.project not in os.path.basename(os.path.dirname(path)):
            continue
        session = read_session(path)
        if args.since and session["end"] and session["end"] < args.since:
            continue
        sessions.append(session)

    if args.json:
        with open(args.json, "w") as handle:
            json.dump(sessions, handle, indent=1)
        print(f"{len(sessions)} session(s) -> {args.json}")
        return 0

    sessions.sort(key=lambda s: (s["project"], s["start"]))

    if args.summaries:
        for session in sessions:
            if not session["summary"]:
                continue
            print("#" * 100)
            print(f"## {session['project']}\n## {session['title']}  "
                  f"[{session['compactions']} compaction(s)]")
            print(session["summary"][: args.chars])
        return 0

    for session in sessions:
        print(f"{session['start']}..{session['end']} {session['turns']:5d}t  "
              f"{session['project'][:58]:60s} {(session['title'] or '?')[:64]}")
        if args.detail:
            for prompt in session["prompts"][:20]:
                flat = " ".join(prompt.split())
                print(f"      · {flat[:220]}")
            print()

    print(f"\n{len(sessions)} session(s), {sum(s['turns'] for s in sessions)} assistant turns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
