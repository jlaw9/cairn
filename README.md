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

### What about Graphify?

[Graphify](https://github.com/Graphify-Labs/graphify) turns a codebase into a
queryable knowledge graph — tree-sitter AST parsing, typed edges (`calls`,
`imports`, `inherits`), Leiden community detection, an interactive
force-directed `graph.html`, and a generated `GRAPH_REPORT.md` naming the
most-connected "god nodes". It is good, it is fast, and it is **orthogonal to
this**.

The distinction is the one its own commenters kept making: Graphify maps the
**current state of a codebase**; Cairn maps the **history of research
decisions**. Graphify does read `# WHY:` and `# HACK:` comments and ADRs as
first-class nodes, so it captures rationale that *exists in the repo* — but a
dead end leaves no comment, because the code was deleted. "We tried fitting
published final Tg values as Tgp and the literature refutes it" is not in any
AST, will never be in one, and is exactly the node that stops the idea being had
twice. Same for *when* a decision was made, which Cairn gets free from `history`
being an event log and Graphify has no axis for.

Practically: run both. Graphify in a project repo to orient in the code, Cairn
across projects to know what has been tried. Three of its ideas were worth
taking, and two of them are in here:

- **The generated report as an entry point.** `build/report.md` — see below. Its
  "start here" section is Graphify's god-nodes idea; its "connections across
  projects" section is the surprising-connections idea, except the definition can
  be exact here rather than heuristic.
- **`EXTRACTED` vs `INFERRED` on every edge**, so you always know what was read
  versus guessed. The analogue that matters here is *contemporaneity* — was this
  node written the day the work happened, or reconstructed six weeks later? — and
  it was already derivable from git, so it cost no field.
- **A git merge driver** that union-merges the generated graph on parallel
  commits. Cairn's version of that problem is `build/`, and `cairn sync` now
  resolves it by regenerating rather than merging.

Not taken: force-directed layout (research history has a real time axis, and a
force layout throws it away), and a vector store or MCP server for search (110
nodes of text parse in well under a second).

## Install — once per machine

**New here, or setting up a machine that isn't the one this was written on? Read
[docs/install.md](docs/install.md).** It is the same four steps, spelled out,
with the failure modes named — including what to do when a cluster's `python3`
can't run the scripts at all.

```sh
git clone <your-cairn-remote> ~/Cairn-graph && cd ~/Cairn-graph
make setup                                  # hook + slash commands + checks
export CAIRN_PATH=$HOME/Cairn-graph         # add to your shell profile
export PATH=$CAIRN_PATH/bin:$PATH           # optional: plain `cairn` anywhere
make doctor                                 # confirm all four steps took
```

Then wire the machine up once, so every session sees the graph without a
per-project step:

```sh
cairn install_context            # dry run: says what it would change
cairn install_context --apply
```

That does three things, none of them per-project:

1. Writes a marked block into `~/.claude/CLAUDE.md` — user-level memory, loaded
   in every session in every directory — naming the graph and the four verbs.
2. Installs a `SessionStart` hook running `cairn session_hook`, which pulls
   (throttled) and returns the graph's current state as the session's context,
   plus a `SessionEnd` hook that says what is unpushed.
3. Symlinks the slash commands, so `/log`, `/standup`, `/capture`, `/triage`
   and `/digest` resolve from any repo.

**The hook is the part a pointer can't do.** A line in a `CLAUDE.md` has to be
*followed*, and an agent in the middle of a task does not go looking; state
already in the context window gets used. `cairn session_hook --dry-run` prints
exactly what a new session will be told, and `cairn install_context --remove`
takes all of it back out. Everything it writes is inside markers, so it never
touches a setting it didn't write — including other people's hooks on the same
events.

The older, narrower route still works and is worth knowing about, because it is
what makes the conventions reachable rather than just the pointer: one line in a
project repo's own `CLAUDE.md`.

```markdown
Research activity is recorded in Cairn. To capture a note, resume a project, or
log a session, read the matching skill under `$CAIRN_PATH/skills/`.
```

That makes three skills reachable at zero cost until used — see
[skills/README.md](skills/README.md).

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

**At corpus scale — hundreds or thousands of PDFs — read
[docs/literature.md](docs/literature.md).** Those papers can't each get a node,
and the answer is not one node per cluster either: the map is an artifact, one
node describes the mapping run, and a cluster becomes a node only once someone
has read it. That doc works out the pipeline, why cluster *identity* is the hard
part when node ids are permanent, and where the boundary sits between "corpus
member", "cited evidence with a `papers/` page", and "a claim of its own".

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
build/       generated: graph.html (self-contained), graph.md (Mermaid),
             report.md (where to start, and how much to trust a gap)
scripts/     lib.py, validate.py, build_graph.py, new_node.py, add_paper.py,
             mine_sessions.py, digest.py, standup.py, capture.py, sync_issues.py,
             sync.py, note.py, import_note.py, report.py, session_hook.py,
             install_context.py
skills/      path-addressed skills, so agents in *other* repos can use the graph
docs/        install.md, schema.md, backfill.md, worked examples
```

`make doctor` · `make validate` · `make build` · `make digest` · `make standup` ·
`make sync` · `make push` · `make test`

In a node body, `[[2026-07-01-polyid-network-ablation]]` refers to another node
and renders as a link to it, labelled with that node's title. `make validate`
warns if the target doesn't exist.

## What to pick up today

```sh
cairn standup                         # every project, most-needs-you first
cairn standup --project polyid        # the resume packet for one project
```

`digest` answers *what changed*, which is the right question when you have been
present all week and the wrong one after two weeks away — then you don't need a
list of events, you need the frontier: what is still open, what it was waiting
on, and what the last note said to do next.

Two differences carry it. It is **ordered by what needs you rather than by when
it happened**, so a project whose live threads have gone quiet ranks above one
that moved yesterday — the quiet one is the one whose context you have lost.
And it **reads `## Next` back out of the node bodies**, which is the cheapest
resume there is: the sentence you wrote when the whole problem was still in your
head. That section was always the convention and nothing ever read it.

`--project` goes deeper and adds the part that stops repeated work: **what this
project already settled**, most recent first, each with the note saying why. A
`dead` node there is a claim someone refuted, and rereading it is how the same
dead end doesn't get tried twice.

Like `digest`, it invents no fields and no bookkeeping — it is a query over
`status`, `history` and the bodies. Nothing to maintain means nothing to go
stale, and a stale planning view is worse than none because you act on it.

## Capture, from anywhere

```sh
cairn capture "the block-size distribution might be bimodal"
cairn capture --project mdegrade --title "q vs stack size" "<longer note>"
cairn capture --from-file ~/notes/meeting.org --title "meeting with Dave"
tail -40 slurm-12345.out | cairn capture --title "why the run died"
```

Writes to `inbox/`, which has no schema and no validation. It **never refuses,
never prompts, and never asks which project** — `--project` is a hint for triage,
not a validated key, and this is the one place in Cairn where a typo costs
nothing. It doesn't even commit, because committing runs the validation hook and
a capture that can fail on unrelated schema drift is not a capture.

That is design decision 7 finally having a command. It also means capture no
longer depends on which machine you are on or what editor is installed there:
`--from-file` takes org-mode, markdown or anything else verbatim, so an
org-capture template on a laptop and a shell on a cluster are the same mechanism.
Nothing in `inbox/` is ever parsed, so there is nothing to convert.

`/triage` turns the queue into nodes, or discards it. Both are correct outcomes.

For a file that already exists somewhere else — a meeting's org buffer, a pasted
mail, notes someone sent you:

```sh
cairn import_note ~/notes/2026-08-26-dave.org --meeting --who dave
cairn import_note ~/Downloads/scribbles.md --project polyid
pbpaste | cairn import_note --meeting --who "dave, sarah" --title "CG handoff"
```

A meeting import writes **two** files, and that is the design rather than an
accident. The notes themselves go to `meetings/<date>-<who>.md`, because a
meeting note is a durable record you find by who was in the room. A one-line
pointer goes to `inbox/`, because the thing that belongs in a queue is not the
record but the *obligation to read it*, and that is what `/triage` consumes.
Content lands verbatim, always — org markup in a `.md` file is not a problem to
be solved.

## Notes on a node

```sh
cairn note 2026-07-20-polyid-run-variance "the spread looks bimodal — seeds?"
cairn note polyid-run-variance                 # unique suffix is enough; opens $EDITOR
cairn note --list --project polyid
```

The agent writes the record; you read it later and have a reaction — a doubt, a
correction, "the number here is wrong", "this is the one that matters". Until
this existed the only places to put that were a status change, which lies about
what happened, and the inbox, which detaches the thought from the node it is
about.

A note appends a dated bullet under `## Notes` in the node body:

```
- **2026-08-26** (jlaw) the spread looks bimodal — does it track the seed?
```

`standup`, `digest`, `build/report.md` and the map all read them back. Three
things are deliberate:

- **It is a body edit, not a status change.** `status`, `updated` and `history`
  don't move, because a note isn't a claim about the state of the work. If it
  moved `updated`, the replay slider would show a change that never happened.
- **No new field**, against rule 5. The line carries its own date, so it stays
  findable by reading the body — exactly how `## Next` is already read.
- **"Unanswered" is derived.** A note dated at or after the node's last history
  entry is one no later work has responded to; once the thread moves, it stops
  being reported. That is what keeps it off a nag list.

It **commits by default**, which is the one place this differs from `capture`:
design decision 6 refuses to commit a node *you haven't seen*, and a sentence you
just typed is the definition of seen. The whole value is that it's visible from
the other machine tomorrow. The note is written to the file before the commit is
attempted, so a commit that fails on unrelated schema drift costs it nothing.

And it works the other way round too — this is the answer to "can Claude pick up
on comments I left?". Yes: notes are in the node body, so they are in `standup`'s
resume packet, in the session-start context, and in the report. A note is how you
hand an instruction to next week's session without writing a prompt.

## Where to start, and how much to trust a gap

`make build` also writes **`build/report.md`**, which answers the questions the
map and `standup` don't:

- **Start here** — the most-connected nodes. Everything hangs off these, so
  they're the cheapest way into a project, and changing what one claims has the
  widest blast radius.
- **Connections across projects** — every edge whose two ends sit in different
  projects. A project repo cannot know about these, which is precisely why the
  graph is one graph and not one per project.
- **Coverage** — per project: how many nodes, how many settled, how many dead
  ends, and *what share were committed within a week of the work they describe*.
  This is the table that makes the "a missing node means not tried" rule usable
  at all. A project at 0% is a reconstruction, and a reconstruction is biased
  toward what worked, so a gap there means the graph doesn't know.
- **Reconstructed after the fact**, **Unattached**, and **notes nobody answered**.

That contemporaneity number is the one idea worth taking from
[Graphify](https://github.com/Graphify-Labs/graphify), which tags every edge
`EXTRACTED` or `INFERRED` so you always know what was read versus guessed. The
same distinction matters here and is already *derivable* — git knows when the
file landed, the frontmatter says when the work happened, and the difference is
capture lag. It costs no field, which is the only reason it belongs.

## What changed, and what needs you

```sh
cairn digest                          # the last 7 days
cairn digest --project photopoly --days 1     # right before that meeting
cairn digest --format brief --mail    # one line per item — right size for mail
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

Use `--format brief` for anything mailed. The full form is the right length for a
terminal and too long for a mail client, where it competes with the map and loses
— a mailed digest's job is to say what deserves a click, not to reproduce the
graph in text.

### Tasks as issues

```sh
cairn sync_issues              # dry run — prints, writes nothing
cairn sync_issues -v           # ...including the exact body it would post
cairn sync_issues --apply
```

**Only `task` nodes, and only outward.** A task has a `due`, an owner and no
scientific claim, so an issue holds it faithfully. An `experiment` is open or
closed to GitHub, while the point of this graph is that `dead` is not `closed`,
`parked` is neither, and the status event log is what makes replay work — so
mirroring an experiment would discard the part worth keeping.

What issues buy that a markdown file cannot: assignment, notification, and a
phone. The graph stays authoritative and each issue says so in its own body.

The target repo is **derived** from the project's other nodes, not stored per
task — an experiment in the same project already carries `repo`. Projects with no
GitHub remote are reported and skipped, never guessed at.

`sync_issues` reaches Enterprise hosts (`gh auth login --hostname <host>` first).
Whether *mentioning an agent* on an issue works there is a different question and
an open one — and the agent round trip only closes at all for issues in this repo,
since an agent in a project repo has no checkout of the graph.
**[docs/github.md](docs/github.md)** has the table, the prompts to test with, and
the numbers.

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
  the panel follows. **`▶` plays it**, which is the difference between a control
  and an animation: nobody drags a slider to watch a shape change, and the
  animation is what makes five months legible at once
- **needs you** → collapse to what is actually waiting: a thread whose status
  asserts activity but which has gone quiet, or a node carrying a note nobody has
  answered. Same rule as `cairn standup`, evaluated against the slider's date, so
  "needs you as of June" means what it meant in June
- **leave a note** → type it in the panel and copy the exact `cairn note` command
  to your clipboard. The page is `file://` with no server by design, so it cannot
  write to the repo — and a comment living in one browser's localStorage, invisible
  from the other machine, is the failure this whole repo exists to avoid. Two
  keystrokes at a terminal and the note is in the node body, in git, on both
  machines, where `standup` and the next agent session both find it
- **keyboard navigation** — arrow keys walk the layout (x is time, y is a project
  lane), `p`/`c` walk the edges, `i` isolates, `n` writes a note, `w` toggles
  needs-you, `space` plays the replay, `/` searches, `Esc` closes
- a ring marks a node that needs you; a dot marks one carrying a note. Marks on
  top of the glyph, never changes to it — shape already means type and fill
  already means status, so a third axis has to be a decoration or the map stops
  being decodable
- filter by project / type / status / author, search, pan, wheel-zoom
- URL params: `?since=YYYY-MM-DD`, `?project=<key>`, `#<node-id>`

`build/graph.md` is a Mermaid fallback that renders in GitHub, an editor, or a
terminal.

**`nodes/` is already an Obsidian vault**, and nothing had to be built for that.
Node bodies refer to each other as `[[<node-id>]]`, which is Obsidian's own
wikilink syntax, so pointing Obsidian at this repo gives you backlinks, a local
graph view, full-text search, and a mobile app — over the same files, in the same
git remote, with no export step. Use it when you want to *write*; use
`graph.html` when you want the time axis, the replay and the lineage view, which
Obsidian has no idea about.

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
`make setup` and `cairn install_context --apply` on each. Neither machine ever
needs to reach the other: nodes reference code by `repo` + `commit` and outputs
by `host:/path`.

```sh
cairn sync                     # pull, then say what still needs you
cairn sync --push              # regenerate build/, commit build/, push
cairn sync --check             # no network; local state only
```

The friction here was never storage — that question got asked and refuted, in
`2026-08-21-cairn-database-question`. It is a **habit gap at two moments**:
forgetting to pull before working, and forgetting to push after. The second is
the expensive one, because the work is written down and simply invisible from
the other machine.

So `sync` automates the half that is safe to automate and *reports* the half
that isn't. **It never commits a node** — design decision 6 — so `--push`
commits only `build/`, which is generated. Nodes stay uncommitted and get named,
because a node file that has never been committed is almost always a draft
nobody has read yet.

Conflicts are near-impossible: nodes are separate append-only files. The only
shared-file contention is `build/`, and `sync` resolves that itself the way this
README always prescribed — when a rebase stops *only* on `build/`, it
regenerates rather than merging, and continues. A conflict anywhere else is left
for a human, because anywhere else it means something interesting happened.

With `install_context` in place, the pull happens on its own at session start
and the "you have unpushed work" warning at session end. Neither replaces
`sync --push`; they make forgetting visible.

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
