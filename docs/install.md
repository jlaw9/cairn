# Installing and using Cairn

For someone who has never used Cairn, on any machine. Ten minutes, four steps,
one dependency.

If a command fails at any point, run `make doctor` before debugging anything
else. It reports which of the four install steps is missing, and it runs without
a working Python — which matters, because the interpreter is the most common
thing to be wrong and none of the four failures names itself.

---

## 1. Clone it, outside every project repo

```sh
git clone <cairn-remote> ~/Cairn-graph
cd ~/Cairn-graph
```

`~/Cairn-graph` is a suggestion; anywhere works. **What matters is that it is not
nested inside a project repo.** One graph spans all your projects, and a clone
inside one project shows up as untracked junk in that project's `git status`,
makes the `repo` field ambiguous, and quietly implies the graph belongs to that
project. `make doctor` warns if this clone is nested.

## 2. Get a Python that can run it

Cairn needs **Python >= 3.7 with PyYAML**, and nothing else. Ever. That is the
whole dependency list, and it is deliberate: this has to run on a laptop and on a
cluster login node without a virtualenv dance.

```sh
make python          # prints the interpreter Cairn will use, or fails
```

If that prints a path, skip ahead. If it fails, install PyYAML whichever way
suits the machine — `pip install pyyaml` is not universally right, and on a
Homebrew Python it is refused outright under PEP 668:

```sh
conda install pyyaml                        # conda-managed python
python3 -m pip install --user pyyaml        # a python you control
python3 -m venv ~/.cairn/venv && ~/.cairn/venv/bin/pip install pyyaml
```

Or point Cairn at an interpreter that already has it — the escape hatch for
anything unusual:

```sh
export CAIRN_PYTHON=/path/to/python         # add to your shell profile
make python                                 # confirm
```

**Why Cairn discovers the interpreter rather than trusting `python3`:** on an HPC
login node, `python3` is routinely too old to *compile* these files while some
`python3.N` alongside it has no PyYAML — picking either blindly fails, in a way
whose error message points nowhere near the cause. `scripts/find_python.sh` is
one answer to "which Python?", shared by `make`, `bin/cairn` and the git hook, so
they cannot disagree.

This is also why **every command is `bin/cairn <thing>`, never
`scripts/<thing>.py`.** The dispatcher is `/bin/sh`, so it has no Python version
of its own to trip over. Running a script directly hands that choice to whatever
`#!/usr/bin/env python3` resolves to, and a shim inside the script cannot rescue
it: Python compiles the whole file before running a line, so the SyntaxError
arrives before any fallback could execute.

## 3. Set up this machine

```sh
make setup
```

Three things happen: the pre-commit validation hook is installed, the interpreter
is confirmed, and the slash commands are symlinked into `~/.claude/commands` so
they work **from any repo** rather than only from a session rooted here. That last
part is the point — `/log`'s whole job is to run inside a project repo and reach
into the graph.

Then export the path, and add it to your shell profile:

```sh
export CAIRN_PATH=$HOME/Cairn-graph
export PATH=$CAIRN_PATH/bin:$PATH           # optional: plain `cairn` anywhere
```

`CAIRN_PATH` is **not** optional — the slash commands and the skills use it to
find the graph. The `PATH` line is convenience only.

```sh
make doctor                                 # confirm all four steps took
```

**Do this on every machine you work on.** Laptop and cluster both.

## 4. Point your project repos at it

This is the step that is easy to skip and makes the difference between a graph
you maintain and a graph that maintains itself. An agent working in a project
repo has no idea Cairn exists unless that repo says so.

Add one line to each project's `CLAUDE.md`:

```markdown
Research activity is recorded in Cairn. To capture a note, resume a project, or
log a session, read the matching skill under `$CAIRN_PATH/skills/`.
```

That is the whole integration. Three skills become reachable —
`cairn-capture`, `cairn-resume`, `cairn-log` — and none of them costs anything
until it is used, because a path is an address and reading it is using it. See
[`skills/README.md`](../skills/README.md) for what each does and why it is
structured this way.

If `$CAIRN_PATH` is not set in the environment the agent runs in, use the
absolute path instead. Do not copy the skills into project repos: a copy drifts,
silently, and five projects with five slightly different ideas of what
`status: dead` means is worse than no convention at all.

