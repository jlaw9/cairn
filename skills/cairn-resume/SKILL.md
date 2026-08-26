---
name: cairn-resume
description: Read the state of a research project out of Cairn before starting work on it — what is still open, what it was waiting on, what was already tried and refuted, and what the last note said to do next. Use at the start of a session in a project repo, when returning to a project after time away, when asked "where was I" or "what should I work on", or before proposing an experiment that may already have been run.
---

# Resume a project from Cairn

Cairn holds the research history across all projects: experiments, dead ends,
open directions, deadlines. Before doing work in a project, read its frontier.
This costs one command and prevents the two expensive mistakes: re-running a
refuted experiment, and asking the user to reconstruct context the graph already
has.

## The resume packet

```sh
$CAIRN_PATH/bin/cairn standup --project <key>
```

If `$CAIRN_PATH` is unset, use the absolute path to the Cairn clone — on a shared
filesystem, `/kfs2/projects/bpms/jlaw/tools/Cairn-graph`. If you don't know the
project key, run `$CAIRN_PATH/bin/cairn standup` with no arguments; it lists
every project, ordered by what most needs attention.

Four sections come back, and each answers a different question:

- **Open questions** — the `direction` nodes. What the project is *for*. Read
  these first; they frame everything else.
- **Deadlines** — tasks and milestones inside a fortnight, overdue first.
- **Live threads** — anything `running`, `planned`, `doing` or `submitted`, with
  its lineage, its last history note, its `## Next` line, and the repo and commit
  it was last at. This is where you were.
- **Already settled** — terminal nodes, most recent first, each with the note
  saying why. **This is the section that matters most and reads as the least
  urgent.** `dead` here means the claim was refuted and the reason is attached.

## Then do this

1. **Check your intended work against "already settled" before proposing it.** If
   a node already refuted the idea, say so and cite the node id rather than
   running it again. This is the single highest-value thing this skill does; a
   dead end in the graph exists so it is not repeated.
2. **Prefer resuming a live thread over opening a new one.** A session that
   continues yesterday's experiment is a status change on that node, not a new
   node. The `next:` line is usually the literal instruction.
3. **Trust `was:` over your own reconstruction.** The last history note was
   written when the whole problem was in someone's head.
4. **Read the node itself when the summary isn't enough:**
   `$CAIRN_PATH/nodes/<id>.md`. The full body has `## Claim` / `## What I did` /
   `## Result`. A `[[node-id]]` in a body is a cross-reference — follow it,
   especially for cross-project dependencies, which live in bodies rather than in
   `parents`.

## Across the whole graph

```sh
$CAIRN_PATH/bin/cairn standup          # every project, most-needs-you first
$CAIRN_PATH/bin/cairn digest --days 7  # what changed recently, chronologically
```

`standup` and `digest` answer different questions and are not substitutes.
`standup` ranks by what needs attention, so a project touched this morning sinks
to the bottom and one quiet for six weeks rises — right for deciding what to
work on. `digest` is chronological — right for "what happened while I was away."
When someone asks what to work on, use `standup`.

A project flagged `quiet Nd` has live threads nobody has touched in N days. That
is not a failure to report as one: it is the normal state of parallel projects,
and it is the specific thing this view exists to surface. Say which threads and
what they were waiting on.

## Notes somebody left

The resume packet has a **"Notes left, not yet answered"** section when one
applies. Read it first and treat it as the highest-priority item in the packet:
it is a human explicitly asking for something, where everything else in the view
is inferred from status and dates.

A note is a dated line in the node body under `## Notes`. It is reported as
unanswered while its date is at or after the node's last status change, so if you
act on one, the status change that records the work also clears the note — you
never have to mark it done.

## How much to trust a gap

`$CAIRN_PATH/build/report.md` carries a coverage table: per project, how many
nodes, how many settled, how many dead ends, and **what share were committed
within a week of the work they describe**.

That last column is the one to check before saying "we never tried that." A
project at 0% is a reconstruction rather than a record, and a reconstruction is
biased toward what worked — so a gap there means the graph doesn't know, not that
nobody tried. Say which of the two you mean; they are very different answers.

## Do not

- **Do not write anything.** This skill is read-only. Recording a result is
  `cairn-log`; saving a stray thought is `cairn-capture`.
- **Do not treat a missing node as "not tried"** unless the project is
  well-covered. If a project has very few nodes, the graph does not yet know
  its history — say that rather than concluding the work is new.
- **Do not summarise the whole graph unasked.** Report what bears on the task at
  hand, with node ids so the user can open them.
