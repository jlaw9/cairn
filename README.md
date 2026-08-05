# Cairn

A persistent, git-backed DAG of research activity across projects —
experiments, dead ends, open threads, conference ideas, tasks with deadlines,
papers, milestones — maintained by Claude Code as a side effect of doing the
work, and rendered as a clickable map.

The point isn't visualization. The point is that six months from now, *"did we
already try this, and what happened?"* has an answer, and *"what should I do
next?"* has a defensible one.

## Why this can exist now

Every prior attempt at this died on the same rock: **capture cost**. Renku does
compute provenance but has no concept of a hypothesis or a dead end. W&B, MLflow
and DVC track runs and artifacts, not ideas. The HCI work — Kery's Variolite and
Verdant, Burrito, Hindsight — attacked exactly this and needed a discipline
nobody sustains, because a graph at 60% coverage is worse than none: you can't
trust a missing node to mean "not tried."

The agent doing the work can now write the record. Every design decision here
serves that one fact, so **when expressiveness and capture reliability
conflict, capture wins.**

## Install — once per machine

```sh
git clone <your-cairn-remote> ~/Cairn-graph && cd ~/Cairn-graph
make setup                                  # hook + slash commands + checks
export CAIRN_PATH=$HOME/Cairn-graph         # add to your shell profile
export PATH=$CAIRN_PATH/bin:$PATH           # optional: plain `cairn` anywhere
make doctor                                 # confirm all four steps took
```

The `PATH` line is convenience only. `bin/cairn` works by path from anywhere, and
the slash commands call it as `$CAIRN_PATH/bin/cairn`, so nothing depends on it.

**Clone it outside every project repo.** One graph spans all projects (design
decision 1), and a clone nested inside a project shows up as an untracked
directory in that project's `git status`, makes `/log`'s `repo` field ambiguous,
and quietly implies the graph belongs to one project. `make doctor` warns if
this clone is nested.

`make setup` installs the pre-commit validation hook and symlinks `/log` and
`/paper` into `~/.claude/commands` so they work **from any repo**, not only
from this one. That matters: `/log`'s whole job is to run inside a project repo
and reach into the graph, and slash commands otherwise resolve only from the
session's own directory. Do this on every machine you work on — laptop and
cluster both.

**`make doctor` is the thing to run when something is off.** It reports, without
needing a working Python, which of the four install steps happened: interpreter,
hook, slash commands, `CAIRN_PATH`. Each of those fails differently and none of
the failures names which one is missing, which is how a first install goes
wrong.

### The one dependency

Cairn needs **Python >= 3.7 with PyYAML** and nothing else. `scripts/find_python.sh`
finds a suitable interpreter rather than assuming `python3` is one — on Kestrel
the default `python3` is 3.6.8 *with* PyYAML while `python3.9` has none, and
picking either blindly fails.

**This is why every command below is `bin/cairn <something>` rather than
`scripts/<something>.py`.** The dispatcher is a `/bin/sh` script, so it has no
Python version of its own to trip over: it asks `find_python.sh` and execs the
answer, which is the same interpreter `make` and the pre-commit hook use. Running
a script directly instead hands that choice to whatever `#!/usr/bin/env python3`
happens to resolve to, and a shim *inside* the script cannot correct it — Python
compiles the whole file before running a line of it, so on a 3.6 interpreter the
SyntaxError arrives before any shim could execute.

If nothing on the machine has PyYAML, install it whichever way suits that
machine — `pip install pyyaml` is not always the right answer, and on a
Homebrew python it is refused outright under PEP 668:

```sh
conda install pyyaml                        # conda-managed python
python3 -m pip install --user pyyaml        # a python you control
python3 -m venv ~/.cairn/venv && ~/.cairn/venv/bin/pip install pyyaml
```

Or point Cairn at an interpreter that already has it, which is also the escape
hatch for anything exotic:

```sh
export CAIRN_PYTHON=/path/to/python
make python                                 # prints what Cairn will use
```

## Then pick your path

