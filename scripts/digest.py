#!/usr/bin/env python3
"""Answer "what happened, and what needs me?" out of the history log.

This is the cheapest collaboration mechanism Cairn has. Most of what people mean
by collaborating on a research record is not co-editing it — it's *awareness*,
knowing what everyone else did without having to go and look. A digest in a shared
channel delivers that for a day of work, where a platform delivers it for months.
So this exists partly to find out whether the platform is needed at all.

It invents nothing. `status` is an event log and `history` carries the dates, so
"what changed this week" is a query, not new bookkeeping — which is the payoff for
design decision 5 finally being spent.

On demand is the normal case, not the exception:

    cairn digest                          # the last 7 days
    cairn digest --days 1                 # yesterday
    cairn digest --project mplastic       # right before that project's meeting
    cairn digest --since 2026-07-01 --format md
    cairn digest --mail                   # to your own git email
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

#: A node claiming to be in progress that nobody has touched in this long is the
#: thing a digest is for: it has stopped being work and become a loose end, and no
#: status change will ever announce that. Long enough not to nag about a week off.
STALE_DAYS = 14

#: Statuses that *assert activity*, and are therefore the only ones where going
#: quiet means anything. `terminal` isn't a strict enough filter on its own:
#: `parked` is non-terminal but explicitly means "paused, will resume", and an
#: `open` direction is a container that is supposed to sit for months. Nagging
#: about either is how a digest teaches people to skip the section.
ACTIVE = {"running", "doing", "submitted", "planned"}

#: How far ahead to look for deadlines. A fortnight is long enough to act on a
#: paper deadline and short enough that the list stays readable.
HORIZON_DAYS = 14


def transitions(node: lib.Node, start: dt.date, end: dt.date) -> list[dict]:
    """History entries inside the window, skipping the node's own creation.

    The creation entry is reported as "opened" instead — listing it in both places
    reads as two events when it was one.
    """
    out = []
    for i, entry in enumerate(node.history):
        when = lib.as_date(entry.get("date"))
        if when is None or not (start <= when <= end):
            continue
        if i == 0 and node.created == when:
            continue
        out.append(entry)
    return out


def previous_status(node: lib.Node, entry: dict) -> str:
    """The status this entry moved away from, so the digest can show `a -> b`."""
    prior = ""
    for candidate in node.history:
        if candidate is entry:
            break
        prior = str(candidate.get("status", "") or "")
    return prior


def gather(nodes: dict[str, lib.Node], start: dt.date, end: dt.date,
           stale_days: int, horizon_days: int) -> dict:
    opened, changed, deadlines, quiet = [], [], [], []
    for node in nodes.values():
        if node.created and start <= node.created <= end:
            opened.append(node)
        for entry in transitions(node, start, end):
            changed.append((node, entry))

        if node.is_terminal:
            continue

        # Deadlines. `due` is a task's, `date` is a milestone's; a task with no
        # due date still belongs here, because the validator warns about exactly
        # that and the warning is only true if this is where it would have shown.
        when = lib.as_date(node.meta.get("due") or node.meta.get("date"))
        if node.type in ("task", "milestone"):
            if when is None:
                deadlines.append((None, node))
            elif when <= end + dt.timedelta(days=horizon_days):
                deadlines.append((when, node))

        # Going quiet. Deadlines are already listed above; don't say it twice.
        last = node.updated or node.created
        if (node.status in ACTIVE and node.type not in ("task", "milestone")
                and last and (end - last).days >= stale_days):
            quiet.append(((end - last).days, node))

    changed.sort(key=lambda pair: (str(pair[1].get("date")), pair[0].project, pair[0].id))
    opened.sort(key=lambda n: (n.project, n.id))
    # Overdue first, then soonest, then undated — undated is worth reporting but
    # it is never the most urgent thing on the list.
    deadlines.sort(key=lambda pair: (pair[0] is None, pair[0] or dt.date.min, pair[1].id))
    quiet.sort(key=lambda pair: -pair[0])
    return {"opened": opened, "changed": changed, "deadlines": deadlines, "quiet": quiet}


def render(found: dict, start: dt.date, end: dt.date, project: str,
           horizon_days: int, markdown: bool) -> str:
    b = (lambda s: f"**{s}**") if markdown else (lambda s: s)
    bullet = "- " if markdown else "  "
    width = min(shutil.get_terminal_size((88, 24)).columns, 88)

    def head(text: str) -> str:
        return f"\n### {text}\n" if markdown else f"\n{text}\n{'-' * min(len(text), width)}"

    scope = f" — {project}" if project else ""
    lines = [f"# Cairn digest{scope}" if markdown else f"Cairn digest{scope}",
             f"{start.isoformat()} to {end.isoformat()}"]

    counts = (f"{len(found['changed'])} status change(s), {len(found['opened'])} opened, "
              f"{len(found['deadlines'])} deadline(s), {len(found['quiet'])} going quiet")
    lines.append(counts)

    if found["changed"]:
        lines.append(head("What moved"))
        for node, entry in found["changed"]:
            was, now = previous_status(node, entry), str(entry.get("status", "") or "")
            arrow = f"{was} -> {now}" if was and was != now else now
            lines.append(f"{bullet}{b(arrow)}  {node.title}")
            lines.append(f"{'  ' if markdown else '    '}{node.project} · {node.id}")
            note = str(entry.get("note", "") or "").strip()
            if note:
                lines.append(f"{'  ' if markdown else '    '}\"{note}\"")

    if found["opened"]:
        lines.append(head("Opened"))
        for node in found["opened"]:
            lines.append(f"{bullet}{b(node.type)}  {node.title}")
            lines.append(f"{'  ' if markdown else '    '}{node.project} · {node.id}")

    if found["deadlines"]:
        lines.append(head(f"Needs a decision (next {horizon_days} days)"))
        for when, node in found["deadlines"]:
            if when is None:
                flag = "no date set"
            elif when < end:
                flag = f"OVERDUE {(end - when).days}d — {when.isoformat()}"
            else:
                flag = f"due in {(when - end).days}d — {when.isoformat()}"
            lines.append(f"{bullet}{b(flag)}  {node.title}")
            lines.append(f"{'  ' if markdown else '    '}{node.project} · {node.id} · {node.status}")

    if found["quiet"]:
        lines.append(head(f"Going quiet (no update in {STALE_DAYS}+ days)"))
        for days, node in found["quiet"]:
            lines.append(f"{bullet}{b(f'{days}d')}  {node.title}")
            lines.append(f"{'  ' if markdown else '    '}{node.project} · {node.id} · {node.status}")

    if not any(found.values()):
        lines.append("\nNothing in this window. Either a quiet week, or nothing got logged —"
                     "\nand those two look identical here, which is worth noticing.")

    return "\n".join(lines) + "\n"


def send_mail(to: str, subject: str, body: str) -> bool:
    """Hand the digest to whatever local mailer exists. Never fatal.

    A digest that failed to send is still a digest you can read, so this reports
    and returns rather than exiting — the text has already gone to stdout.
    """
    for cmd in (["mail", "-s", subject, to], ["mailx", "-s", subject, to]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            done = subprocess.run(cmd, input=body, text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"cairn: {cmd[0]} failed: {exc}", file=sys.stderr)
            return False
        if done.returncode == 0:
            print(f"cairn: handed to {cmd[0]} for {to}", file=sys.stderr)
            print("       local mail is fire-and-forget — check that it arrived.", file=sys.stderr)
            return True
        print(f"cairn: {cmd[0]} exited {done.returncode}: {done.stderr.strip()}", file=sys.stderr)
        return False
    print("cairn: no local mailer (mail/mailx). Pipe the output instead.", file=sys.stderr)
    return False


def git_email() -> str:
    try:
        done = subprocess.run(["git", "config", "user.email"],
                              capture_output=True, text=True, timeout=10)
        return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def main() -> int:
    p = argparse.ArgumentParser(
        description="What changed in the graph, and what needs you.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("On demand", 1)[-1] if __doc__ else None,
    )
    p.add_argument("--days", type=int, default=7, help="window length; default 7")
    p.add_argument("--since", help="ISO start date; overrides --days")
    p.add_argument("--until", help="ISO end date; defaults to today")
    p.add_argument("--project", default="", help="restrict to one project key")
    p.add_argument("--stale", type=int, default=STALE_DAYS,
                   help=f"days without an update before a node is 'going quiet'; default {STALE_DAYS}")
    p.add_argument("--horizon", type=int, default=HORIZON_DAYS,
                   help=f"days ahead to report deadlines; default {HORIZON_DAYS}")
    p.add_argument("--format", choices=("text", "md"), default="text")
    p.add_argument("--mail", nargs="?", const="", metavar="ADDR",
                   help="also send it; with no address, your git user.email")
    args = p.parse_args()

    end = lib.as_date(args.until) or dt.date.today()
    if args.since:
        start = lib.as_date(args.since)
        if start is None:
            sys.exit(f"--since: not an ISO date: {args.since}")
    else:
        start = end - dt.timedelta(days=args.days)
    if start > end:
        sys.exit(f"empty window: {start} is after {end}")

    nodes, errors = lib.load_nodes()
    for err in errors:
        print(f"  {err}", file=sys.stderr)
    if args.project:
        keys = {n.project for n in nodes.values()}
        if args.project not in keys:
            sys.exit(f"no project '{args.project}'. known: {', '.join(sorted(keys))}")
        nodes = {k: n for k, n in nodes.items() if n.project == args.project}

    found = gather(nodes, start, end, args.stale, args.horizon)
    text = render(found, start, end, args.project, args.horizon, args.format == "md")
    print(text, end="")

    if args.mail is not None:
        to = args.mail or git_email()
        if not to:
            print("cairn: no address, and git user.email is unset", file=sys.stderr)
            return 1
        scope = f" [{args.project}]" if args.project else ""
        send_mail(to, f"Cairn digest{scope} — {start.isoformat()} to {end.isoformat()}", text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
