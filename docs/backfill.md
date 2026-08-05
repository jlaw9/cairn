# Adopting Cairn into work that already happened

Starting empty is the failure mode this repo exists to avoid. An empty graph
means nothing for months, and during those months a missing node doesn't mean
"not tried" — it means "we hadn't started recording yet", which is exactly the
ambiguity that makes a graph untrustworthy.

So backfill first. Not exhaustively — to the depth that answers **"did we
already try this?"** You don't need every experiment. You need the ones someone
might otherwise repeat, and the dead ends that shaped what you do now.

That scoping rule is what makes this finishable. The 2026-08 backfill covered
five weeks and eight projects in 55 nodes; the same period generated 103 status
documents and ~109,000 words. Aim for the index, not the archive.

---

## Case A — the work went through Claude Code

The transcripts under `~/.claude/projects/<slugified-cwd>/*.jsonl` are the best
source available, and better than the repo for the thing that matters most:
**they contain the dead ends.** A commit log shows what was kept.

### 1. Survey

```sh
scripts/mine_sessions.py --since 2026-06-01
```

One line per session: dates, assistant turns, directory, and the session's
auto-generated title. Turn count is a decent proxy for weight — a 2,000-turn
session is a project, a 20-turn one is an errand.

Group the directories into projects. One project usually spans several session
directories (a repo root and its subdirectories each get their own).

### 2. Read the dense parts

```sh
scripts/mine_sessions.py --project <slug> --summaries
scripts/mine_sessions.py --project <slug> --detail
```

`--summaries` prints each session's last compaction summary. These are the
highest-value text in the whole corpus: a structured recap of intent, technical
concepts, files changed, **errors and fixes**, and problem-solving. Section 4
("Errors and fixes") and section 5 ("Problem solving") are where the dead ends
live.

`--detail` prints the actual prompts, which give you intent in the researcher's
own words — the claim as they framed it, before they knew the answer.

### 3. Cross-check against the repo

Transcripts tell you what was attempted; the repo tells you what survived and
gives you citable provenance.

- `git log --format='%h|%ad|%s' --date=short` for dated SHAs
- the project's own reports — `PROJECT_STATUS`, `RESULTS`, `HANDOFF`,
  `SELECTIVITY_REPORT`. These are usually already a retrospective survey; mine
  them for verdicts and numbers
- `git remote get-url origin` for the `repo` field

Prefer a number from a committed report over the same number recalled in a
transcript. Transcripts contain in-progress figures that were later corrected.

### 4. Draft, don't publish

Generate nodes with `lib.Node` + `set_status()` (never hand-assembled YAML) so
`status`/`history`/`updated` can't drift. Then:

```sh
make validate && make build
```

**Show every node before committing.** This is not optional and not a
formality. An auto-populated graph nobody reviewed is precisely the failure
this project exists to avoid — the record has to be trusted, and trust comes
from a human having read it.

### 5. What to leave out

- **`refs:`.** Transcripts cite papers constantly, but a DOI recalled rather
  than resolved is worse than no DOI: it looks like a citation. Populate
  `papers/` properly with `/paper`, later.
- **Dates you're guessing at.** If the work predates the transcripts, say so
  when you present the node rather than inventing precision.
- **Sessions that were errands.** Environment fixes, package installs, "where
  is this file" — these are not research decisions.

---

## Case B — the work never went through an LLM

No transcripts. The sources are the git history, the files on disk, the
manuscripts, and the researcher's memory. The method changes from *mining* to
*interviewing*, and one caveat dominates:

> **A retrospective backfill is biased toward what worked.**

Git preserves what was committed. Abandoned approaches often were never
committed at all, and the ones that were are the first thing forgotten. So the
default output of this process is a tidy success story — the exact opposite of
what makes the graph valuable.

Counter it deliberately.

### 1. Walk the git log together

```sh
git log --format='%h|%ad|%s' --date=short --reverse
```

Go era by era, not commit by commit. For each cluster ask two questions:

1. **What were you trying to show here?** → the `## Claim`
2. **Did it work, and how did you know?** → the `## Result`

Everything else — dates, SHAs, files — read out of the log yourself.

### 2. Ask the dead-end question explicitly, several times

It will not come up on its own. Ask directly:

- What did you try that you stopped doing?
- What did you expect to work that didn't?
- What would you tell someone joining not to bother re-running?
- Is there anything a reviewer or collaborator talked you out of?

Every answer is a node with `status: dead` and a `## Result` explaining why.
These are the highest-value nodes in the graph and the only ones that cannot be
reconstructed from artifacts later.

### 3. Anchor to what exists

Bench and instrument work has provenance too, just not SHAs: notebook pages,
instrument runs, sample IDs, dated result files. Record them in the body if
they don't fit a field. A node that says "see notebook 4, pp. 88–92" is
enormously more useful than no node.

### 4. Expect a smaller graph, and say so

A backfill of unrecorded work will be thinner and more success-weighted than a
transcript-mined one. That's fine — but make it visible, so the coverage gap
isn't mistaken for an absence of attempts. A root `direction` node whose body
says "backfilled 2026-08 from git history and conversation; dead ends before
2026 are largely unrecorded" is worth writing, and it tells a future reader
exactly how far to trust the silence.

---

## Case C — the work didn't happen at a computer

Cairn's *model* is domain-neutral: claims, results, dead ends, directions,
deadlines. None of that is computational. `repo`, `commit`, `host` and
`artifacts` are all optional on an `experiment`, so a bench experiment node
validates today with none of them.

Cairn's *interface* is not neutral: git, a CLI, markdown, YAML.

The resolution is that the interface was never meant to be the interface. The
design assumes an agent writes the record as a side effect of the work, and the
human reads `graph.html` and answers one question — what the result means. A
collaborator who works with Claude but not with git can use this; a
collaborator who wants to edit YAML by hand should not have to.

Two things to know before recommending it to a wet-lab colleague:

- **The first thing that will break is `artifacts:`.** It requires
  `host:/absolute/path`, which fits an HPC output and not an ELN entry, a
  Benchling URL, or a freezer box. Don't pre-emptively widen it — Cairn adds a
  field when a real node needs one, not in anticipation. But know that's the
  break point.
- **`commit`/`repo` being empty is fine**, and a node with neither is not a
  second-class node.

### Work done in Claude Science rather than Claude Code

There are no local transcripts and no repo, so neither Case A nor Case B
applies cleanly. Use `inbox/`:

```
inbox/2026-08-05-1430.md
```

Paste the result, the reasoning, whatever you have. No schema, no validation —
that is what makes it safe to write to without thinking. `/triage` turns it into
nodes later, with review.

This is the pressure valve for every source Cairn doesn't integrate with, and
using it is always better than not capturing. **Capture wins.**