### A. You have work that already happened → **backfill first**

Read **[docs/backfill.md](docs/backfill.md)**. Do not skip this because it
sounds like homework.

An empty graph means nothing for months, and during those months a missing node
doesn't mean "not tried", it means "we hadn't started yet" — the exact ambiguity
that makes a graph untrustworthy. Backfilling is what makes it useful on day
one.

```sh
bin/cairn mine_sessions --since 2026-01-01        # what work exists?
bin/cairn mine_sessions --project <slug> --summaries
```

If the work went through Claude Code, the transcripts are the best source and
better than the repo for the part that matters: they contain the dead ends.
If it didn't, `docs/backfill.md` covers the interview-based version, including
why it will be biased toward what worked and what to ask to counter that.

Backfill to the depth that answers *"did we already try this?"* — not
exhaustively.

### B. You are starting something new → **open the node before you run it**

```sh
bin/cairn new_node direction "Does X predict Y?" --project <key> --new-project
```

`--new-project` is needed only the first time a project key is used. After that
an unrecognised key is refused, because `project:` is the one field whose typo
validates cleanly — `photpoly` for `photopoly` passes every check and silently
splits one project into two lanes.

Then, before the first job goes to the queue, an `experiment` whose `## Claim`
says what you expect **and what result would prove it wrong**:

```sh
bin/cairn new_node experiment "X predicts Y from Z alone" \
  --project <key> --parent <direction-id> --status planned \
  --note "pre-registered, not yet queued"

# then when it actually starts
bin/cairn new_node --update <id> --status running \
  --repo $(git remote get-url origin) --commit $(git rev-parse HEAD) \
  --host $(hostname -s)
```

A claim written before the result is a pre-registration; written after, it's a
story. That difference is what makes a dead end publishable.

Use `planned` for the pre-registration and `running` once it is queued. They are
different facts and the replay slider shows both: `planned` on a date nothing was
running would otherwise be a small lie in the history that `running` is grepped
for. An experiment created with no `--status` is still `running`, so writing up
work after the fact is unchanged.

At the end of a session, `/log` from inside the project repo does the rest: it
reads the git log, drafts the node, asks only for the interpretation it can't
infer, and commits.

```sh
make build && open build/graph.html
```

A companion repo, **research-kit**, scaffolds a new project with a `CLAUDE.md`
carrying these conventions, a `data/{raw,curated}` split and a stock DVC config.

### C. You are starting from a literature review

Most new projects start here, before there is a repo or a run. **A literature
finding is an `experiment`** — it has a claim, a method and a result, and the
corpus is the instrument. `repo`, `commit`, `host` and `artifacts` are all
optional, so nothing about the node type assumes code.

The point is to write the finding as the claim it settles, not as a summary of
what you read:

```sh
bin/cairn new_node experiment 'Can a reported "final Tg" be fitted as Tgp?' \
  --project photopoly --parent <direction-id> --status dead \
  --ref 10.1021/ma101296j \
  --note "vitrification-limited; the bias is formulation-dependent"
```

`status: dead` because the claim was refuted — by the literature rather than by a
job that failed, which makes no difference to what it means downstream. That node
is worth more than a summary would be: six months on, *"can we just fit published
final Tg values?"* has an answer with a reason attached, and the next person to
have the idea finds it instead of rediscovering it. See
[docs/examples/literature.md](docs/examples/literature.md).

Three habits make this work:

- **One claim per node.** A review that touches eight things is eight nodes or
  one `direction` with eight open questions — not one node called "lit review",
  which is unsearchable by the question you'll actually ask.
- **`--ref` the DOI and register the paper**, so the evidence is resolvable
  rather than remembered: `bin/cairn add_paper <doi>` (or `/paper`). A DOI
  recalled rather than resolved is worse than no DOI.
- **A constraint that shapes later work belongs in the graph, not only in the
  synthesis document.** The document is read once; the node is what the graph
  shows you when you touch that part of the problem again.

