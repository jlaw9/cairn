---
description: What changed in the research graph, and what needs a decision
---

Report what has happened in Cairn over a window, and turn it into something
worth reading.

`$ARGUMENTS` may be a number of days, a project key, a date (`since 2026-08-01`),
or a phrase like "since Monday" / "this week" / "yesterday". With no arguments,
use the last 7 days.

The graph is at `$CAIRN_PATH`. If that isn't set, ask for the path rather than
guessing, and mention `make install-commands` in the Cairn clone, which prints
the export line for a shell profile.

## 1. Read

```sh
$CAIRN_PATH/bin/cairn digest                          # last 7 days
$CAIRN_PATH/bin/cairn digest --days 1                 # yesterday
$CAIRN_PATH/bin/cairn digest --since 2026-08-01
$CAIRN_PATH/bin/cairn digest --project polyid --days 14
```

Five sections come back: notes people left on nodes, what moved (with the history
note), what was opened, deadlines inside a fortnight, and anything claiming to be
*running* that nobody has touched in two weeks.

**`digest` is chronological; `standup` ranks by need.** They answer different
questions and neither substitutes for the other. If the real question is "where
do I pick up?" — which it is after two weeks away — use `/standup` instead. This
command is for "what happened", which is the right question when you were present
and need the list, and the right question before a meeting.

## 2. Report it as prose, not as a re-print

The command's output is already well-formed text. Pasting it back adds nothing.
What you add is the reading of it:

- **Lead with the result, not the count.** "The wD-MPNN null held at 15 runs, so
  the extrapolation deficit is real" beats "3 status changes this week."
- **Group by story, not by node.** Three nodes in one project that are one
  argument should be described as one argument.
- **A `dead` node is the headline, not a footnote.** A refuted claim is the most
  valuable thing in a window, because it is what stops the work being redone.
- **Name what a `## Next` line says to do**, where one exists — that is the
  sentence written while the whole problem was in someone's head.
- **Notes left on nodes are somebody asking for something.** If the window
  contains one, say who left it and whether it has been answered.
- Say plainly when a window is empty, and say the ambiguity out loud: nothing
  happened and nothing got logged look identical here.

## 3. Offer the two things this leads to

Only when they apply, and only as one line each:

- If something is unpushed or a draft is unreviewed, say so —
  `$CAIRN_PATH/bin/cairn sync --check` is the check, `--push` is the fix.
- If a deadline is inside a week, name the node and the date.

## Mailing it

```sh
$CAIRN_PATH/bin/cairn digest --format brief --mail
```

`--format brief` is one line per item, which is the right size for a mail client;
the full form is written for a terminal and too long for mail, where it competes
with the map and loses. A mailed digest's job is to say what deserves a click.

## Notes

- This is read-only. It invents no bookkeeping — `status` is an event log, so the
  whole view is a query over `history` and the node bodies.
- Don't nag about `parked`, and don't treat an `open` direction as stalled. Both
  are deliberate states, and the command already filters them out of the "going
  quiet" section for that reason.
- If the conversation produces a decision worth keeping, that's `/log`, or
  `$CAIRN_PATH/bin/cairn capture` for a loose thought.