---

## Using it: the daily shape

### Starting a session

```sh
cairn standup                     # every project, most-needs-you first
cairn standup --project <key>     # the resume packet for one project
```

`standup` is ordered by **what needs you**, not by when it happened — a project
touched this morning sinks to the bottom, a project quiet for six weeks rises.
That is what makes it the right view for deciding what to work on, and the wrong
view for "what happened last week", which is `digest`:

```sh
cairn digest                      # the last 7 days, chronologically
cairn digest --project <key> --days 1
cairn digest --format brief --mail
```

Both are queries over data that already exists. Neither invents bookkeeping,
which is why neither can go stale.

### During a session

Anything worth keeping, at the moment you have it:

```sh
cairn capture "the block-size distribution might be bimodal"
cairn capture --project mdegrade --title "q vs stack size" "<longer note>"
cairn capture --from-file ~/notes/meeting.org --title "meeting with Dave"
tail -40 slurm-12345.out | cairn capture --title "why the run died"
```

This writes to `inbox/`, which has **no schema and no validation**. It never
refuses, never prompts, never asks which project. That is not laziness in the
design; it is the design. Every previous attempt at a system like this died on
capture cost, so anything that puts a question between you and a written note is
a bug.

`--project` here is a *hint for triage*, not a validated key. Guess and move on.

### Ending a session

From inside the project repo, `/log` in Claude Code: it reads the git log, drafts
the node, asks only for the interpretation it cannot infer, and commits. Or by
hand:

```sh
cairn new_node experiment "<the claim>" --project <key> --parent <id> \
  --repo $(git remote get-url origin) --commit $(git rev-parse HEAD) \
  --host $(hostname -s) --note "<one line>"
```

Then, in the graph repo: `make build`, commit, push.

### Weekly-ish

```sh
/triage                           # turn inbox notes into nodes, or discard them
make build && open build/graph.html
```

Triage is the pass that pays for capture being free. Separating them is the whole
reason capture can stay cheap — and "this note went nowhere, delete it" is a
normal, correct outcome. Deleting an inbox file is fine; the never-delete rule is
about nodes.

---

## Two machines, or two people

Same problem, same answer: clone from the same remote on each, run `make setup`
on each, `git pull --rebase` at the start of a session, commit and push at the
end.

Neither machine ever needs to reach the other. Nodes reference code by `repo` +
`commit` and heavy outputs by `host:/path`, so a node written on a cluster is
fully readable from a laptop without resolving anything. Nothing heavy enters the
repo, so it stays text-only and small forever.

Conflicts are near-impossible by design: nodes are separate append-only files
that are never renamed. The only shared-file contention is generated output under
`build/` — never merge that by hand, regenerate it with `make build`. The one
genuine collision is two people creating the same id on the same day, which git
catches as a real conflict rather than losing one of them.

A collaborator is a collaborator on the git remote and nothing more. Don't shard
the graph per project: the cross-project edges are the hardest part to
reconstruct and the most valuable thing in it.

---

## Starting from an empty graph

An empty graph means nothing for months, and during those months a missing node
doesn't mean "not tried", it means "we hadn't started yet" — the exact ambiguity
that makes a graph untrustworthy. If you have work that already happened, read
[backfill.md](backfill.md) before anything else:

```sh
cairn mine_sessions --since <YYYY-MM-DD>          # what work exists?
cairn mine_sessions --project <key> --summaries
```

Backfill to the depth that answers *"did we already try this?"* — not
exhaustively. If the work went through Claude Code, the transcripts are a better
source than the repo, because they contain the dead ends.

## Command reference

```sh
cairn standup        what to pick up today; --project for a resume packet
cairn capture        append a note to inbox/ — no schema, never refuses
cairn digest         what changed, and what needs you
cairn new_node       create a node, or append a status change to one
cairn add_paper      DOI in, CrossRef-verified papers/ entry out
cairn validate       check every node against the schema
cairn build          regenerate build/graph.html and build/graph.md
cairn mine_sessions  survey Claude Code transcripts (read-only)
cairn sync_issues    mirror open task nodes to GitHub Issues (docs/github.md)
cairn doctor         check the install
```

`cairn <command> --help` for a command's own options. Slash commands: `/standup`,
`/capture`, `/log`, `/triage`, `/paper`.