Use the `litsearch-workflow` or `property-matrix-litsearch` skills to do the
retrieval — don't reimplement it. What lands here is the conclusion and the
verified DOIs, not the corpus.

### D. Your work isn't computational

The *model* here is domain-neutral — claims, results, dead ends, directions,
deadlines. `repo`, `commit`, `host` and `artifacts` are all optional on an
experiment, so a bench experiment node validates today with none of them, and
a node with no SHA is not a second-class node.

The *interface* is not neutral, but it was never meant to be the interface. The
design assumes an agent writes the record while you work, and you read
`graph.html` and answer one question: what the result means. See
[docs/backfill.md](docs/backfill.md) §C, including the one field that will
break first.

Work that happened somewhere Cairn can't see — a web session, a conversation, a
whiteboard — goes in `inbox/` as unstructured text and gets triaged later.
Capture always beats filing.

## What's here

```
nodes/       the graph — one file per node, append-only, never deleted
papers/      one page per cited paper, keyed by DOI
meetings/    raw meeting notes
inbox/       unstructured capture awaiting triage
assets/      small figures only
build/       generated: graph.html (self-contained) and graph.md (Mermaid)
scripts/     lib.py, validate.py, build_graph.py, new_node.py,
             add_paper.py, mine_sessions.py, digest.py
docs/        schema.md, backfill.md, worked examples
```

`make doctor` · `make validate` · `make build` · `make digest` · `make test`

In a node body, `[[2026-07-01-polyid-network-ablation]]` refers to another node
and renders as a link to it, labelled with that node's title. `make validate`
warns if the target doesn't exist.

## What changed, and what needs you

```sh
cairn digest                          # the last 7 days
cairn digest --project photopoly --days 1     # right before that meeting
cairn digest --format md --mail       # to your own git email
```

Four sections: what moved (status changes, with the history note), what was
opened, deadlines inside a fortnight, and anything claiming to be *running* that
nobody has touched in two weeks.

It invents no bookkeeping — `status` is an event log, so this is a query over
`history` rather than a second thing to maintain. That's the payoff for design
decision 5.

The filters that keep entries **out** are the substance. `parked` means "paused,
will resume" and an `open` direction is a container meant to sit for months, so
neither is ever reported as going quiet. A digest that nags about things you
already decided about is a digest people stop reading, and then it is worse than
nothing.

This is also the cheapest collaboration Cairn has: in a shared channel it means
three people know what each other did without anyone opening a graph. Try it
before building anything that syncs.

## The map

`build/graph.html` is a single self-contained file — no server, no CDN, no
build step beyond `make build`. Open it from disk.

Layout is **time-ordered**, not force-directed: x is the creation date, y is a
project lane. Research history has a real time axis and a force layout throws
it away; it also means node positions are stable between builds, so the map
stays memorable.

It's a full interactive app, just one served from disk instead of a server:

- **hover** a node → card with its status, date and latest history note
- **click** → side panel: rendered body, clickable commit link, DOI links,
  parent/child links you can navigate, and a link to the node's markdown source
- **isolate lineage** → collapse to one node's full ancestry and descent. On a
  milestone that's every experiment that fed the paper, dead ends included
- **typed relations** → grey arrows are lineage; coloured, dashed ones carry
  meaning (`supports` / `contradicts` / `supersedes` / `resolves`), each with a
  one-line reason, backlinked so a contradiction is findable from both ends
- **copy link** → deep link to a node (`graph.html#<node-id>`)
- **the "as of" slider replays history** from the `history` log — drag it back
  and the graph shows what was known then, with the statuses of that date, and
  the panel follows
- filter by project / type / status, search, pan, wheel-zoom, `/` to search,
  `Esc` to close; colour = status, shape = type
- URL params: `?since=YYYY-MM-DD`, `?project=<key>`, `#<node-id>`

`build/graph.md` is a Mermaid fallback that renders in GitHub, an editor, or a
terminal.

Because the whole graph is in git, checking out an old commit and re-rendering
replays the research history a second way, for free.

## Design decisions

