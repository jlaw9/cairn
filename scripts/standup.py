#!/usr/bin/env python3
"""Answer "what do I pick up today?" and "where was I on this project?"

`digest` answers *what changed*. That is the right question when you have been
present all week. It is the wrong question after two weeks away from a project,
when the thing you need is not a list of events but the frontier: what is still
open, what it was waiting on, and what the last note said to do next.

So this is not a second digest. Two differences carry the whole design:

1. **It is ordered by what needs you, not by when it happened.** A project whose
   live nodes have gone quiet ranks above a project that moved yesterday, because
   the quiet one is the one whose context you have lost. Chronology is what makes
   a digest readable and it is exactly wrong for deciding what to touch.

2. **It reads `## Next` out of the bodies.** That section is already where the
   next action gets written — /log's body convention asks for it — and until now
   nothing ever read it back. It is the cheapest possible resume: the sentence
   you wrote when you had the whole problem in your head.

It invents no fields and no bookkeeping, for the same reason `digest` doesn't:
anything that needs maintaining stops being true, and a stale planning view is
worse than none because you act on it.

    cairn standup                      # every project, most-needs-you first
    cairn standup --project mplastic   # the resume packet for one project
    cairn standup --quiet-after 21     # what counts as "lost context"
    cairn standup --format md
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib

#: Statuses that assert an open thread. Same set `digest` calls ACTIVE, and for
#: the same reason: `parked` means "paused deliberately" and an `open` direction
#: is a container meant to sit, so neither is a loose end. The difference is that
#: `digest` uses this to decide what to *nag* about and standup uses it to decide
#: what is still live enough to resume.
LIVE = {"running", "doing", "submitted", "planned"}

#: Days of silence after which you have probably lost the context. Shorter than
#: digest's STALE_DAYS of 14 would be wrong in the other direction: this view is
#: for deciding what to work on, and a node touched last week is not a problem.
#: Three weeks is roughly where "I remember where I was" stops being true.
QUIET_AFTER = 21

#: Sections whose text is the next action. `## Next` is the convention /log
#: writes; the others show up in backfilled and hand-written nodes, and reading
#: three headings instead of one costs nothing and misses less.
NEXT_HEADINGS = ("next", "next steps", "todo", "to do", "open questions")

SECTION_RE = re.compile(r"^\s{0,3}#{2,4}\s*(.+?)\s*$", re.MULTILINE)


def next_action(node: lib.Node) -> str:
    """The `## Next` text from a node body, flattened to one line.

    Flattened deliberately. The full section belongs in the panel of the graph;
    what this view needs is the one line that tells you whether to open it, and
    a multi-paragraph plan pasted into a list turns the list into a document
    nobody scans.
    """
    matches = list(SECTION_RE.finditer(node.body))
    for index, match in enumerate(matches):
        if match.group(1).strip().lower().rstrip(":") not in NEXT_HEADINGS:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(node.body)
        text = node.body[match.end():end]
        # Bullets and prose both collapse to one stream; strip list markers so
        # the result reads as a sentence rather than as broken markdown.
        parts = [re.sub(r"^\s*[-*+]\s*|^\s*\d+[.)]\s*", "", line).strip()
                 for line in text.strip().splitlines()]
        joined = " ".join(part for part in parts if part)
        if joined:
            return joined
    return ""


def truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)].rstrip() + "…"


def wrapped(label: str, text: str, indent: str, width: int,
            max_lines: int = 4) -> list[str]:
    """`label: text` wrapped to the terminal, capped at max_lines.

    The survey truncates these to one line, which is right there — it is a list
    you scan. The packet is a briefing you read, so a `## Next` section that is
    genuinely four sentences long should show all four. But it must still be
    capped: one node with a twenty-line plan otherwise pushes every other live
    thread off the screen, and then the ordering work above buys nothing.
    """
    # Continuation lines carry two extra spaces, so they are the binding
    # constraint — wrap to the narrower of the two or they overflow the terminal
    # and wrap again in the wrong place, which is worse than not wrapping at all.
    inner = max(width - len(indent) - 2, 20)
    body = textwrap.wrap(f"{label}{text}", width=inner)
    if len(body) > max_lines:
        body = body[:max_lines]
        body[-1] = truncate(body[-1] + " …", inner)
    return [f"{indent}{line}" if i == 0 else f"{indent}  {line}"
            for i, line in enumerate(body)]


def last_note(node: lib.Node) -> str:
    """The most recent history note — why the node is in the state it is in.

    Preferred over the body when both exist, because it is the most recent thing
    written and it is the one field guaranteed to be about *this* status.
    """
    for entry in reversed(node.history):
        note = str(entry.get("note", "") or "").strip()
        if note:
            return note
    return ""


def age(node: lib.Node, today: dt.date) -> int:
    """Days since anything was written about this node. -1 if undatable."""
    last = node.updated or node.created
    return (today - last).days if last else -1


def survey(nodes: dict[str, lib.Node], today: dt.date, quiet_after: int,
           horizon: int) -> list[dict]:
    """Per-project frontier, ordered by how much it needs attention.

    The ordering is the opinion in this file, so it is worth stating plainly.
    A project is ranked by the worst thing true of it, in this order: an overdue
    deadline, then a live thread that has gone quiet, then a live thread at all,
    then nothing live. Within a rank, the longest silence first.

    The deliberate consequence: a project you touched this morning sinks to the
    bottom. That is correct for this view — you have not lost its context, so it
    does not need a briefing. It is also why this must never replace `digest`,
    which is the view where recency is the point.
    """
    by_project: dict[str, list[lib.Node]] = {}
    for node in nodes.values():
        by_project.setdefault(node.project, []).append(node)

    out = []
    for project, members in by_project.items():
        live = [n for n in members if n.status in LIVE and not n.is_terminal]
        live.sort(key=lambda n: -age(n, today))

        deadlines = []
        for node in members:
            if node.is_terminal or node.type not in ("task", "milestone"):
                continue
            when = lib.as_date(node.meta.get("due") or node.meta.get("date"))
            if when is not None and when <= today + dt.timedelta(days=horizon):
                deadlines.append((when, node))
        deadlines.sort(key=lambda pair: pair[0])

        # Directions are the open questions a project is organised around, and an
        # `open` one is not a loose end — but it *is* the context you need to read
        # a resume packet, so it belongs in the briefing without counting as work.
        threads = [n for n in members if n.type == "direction" and n.status == "open"]

        touched = max((age(n, today) for n in members if age(n, today) >= 0),
                      default=-1)
        quiet = min((age(n, today) for n in live if age(n, today) >= 0), default=-1)
        overdue = any(when < today for when, _ in deadlines)

        if overdue:
            rank = 0
        elif live and quiet >= quiet_after:
            rank = 1
        elif live:
            rank = 2
        else:
            rank = 3

        out.append({
            "project": project, "live": live, "deadlines": deadlines,
            "threads": threads, "rank": rank, "quiet": quiet,
            "since": touched, "total": len(members),
        })

    out.sort(key=lambda row: (row["rank"], -row["quiet"], row["project"]))
    return out


def inbox_count(root: Path | None = None) -> int:
    folder = (root or lib.REPO_ROOT) / "inbox"
    return len(list(folder.glob("*.md"))) if folder.is_dir() else 0


def render(rows: list[dict], today: dt.date, quiet_after: int, horizon: int,
           markdown: bool, width: int, pending: int) -> str:
    b = (lambda s: f"**{s}**") if markdown else (lambda s: s)
    bullet = "- " if markdown else "  "
    indent = "  " if markdown else "    "

    lines = [f"# Cairn standup — {today.isoformat()}" if markdown
             else f"Cairn standup — {today.isoformat()}"]

    live_total = sum(len(row["live"]) for row in rows)
    stalled = [row for row in rows if row["rank"] == 1]
    lines.append(f"{live_total} live thread(s) across {len(rows)} project(s); "
                 f"{len(stalled)} project(s) quiet for {quiet_after}+ days")
    if pending:
        lines.append(f"{pending} untriaged inbox item(s) — `/triage` or read inbox/")

    for row in rows:
        if not row["live"] and not row["deadlines"]:
            continue                       # nothing open; the map is the right view

        flag = {0: "OVERDUE", 1: f"quiet {row['quiet']}d", 2: "live"}.get(row["rank"], "")
        header = f"{row['project']}  ({flag})" if flag else row["project"]
        lines.append(f"\n### {header}\n" if markdown
                     else f"\n{header}\n{'-' * min(len(header), width)}")

        for when, node in row["deadlines"]:
            days = (when - today).days
            label = f"OVERDUE {-days}d" if days < 0 else f"due in {days}d"
            lines.append(f"{bullet}{b(label)}  {node.title}")
            lines.append(f"{indent}{node.id} · {node.status}")

        for node in row["live"]:
            days = age(node, today)
            lines.append(f"{bullet}{b(f'{node.status} {days}d')}  {node.title}")
            lines.append(f"{indent}{node.id}")
            note = last_note(node)
            if note:
                lines.append(f'{indent}was: "{truncate(note, width - len(indent) - 6)}"')
            action = next_action(node)
            if action:
                lines.append(f"{indent}next: {truncate(action, width - len(indent) - 6)}")

    if not any(row["live"] or row["deadlines"] for row in rows):
        lines.append("\nNothing live anywhere. Either genuinely between things, or"
                     "\nthe last few sessions never got logged.")

    return "\n".join(lines) + "\n"


def render_packet(row: dict, nodes: dict[str, lib.Node], today: dt.date,
                  markdown: bool, width: int) -> str:
    """The resume packet: one project, enough to start working again.

    Deeper than the survey on purpose, and the extra depth is all *lineage* —
    what each live thread grew out of, and what the project already settled.
    Rereading a claim you refuted in June is how the same dead end gets tried
    twice, and that is the failure this whole repo exists to prevent.
    """
    b = (lambda s: f"**{s}**") if markdown else (lambda s: s)
    bullet = "- " if markdown else "  "
    indent = "  " if markdown else "    "
    project = row["project"]

    def head(text: str) -> str:
        return f"\n### {text}\n" if markdown else f"\n{text}\n{'-' * min(len(text), width)}"

    lines = [f"# Resume: {project}" if markdown else f"Resume: {project}",
             f"{row['total']} node(s); last touched {row['since']}d ago"]

    if row["threads"]:
        lines.append(head("Open questions"))
        for node in row["threads"]:
            lines.append(f"{bullet}{b(node.title)}")
            lines.append(f"{indent}{node.id}")

    if row["deadlines"]:
        lines.append(head("Deadlines"))
        for when, node in row["deadlines"]:
            days = (when - today).days
            label = f"OVERDUE {-days}d" if days < 0 else f"due in {days}d"
            lines.append(f"{bullet}{b(label)}  {node.title}  ({when.isoformat()})")
            lines.append(f"{indent}{node.id} · {node.status}")

    if row["live"]:
        lines.append(head("Live threads"))
        for node in row["live"]:
            lines.append(f"{bullet}{b(f'{node.status} · {age(node, today)}d')}  {node.title}")
            lines.append(f"{indent}{node.id}")
            for parent in node.parents:
                if parent in nodes:
                    lines.append(f"{indent}from: {nodes[parent].title} ({nodes[parent].status})")
            note = last_note(node)
            if note:
                lines += wrapped("was: ", f'"{note}"', indent, width)
            action = next_action(node)
            if action:
                lines += wrapped("next: ", action, indent, width)
            if node.meta.get("commit"):
                lines.append(f"{indent}at: {node.meta.get('repo', '?')} @ {node.meta['commit']}")
            for artifact in node.meta.get("artifacts") or []:
                lines.append(f"{indent}out: {artifact}")

    # What is already settled, most recent first. Capped, because the point is
    # "don't retry these", and a reader who needs all of them should open the map.
    settled = sorted(
        (n for n in nodes.values() if n.project == project and n.is_terminal),
        key=lambda n: (n.updated or n.created or dt.date.min), reverse=True)
    if settled:
        lines.append(head("Already settled (most recent first)"))
        for node in settled[:12]:
            lines.append(f"{bullet}{b(node.status)}  {node.title}")
            note = last_note(node)
            if note:
                lines.append(f'{indent}"{truncate(note, width - len(indent) - 2)}"')
        if len(settled) > 12:
            lines.append(f"{indent}… and {len(settled) - 12} more; see the map")

    if not (row["live"] or row["deadlines"] or row["threads"]):
        lines.append("\nNothing open in this project. Every thread is settled or parked.")

    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(
        description="What to pick up today, and where you left off.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("    cairn standup", 1)[-1] if __doc__ else None,
    )
    p.add_argument("--project", default="",
                   help="the resume packet for one project, instead of the survey")
    p.add_argument("--quiet-after", type=int, default=QUIET_AFTER, metavar="DAYS",
                   help=f"silence after which context is lost; default {QUIET_AFTER}")
    p.add_argument("--horizon", type=int, default=14, metavar="DAYS",
                   help="days ahead to report deadlines; default 14")
    p.add_argument("--format", choices=("text", "md"), default="text")
    args = p.parse_args()

    today = dt.date.today()
    nodes, errors = lib.load_nodes()
    for err in errors:
        print(f"  {err}", file=sys.stderr)
    if not nodes:
        print("cairn: no nodes yet — see docs/backfill.md", file=sys.stderr)
        return 1

    width = min(shutil.get_terminal_size((88, 24)).columns, 88)
    rows = survey(nodes, today, args.quiet_after, args.horizon)

    if args.project:
        match = next((row for row in rows if row["project"] == args.project), None)
        if match is None:
            keys = ", ".join(sorted(row["project"] for row in rows))
            sys.exit(f"no project '{args.project}'. known: {keys}")
        print(render_packet(match, nodes, today, args.format == "md", width), end="")
    else:
        print(render(rows, today, args.quiet_after, args.horizon,
                     args.format == "md", width, inbox_count()), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