These are settled. See `docs/schema.md` for the field reference and `CLAUDE.md`
for the conventions the agent follows.

1. **Separate repo.** One graph spans all projects; nodes carry `project:`.
   This is what makes the laptop/HPC split tractable.
2. **Reference commits, never branches.** Branches get merged and deleted, and
   the most valuable nodes here are the dead ends git is designed to garbage
   collect.
3. **One file per node, append-only.** Never delete a node; change its status.
   Files never move; `id` is permanent.
4. **Tiny schema.** Every optional field is a field that stops getting filled in.
5. **Status is an event log.** `history:` gives the time axis for free, which
   is what makes replay and the weekly digest work.
6. **Nothing is committed unreviewed.** Draft the node, show it, then commit.
   An auto-populated graph nobody has read is the failure this project exists
   to avoid. Unprompted capture goes to `inbox/` instead.
7. **Capture ≠ structure.** `inbox/` accepts unstructured junk from anywhere;
   a separate triage pass turns junk into nodes. Never require filing at
   capture time — that's how capture dies.
8. **Artifacts stay where they are.** Nodes reference big outputs by
   `host:/path`. The repo stays small forever, so it syncs instantly and diffs
   stay readable.
9. **One graph, many writers, synced through git.** No server, no auth, no
   real-time editing, no discussion threads — but multi-writer was never the
   thing being refused. One file per node, append-only and never renamed, is
   what makes two people non-colliding, and `git log --diff-filter=A` already
   answers "whose node is this?" without a field for it. Add collaborators to
   the repo; don't shard the graph per project, or you lose the cross-project
   edges that are the hardest part to reconstruct.

## Two machines, or two people

Clone on every machine you work on, synced through this remote, and run
`make setup` on each. Neither machine ever needs to reach the other: nodes
reference code by `repo` + `commit` and outputs by `host:/path`.

`git pull --rebase` at the start of a session, commit and push at the end.
Conflicts are near-impossible — nodes are separate append-only files. The only
shared-file contention is `build/`, which should be regenerated, never merged.

**The same mechanism carries a second person.** Two machines and two people are
the same problem to this repo, so a collaborator is a collaborator on the git
remote and nothing more. The one genuine collision is two people creating the
same id on the same day — same project, same date, similar enough title to slug
identically. Git catches that as a real conflict rather than losing one of them,
which is the correct behaviour, if a startling way to find out.

## Status

Phase 0 and Phase 1 tooling are built, and the graph is backfilled: **55 nodes
across 8 projects**, reconstructed from five weeks of Claude sessions on kestrel
(2026-06-24 to 2026-08-02) plus the project repos' own reports and git history.

**Next step is two weeks of living with it** — before `/weekly`, `/capture`,
`/triage`, the papers registry, or `/review`. The failure mode for this project
is building the whole system and then not using it.

The backfill was also the first real test of the tooling, and using the result
was the second. Between them they found three things:

1. The pre-commit hook probed for "a `python3` that can `import yaml`", which is
   satisfied on Kestrel by a 3.6.8 too old to parse `lib.py` — so every commit
   was blocked with a SyntaxError reported as schema drift. Fixed by
   `scripts/find_python.sh`.
2. **Frontmatter did not round-trip.** An unquoted comma inside a flow-style
   history note split the value and turned its tail into a key: `note: past
   1,000 systems` silently became `note: past 1` plus a junk key `000 systems`.
   17 of the 55 backfilled nodes were affected. The writer now quotes flow
   scalars properly, and the validator rejects unexpected keys in a history
   entry so the same class of corruption can't return quietly.
3. **Untyped edges lost information.** Three findings could only be connected in
   prose. Hence `relates` — the one schema addition, argued for in
   `docs/schema.md`.

Two node types that wanted extra fields (milestones reaching for
`repo`/`artifacts`) were made to use their bodies instead.

`refs:` is deliberately empty everywhere. The sessions cite plenty of papers,
but a DOI recalled rather than resolved is worse than no DOI — populate the
papers registry with verified metadata rather than backfilling it from memory.
