# <img src="docs/img/cairn.svg" height="30" alt=""> Cairn

**The research record an agent keeps: a git-backed graph of what was tried, dead ends included.**

A persistent DAG of research activity across projects — experiments, dead ends,
open threads, conference ideas, tasks with deadlines, papers, milestones —
written by Claude Code as a side effect of doing the work, and rendered as a
clickable map.

**Two repos.** This one is the tool, `$CAIRN_PATH`. Your graph is its own repo,
created with `cairn init` and found through `$CAIRN_ROOT` — so the tool can be
shared without shipping anyone's research record, and one tool can serve several
graphs. A pre-split clone with `nodes/` beside `scripts/` keeps working
unchanged. `example/` will hold a scrubbed, generated copy of this project's own
subgraph — a tool for recording research decisions is best explained by the
record of its own — once the release review below clears it; until then it is
generated locally and gitignored.

The point isn't visualization. The point is that six months from now, *"did we
already try this, and what happened?"* has an answer, and *"what should I do
next?"* has a defensible one.

**Documentation.** The long-form docs — the model, the two kinds of edge, the
four workflows, the map, and the design rationale — live in [`site/`](site/) and
publish to <https://jlaw9.github.io/cairn/>. **That URL is not live yet:**
publishing is gated on `2026-08-05-cairn-release-review`, since Cairn was written
on lab time and a public Pages site is a release. Preview it locally with
`make site-serve`, and see [`site/README.md`](site/README.md) for how it is put
together.

## Contents

- [Why this can exist now](#why-this-can-exist-now) — long version [on the site][site-why]
- [Install — once per machine](#install--once-per-machine) — `onboard` · [Your own graph](#your-own-graph) · [The one dependency](#the-one-dependency)
- [Standalone, or with OpenViking](#standalone-or-with-openviking) — `openviking`
- [Then pick your path](#then-pick-your-path)
  - [A. Work that already happened → backfill first](#a-you-have-work-that-already-happened--backfill-first)
  - [B. Starting something new → open the node before you run it](#b-you-are-starting-something-new--open-the-node-before-you-run-it)
  - [C. Starting from a literature review](#c-you-are-starting-from-a-literature-review)
  - [D. Your work isn't computational](#d-your-work-isnt-computational)
- [What's here](#whats-here) — the tool, and the graph
- [What to pick up today](#what-to-pick-up-today) — `standup`
- [Capture, from anywhere](#capture-from-anywhere) — `capture`, `import_note`
- [Notes on a node](#notes-on-a-node) — `note`
- [Who presses commit](#who-presses-commit) — `policy`
- [Which claims a human has actually read](#which-claims-a-human-has-actually-read) — `review`
- [Where to start, and how much to trust a gap](#where-to-start-and-how-much-to-trust-a-gap) — `build/report.md`
- [What changed, and what needs you](#what-changed-and-what-needs-you) — `digest` · [Tasks as issues](#tasks-as-issues)
- [The map](#the-map) — `build/graph.html` · [Writing from the map](#writing-from-the-map) — `serve`, `edit`
- [Design decisions](#design-decisions)
- [Two machines, or two people](#two-machines-or-two-people) — `sync`
- [Status](#status)
- The site: [overview] · [the model] · [using it] · [the map] · [design] · [notebook]

[overview]: https://jlaw9.github.io/cairn/
[the model]: https://jlaw9.github.io/cairn/model.html
[using it]: https://jlaw9.github.io/cairn/workflows.html
[the map]: https://jlaw9.github.io/cairn/map.html
[design]: https://jlaw9.github.io/cairn/design.html
[notebook]: https://jlaw9.github.io/cairn/blog/

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

The long version — the prior art, and why [Graphify][gfy] is orthogonal to this
rather than a competitor — is on the site: **[why this can exist now][site-why]**.
Three of Graphify's ideas were worth taking and two are in here.

[gfy]: https://github.com/Graphify-Labs/graphify
[site-why]: https://jlaw9.github.io/cairn/design.html#prior

## Install — once per machine

**[docs/install.md](docs/install.md) is the authority for setup** — the same
steps spelled out, with the failure modes named, including what to do when a
cluster's `python3` can't run the scripts at all.

```sh
git clone https://github.com/jlaw9/cairn ~/cairn && cd ~/cairn
make python                                 # the interpreter Cairn will use, or why not
bin/cairn onboard                           # three questions; the answers land on disk
export CAIRN_PATH=$HOME/cairn               # the tool  — add these to your profile
export CAIRN_ROOT=$HOME/research-graph      # your graph
export PATH=$CAIRN_PATH/bin:$PATH           # optional: plain `cairn` anywhere
cairn doctor                                # confirm every step took
```

`onboard` asks three things, and keeps no config file — each answer becomes a
fact on disk that `doctor` reads back:

1. **Where is your graph?** Created with `cairn init` if it doesn't exist:
   directories, a `CLAUDE.md` with the conventions, `git init`, the validation
   hook.
2. **Commit policy** — `ask` or `auto`. See [Who presses commit](#who-presses-commit).
3. **Which sessions see the graph?** Every Claude Code session on this machine,
   or only sessions started in one project.

Every question has a flag, so an agent can run it:
`cairn onboard --graph ~/research-graph --commit-mode auto --scope project=. --yes`.
Cloned an existing graph rather than `init`ing one? Point `CAIRN_ROOT` at it and
run `cairn install_hooks $CAIRN_ROOT`.

**Keep the graph outside every project repo.** One graph spans all projects
(design decision 1), and a graph nested inside a project shows up as untracked in
that project's `git status`, makes `/log`'s `repo` field ambiguous, and quietly
implies the graph belongs to one project. `cairn init` refuses to nest one.

The third question is `install_context`, which is worth understanding rather
than just running:

```sh
cairn install_context                               # dry run: says what it would change
cairn install_context --apply                       # every session on this machine
cairn install_context --project ~/work/polyid --apply   # only sessions started there
```

Machine-wide, it writes three things under `~/.claude`: a marked block in
`CLAUDE.md` naming the graph and the four verbs; a `SessionStart` hook running
`cairn session_hook`, which pulls (throttled) and hands the session the graph's
state and the commit policy in force, plus a `SessionEnd` hook that says what is
unpushed; and symlinks so `/log`, `/standup`, `/capture`, `/triage`, `/digest`
and `/paper` resolve from any repo. With `--project <path>` the same three land
inside that project instead — `CLAUDE.local.md`, hooks in
`.claude/settings.local.json`, and `.claude/commands/` — the two `.local` files
being the ones git convention already ignores, so this machine's absolute paths
never reach a collaborator.

**The hook is the part a pointer can't do.** A line in a `CLAUDE.md` has to be
*followed*, and an agent mid-task does not go looking; state already in the
context window gets used. `cairn session_hook --dry-run` prints what a session
will be told, and `--remove` takes it all back out — everything is written
inside markers, so it never touches a setting it didn't write. The older route,
one line in a project's `CLAUDE.md` pointing at `$CAIRN_PATH/skills/`, still
works; see [skills/README.md](skills/README.md).

**`cairn doctor` is the thing to run when something is off.** It reports,
without needing a working Python, which install step is missing: interpreter,
hook, slash commands, `CAIRN_PATH`, `CAIRN_ROOT`. Each of those fails
differently and none of the failures names itself, which is how a first install
goes wrong. Do all of this on every machine you work on — laptop and cluster
both.

### Your own graph

If you are not the person this was written for, this is the whole path from a
clone to a graph of your own. Everything above is assumed done.

```sh
cd $CAIRN_ROOT
cairn new_node direction "Does X predict Y?" --project demo      # first project needs no --new-project
cairn new_node experiment "X predicts Y" --project demo --parent <direction-id> --status planned \
  --body "Expect R2>0.5 on held-out; wrong if R2<0.2." --note "pre-registered"
cairn new_node task "Request data access" --project demo --parent <direction-id> --due 2026-10-30
cairn validate && cairn build && cairn standup
git add nodes && git commit -m "first nodes"        # you read them, then you commit; sync never commits nodes
git remote add origin <your-graph-remote> && cairn sync --push
cairn serve --port 8790                             # the map, live, at localhost:8790
```

**Commit the first nodes before anything else.** Notes and reviews commit one
node at a time, which git refuses for a file it has never seen, and an
uncommitted node is invisible from your other machine. Nodes you type yourself
you commit yourself, whatever the [commit policy](#who-presses-commit) — that
setting decides only what an agent does with the nodes *it* writes. Replace `<direction-id>`
with the id the first command printed.

### The one dependency

Cairn needs **Python >= 3.7 with PyYAML** and nothing else. `scripts/find_python.sh`
finds a suitable interpreter rather than assuming `python3` is one — on Kestrel
the default `python3` is 3.6.8 *with* PyYAML while `python3.9` has none.

**This is why every command here is `bin/cairn <something>` rather than
`scripts/<something>.py`.** The dispatcher is `/bin/sh`, so it has no Python
version of its own to trip over; it execs the same interpreter `make` and the
hook use. A script run directly gets whatever `#!/usr/bin/env python3` resolves
to, and no shim inside it can help — Python compiles the whole file first, so on
3.6 the SyntaxError arrives before any fallback runs.

No PyYAML anywhere? [docs/install.md](docs/install.md) §2 has the install for
each kind of Python (on Homebrew's, `pip install` is refused under PEP 668), or
`export CAIRN_PYTHON=/path/to/python`. `capture`, `sync`, `policy`, `onboard` and
`openviking` need no PyYAML at all, so a thought is never lost to a broken
install.

## Standalone, or with OpenViking

Two setup paths, both first-class, and the graph format is identical either way.

**Standalone** is the complete tool: `cairn onboard`, three questions, done. The
session hook gives every session the graph's state; `/log`, `/capture`, `/triage`
and the skills do the writing; the map does the reading.

**With [OpenViking](https://github.com/volcengine/OpenViking)**, install it and its
Claude Code plugin first; `onboard` detects `ov` and offers to register the graph.
The reason to run both is that they answer neighbouring questions. OpenViking is
an agent's memory substrate — session history, summarization, semantic retrieval
over everything it has seen. Cairn is the research-progression view — claims,
dead ends, lineage, review, and a replay of how it looked in June. **Memory is
extracted; a record is asserted.** OpenViking makes an agent *remember*; Cairn
makes the research *legible*. Neither does the other's job.

```sh
cairn openviking status          # is `ov` here, is a server up, what would be pushed
cairn openviking push            # dry run: prints the `ov add-resource` commands
cairn openviking push --apply    # registers them
```

That is the whole seam. **The graph becomes a resource** — `nodes/`,
`build/graph.md` and `build/report.md` under `viking://resources/cairn/<graph>/`
— so OpenViking's recall answers "did we already try this?" in every session it
serves. **Memories come back only as capture**: `cairn capture` into
`$CAIRN_ROOT/inbox/`, for `/triage` to judge, never as nodes, because a missing
node can only mean "not tried" if every present node was put there on purpose.
Cairn does not import OpenViking's package (AGPLv3, and it needs a server and two
models; Cairn's one dependency stays PyYAML), stores no OpenViking state in a
node, and puts no server in the path of the map, the hook, `standup`, `sync` or
the validator.

**It has not yet been run against a live OpenViking server.** The command is
built and tested against a stub `ov`, and the dry run exists so a wrong flag
costs a read, not a write. [docs/openviking.md](docs/openviking.md) has the seam
in full, and the two places the systems overlap.

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

`planned` and `running` are different facts and the replay slider shows both.
An experiment created with no `--status` is still `running`, so writing up work
after the fact is unchanged.

At the end of a session, `/log` from inside the project repo does the rest: it
reads the git log, drafts the node, asks only for the interpretation it can't
infer, and then — under `ask` — shows it and waits, or — under `auto` — commits
it and says so.

```sh
cairn build && open $CAIRN_ROOT/build/graph.html
```

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

Do the retrieval with whatever literature tooling you already use; what lands
here is the conclusion and the verified DOIs, not the corpus.

**At corpus scale — hundreds or thousands of PDFs — read
[docs/literature.md](docs/literature.md).** Those papers can't each get a node,
and nor can each cluster: the map is an artifact, one node describes the mapping
run, and a cluster becomes a node only once someone has read it.

### D. Your work isn't computational

The *model* here is domain-neutral — claims, results, dead ends, directions,
deadlines. `repo`, `commit`, `host` and `artifacts` are all optional on an
experiment, so a bench experiment node validates today with none of them, and
a node with no SHA is not a second-class node.

The *interface* is not neutral, but it was never meant to be the interface: an
agent writes the record while you work, and you answer one question — what the
result means. See [docs/backfill.md](docs/backfill.md) §C.

Work that happened somewhere Cairn can't see — a web session, a conversation, a
whiteboard — goes in `$CAIRN_ROOT/inbox/` as unstructured text and gets triaged
later. Capture always beats filing.

## What's here

**The tool** — this repo, `$CAIRN_PATH`:

```
bin/cairn    the dispatcher — run everything through it
scripts/     lib.py, validate.py, build_graph.py, new_node.py, add_paper.py,
             add_dataset.py, mine_sessions.py, standup.py, digest.py, report.py,
             capture.py, import_note.py, note.py, review.py, edit.py, discard.py,
             policy.py, sync.py, sync_issues.py, session_hook.py,
             install_context.py, init.py, onboard.py, serve.py, export.py,
             export_example.py, openviking.py, check_site_links.py;
             find_python.sh, doctor.sh, install_hooks.sh, graph_template.html
skills/      path-addressed skills, so agents in *other* repos can use the graph
docs/        install.md, schema.md, backfill.md, literature.md, github.md,
             openviking.md, worked examples
site/        the documentation site — hand-written HTML, no build step
example/     generated: a scrubbed copy of this project's own subgraph
```

**The graph** — its own repo, `$CAIRN_ROOT`, made by `cairn init`:

```
nodes/       the graph — one file per node, append-only, never deleted
papers/      one page per cited paper, keyed by DOI, CrossRef-verified
datasets/    one page per dataset nodes cite in `data:` — sha256, host:path, tier
meetings/    raw meeting notes
inbox/       unstructured capture awaiting triage
assets/      small figures only — assets/<node-id>.<ext>, shown in the panel
build/       generated: graph.html (self-contained), graph.md (Mermaid),
             report.md (where to start, and how much to trust a gap)
CLAUDE.md    the graph's conventions, and its one setting: commit_mode
```

`cairn doctor` · `make validate` · `make build` · `make serve` · `make digest` ·
`make standup` · `make sync` · `make push` · `make test` · `make site-check` ·
`make site-serve`

In a node body, `[[2026-07-01-polyid-network-ablation]]` refers to another node
and renders as a link to it, labelled with that node's title. `make validate`
warns if the target doesn't exist.

**Datasets are registered the way papers are.** `artifacts` records what a node
produced; `data: [<key>]` records what it consumed, pointing at a
`$CAIRN_ROOT/datasets/<key>.md` page that `cairn add_dataset` writes. The
load-bearing field is `sha256` — a path can be overwritten, a hash names the
bytes — so `--file` measures it from a local copy rather than letting anyone
retype it. The field reference is under "Datasets registry" in
[docs/schema.md](docs/schema.md).

`cairn export --project <key> --dest <repo>/docs/research` is what a project repo
gets instead of its nodes: a filtered map, a Mermaid fallback and an index, all
generated and saying so. The nodes stay in the one graph.

## What to pick up today

```sh
cairn standup                         # every project, most-needs-you first
cairn standup --project polyid        # the resume packet for one project
```

`digest` answers *what changed*, the wrong question after two weeks away — then
you need the frontier: what is still open, what it was waiting on, and what the
last note said to do next. `standup` is **ordered by what needs you rather than
by when it happened**, so a project whose live threads have gone quiet ranks
above one that moved yesterday. And it **reads `## Next` back out of the node
bodies** — the cheapest resume there is, the sentence you wrote when the whole
problem was still in your head.

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

Writes to `$CAIRN_ROOT/inbox/`, which has no schema and no validation. It
**never refuses, never prompts, and never asks which project** — `--project` is a
hint for triage, not a validated key, and this is the one place in Cairn where a
typo costs nothing. It doesn't even commit, because committing runs the
validation hook and a capture that can fail on unrelated schema drift is not a
capture.

That is design decision 7 having a command. `--from-file` takes org-mode,
markdown or anything else verbatim, so an org-capture template on a laptop and a
shell on a cluster are the same mechanism; nothing in `inbox/` is ever parsed.

`/triage` turns the queue into nodes, or discards it. Both are correct outcomes.

For a file that already exists somewhere else — a meeting's org buffer, a pasted
mail, notes someone sent you:

```sh
cairn import_note ~/notes/2026-08-26-dave.org --meeting --who dave
cairn import_note ~/Downloads/scribbles.md --project polyid
pbpaste | cairn import_note --meeting --who "dave, sarah" --title "CG handoff"
```

A meeting import writes **two** files on purpose: the record goes to
`$CAIRN_ROOT/meetings/<date>-<who>.md`, found by who was in the room, and a
one-line pointer goes to `inbox/`, because what belongs in a queue is not the
record but the *obligation to read it*. Content lands verbatim, always.

## Notes on a node

```sh
cairn note 2026-07-20-polyid-run-variance "the spread looks bimodal — seeds?"
cairn note polyid-run-variance                 # unique suffix is enough; opens $EDITOR
cairn note --list --project polyid
```

The agent writes the record; you read it later and have a reaction — a doubt, a
correction, "this is the one that matters". A status change would lie about what
happened, and the inbox would detach the thought from the node it is about.

A note appends a dated bullet under `## Notes` in the node body:

```
- **2026-08-26** (jlaw) the spread looks bimodal — does it track the seed?
```

`standup`, `digest`, `build/report.md` and the map all read them back. It is a
**body edit, not a status change** — `status`, `updated` and `history` don't
move, or the replay slider would show a change that never happened. It adds **no
field**: the line carries its own date. And **"unanswered" is derived**: a note
dated at or after the node's last history entry is one no later work has
answered, and once the thread moves it stops being reported.

It **commits by default**, in either commit mode: design decision 6 is about
nodes nobody has read, and a sentence you just typed is the definition of read.
The note is written before the commit is attempted, so a commit that fails on
unrelated schema drift costs it nothing. And because notes are in the body, they
are in `standup`'s resume packet and the session-start context — a note is how
you hand an instruction to next week's session without writing a prompt.

## Who presses commit

```sh
cairn policy              # the mode in force, and what it means
cairn policy auto         # agents commit the nodes they write; you edit after
cairn policy ask          # agents draft, show, and wait (the default)
```

The policy is one line in the graph repo's own `CLAUDE.md` — `commit_mode: ask`
or `commit_mode: auto` — and the session hook states it at the start of every
session, so `/log` in any repo knows it without reading a file. Not a dotfile:
the one preference Cairn cannot derive goes where every agent already reads, in
git, next to the prose that says why, and a team shares it by sharing the repo.

- **`ask`**: the agent drafts the node, shows it, and commits only after you
  confirm. Nothing enters the graph unread.
- **`auto`**: the agent commits the node it wrote about work it did, right then,
  and says what it committed; you edit afterward. It still never commits a node
  about work it didn't do, never hand-edits `status:`, and never writes in your
  voice.

`auto` is safe to offer only because an unread node stays *visible* rather than
absent: `cairn review --list` derives from git which nodes nobody has read, in
either mode. It is policy over identical data, so two collaborators with
different modes still hold one graph. And whatever the mode, `sync` never
commits a node.

## Which claims a human has actually read

```sh
cairn review --list                    # what nobody has read
cairn review polyid-run-variance "the seeds explain it"
cairn review polyid-run-variance       # read it, nothing to add
```

A draft you decide not to keep is `cairn discard <id>`: it deletes a node file git has never seen, and refuses anything committed or modified, or any node another node points at. A node that has been committed is never deleted; change its status.

`reviewed` is **derived from git, never a field**. A commit that carries a
`Cairn-Review: <who> <node-id>` trailer says a human read that node; a node whose
last write came after its last stamp is one nobody has read since.

It has to be a message trailer rather than an identity. **Committer identity is
erased by `sync`**, since `git rebase` rewrites it twice a day; **author identity
is already spoken for**, since `git log --diff-filter=A` is how authorship is
derived. The trailer names the node id because a review with nothing to add is an
*empty* commit, which `git log -- nodes/<id>.md` never shows.

- **A note is a review.** `cairn note` stamps the trailer itself; `cairn review`
  with no text is for "I read it and had nothing to add", a real outcome.
- **Reviewing an uncommitted draft admits it** — file and stamp land in one
  commit. Under `ask` that is the queue design decision 6 creates, draining;
  under `auto` it is how a committed-but-unread node gets read.
- **What predates the convention stays `unclassified`**, left out of the report
  rather than counted as unread, because git has nothing to say about it.

What this is *not* is proof a human did the reading: agents run as whoever owns
the clone. The `commit-msg` hook only checks that a stamp is well-formed and
names a node that exists, because a mistyped id would otherwise mark nothing,
silently.

## Where to start, and how much to trust a gap

`make build` also writes **`$CAIRN_ROOT/build/report.md`**, which answers the
questions the map and `standup` don't:

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

That contemporaneity number is taken from [Graphify][gfy]'s `EXTRACTED` /
`INFERRED` edge tags, and here it is *derivable*: git knows when the file landed,
the frontmatter says when the work happened, and the difference is capture lag.
It costs no field, which is the only reason it belongs.

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

The filters that keep entries **out** are the substance: `parked` and an `open`
direction are never reported as going quiet, because a digest that nags about
things you already decided is one people stop reading.

This is also the cheapest collaboration Cairn has: in a shared channel it means
three people know what each other did without anyone opening a graph. Try it
before building anything that syncs.

Use `--format brief` for anything mailed: a mailed digest's job is to say what
deserves a click, not to reproduce the graph in text.

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
phone. The graph stays authoritative and each issue says so. The target repo is
**derived** from the project's other nodes — an experiment there already carries
`repo` — and a project with no GitHub remote is reported and skipped, never
guessed at. Enterprise hosts work (`gh auth login --hostname <host>` first);
whether *mentioning an agent* on an issue does is still open, and
**[docs/github.md](docs/github.md)** has the table and the prompts to test with.

## The map

`$CAIRN_ROOT/build/graph.html` is a single self-contained file — no server, no
CDN, no build step beyond `make build`. Open it from disk.

Layout is **time-ordered**, not force-directed: x is the creation date, y is a
project lane. Research history has a real time axis and a force layout throws
it away; it also means node positions are stable between builds, so the map
stays memorable. Within a lane a row is a thread: a child joins its parent's row
when there is room, so what sits on one line is one line of work.

The `x` control in the header (or `l`) swaps that axis for **lineage**: x is
how many hops a node is from a root, y packs each lane as a tree, and no dates
are involved. A project planned in one sitting has every node created today, and
on the time axis that is one column with the edges crumpled into the glyphs —
the lineage view is for laying out a plan before anyone knows when anything will
run, and for reading a project as an argument rather than as a calendar. The
time view is unchanged and still the default; `?layout=lineage` in the URL picks
the other.

It's a full interactive app, just one served from disk instead of a server:

- **lane names and months stay on screen** — project names sit in a gutter on
  the left and month labels in a strip along the top, and both follow the map
  as you pan and zoom. Click a lane name to fold the lane
- **hover** a node → card with its status, date and latest history note, plus
  why it needs you ("todo, quiet 73 d", "overdue 29 d", "unanswered note from
  2026-10-14"). While a search is active, the card shows the matching line
  instead, with the match in bold
- **one project in one gesture** → hover a project in the rail and click
  `only`, or alt/⌘-click the row. The same click on the lone project shows
  everything again. The filters are written to the URL (`?project=polyid`) as
  you change them, and hidden projects' lanes take no room
- **click** → side panel: rendered body, the node's figure if it has one,
  clickable commit link, DOI links, artifacts split into host and path (click to
  copy the path), parent/child links you can navigate, and a link to the node's
  markdown source
- **isolate lineage** → collapse to one node's full ancestry and descent. On a
  milestone that's every experiment that fed the paper, dead ends included
- **typed relations** → grey arrows are lineage; coloured, dashed ones carry
  meaning (`supports` / `contradicts` / `supersedes` / `resolves`), each with a
  one-line reason, backlinked so a contradiction is findable from both ends.
  They are drawn faint until you hover or open a node they touch, because a bow
  spanning four months and three lanes otherwise dominates a view it says
  little about
- **copy link** → deep link to a node (`graph.html#<node-id>`). Back and Forward
  walk the nodes you opened, and a `#<node-id>` typed into the address bar opens
  that node
- **the "as of" slider replays history** from the `history` log — drag it back
  and the graph shows what was known then, with that date's statuses. **`▶`
  plays it**: nobody drags a slider to watch a shape change, and the animation
  is what makes five months legible at once
- **needs you** → collapse to what is actually waiting: a thread whose status
  asserts activity but which has gone quiet, a node carrying a note nobody has
  answered, or a deadline that is missed or a week away. Same rule as
  `cairn standup`, evaluated against the slider's date, so "needs you as of
  June" means what it meant in June. The panel says why under the status
- **deadlines** → a task's `due` and a milestone's `date`, read against the
  slider's date. An open task or milestone (not done, dropped or accepted) is
  overdue once its date has passed. The rail's Deadlines section lists the
  overdue ones, then those due within 7 days, then milestones within 30 days
  (`date · title`, click to open), and it disappears when there are none. The
  panel's date row says how far off the date is ("2026-09-15, 29 d ago —
  overdue"). All of it is computed in the page; nothing is written
- **leave a note** → type it in the panel and copy the exact `cairn note` command.
  Opened as a `file://`, the page cannot write to the repo — and a comment in one
  browser's localStorage, invisible from the other machine, is the failure this
  whole repo exists to avoid. Run [`cairn serve`](#writing-from-the-map) and the
  same box saves directly
- **search reaches the bodies** — the claim, the result, `## Next`, the notes,
  and the history notes where a `dead` node keeps *why* it died
- **size is descent** → a glyph grows with how much work hangs off it, counted as
  of the slider's date
- **labels wrap** to two lines of about thirty characters and are elided after
  that — titles are claims, and 95% of the ones this was measured on ran past
  the old one-line cut. A node is half as wide as it was, so more of a lane
  fits on screen
- **colour by** status, needs-you, age, author or deadline — fill changes
  meaning, the legend says which, and nothing else is repainted. The status key
  lists the five colours with the statuses that share each. The deadline fill
  shows overdue, due within 7 days, due within 30 days, and no open deadline
- **fold a lane** to a strip of ticks at their real dates, keeping the time axis
  and every edge that leaves the lane
- **keyboard navigation** — arrow keys walk the layout (x is time, y is a project
  lane), `p`/`c` walk the edges, `i` isolates, `l` swaps time for lineage on x,
  `n` writes a note, `w` toggles
  needs-you, `space` plays the replay, `/` searches, `k` opens the chat (under
  `cairn serve`), `Esc` closes, and `?` lists every key
- a ring marks a node that needs you; a dot marks one carrying a note —
  decorations on the glyph, because shape already means type and fill status.
  The legend draws the map's own glyphs
- filter by project / type / status / author (statuses nobody holds are left
  out of the list), pan, wheel-zoom
- URL params: `?since=YYYY-MM-DD`, `?project=a,b` (and `type`, `status`,
  `author`), `?q=`, `?colour=`, `?layout=lineage`, `?folded=a,b`, `?needs=1`, `?iso=<id>`,
  `#<node-id>`

`build/graph.md` is a Mermaid fallback that renders in GitHub, an editor, or a
terminal.

**`$CAIRN_ROOT/nodes/` is already an Obsidian vault**, and nothing had to be
built for that. Node bodies refer to each other as `[[<node-id>]]`, which is
Obsidian's own wikilink syntax, so pointing Obsidian at the graph repo gives you
backlinks, a local graph view, full-text search, and a mobile app — over the same
files, in the same git remote, with no export step. Use it when you want to
*write*; use `graph.html` when you want the time axis, the replay and the lineage
view, which Obsidian has no idea about.

Because the whole graph is in git, checking out an old commit and re-rendering
replays the research history a second way, for free.

## Writing from the map

```sh
cairn serve                    # http://127.0.0.1:8787/build/graph.html
cairn serve --port 9000 --open
```

A thought you have *while looking at the map* — a doubt about a claim, a status
that is plainly wrong now, the experiment this one obviously implies — used to
have to be retyped at a terminal, and a node you never file is a node that does
not exist. `cairn serve` is a localhost writer that closes that gap:

- **leave a note** — the panel's note box saves directly instead of composing a
  command for the clipboard
- **move a status** — a select beside it, offering only the statuses that node's
  type actually has, with a one-line why that becomes the history note. A move to
  `dead`, `dropped`, `killed` or `abandoned` needs the why (a refuted claim is only
  citable with its reason); every other move is free. Enter applies
- **create a node** — `+ node` in the header makes a root; `+ child node` in an
  open node's panel prefills the parent and its project. The project starts as
  "choose…" (or the one project the map is showing), never a guess. The form
  previews the id the title will become, takes your own slug, a "why now" that
  becomes the first history note, and the type's own fields: `due` for a task,
  `date`/`venue` for a milestone, collapsed provenance (repo, commit, host, DOIs)
  for an experiment
- **start a project** — the project select ends in `+ new project…`
- **correct a node** — `edit` in the panel opens a form for its title, project,
  the scalar fields its type carries, parents, typed relations (with a required
  why), refs, artifacts and the markdown body, through `cairn edit`, which
  validates the result before writing and refuses `status` (that is the select
  above, because it moves `history` with it). The body is read from
  `nodes/<id>.md` when the form opens rather than shipped in the page. Only
  what changed is sent. An edit
  leaves `updated` alone: fixing a typo is not news. A mistake in a committed
  node is not deleted: add a `supersedes` relation from the corrected node, then
  close this one
- **review & commit, or discard** — a node git does not have yet (or one with an
  uncommitted edit) carries a hollow dot on the map and a banner in the panel,
  because it is invisible from the other machine. `review & commit` runs
  `cairn review <id> [note]`, which is what admits it; `discard draft` (an
  untracked file only, and it asks twice) runs `cairn discard <id>`

**The form is the one place in Cairn that insists on structure**, and only for an
experiment: it will not submit without a claim. The whole point of `planned` is a
claim written *before* the result — written after it, it is a story — and a
quick-add box is otherwise the cheapest possible way to fill the graph with
titled nodes that settle nothing. Everywhere else, capture wins and nothing is
required. `cairn capture` is still one keystroke away for a thought with no shape
yet.

A new project key gets its own guard, because it is the first word of every id in
that project, permanently: lowercase, digits and dashes only. And claiming a key
is new when the graph already has it does *not* pass `--new-project` — that flag
is what disables `check_project`, the guard that catches `photpoly` for
`photopoly`, the one typo that validates cleanly and silently splits a project in
two. Because the flag switches the guard off, the server runs the same near-match
check first: a key close to an existing one comes back as "did you mean
`photopoly`?", and the form offers `use photopoly` or `it really is new`.

**It is not a second store.** Every write shells out to `bin/cairn` — the same
code path `/log` and the terminal use — so the node file stays the only copy,
`status`/`history` still move together in `lib.Node.set_status`, and everything
the terminal refuses is refused here too. The view may create a node, append a
note, propose a status change, correct a node through `cairn edit`, and review or
discard one through those commands. It may never hand-edit frontmatter, there is no
endpoint that writes YAML, and the day one appears is the day the map becomes a
second source of truth.

The panel reports whatever the command said, including whether the write landed
in git — derived by asking git about the file rather than declared, because
`note` and `edit` commit and `new_node` does not. An uncommitted node is invisible
from the other machine, so it says so, and names `cairn review <id>` — never
`sync --push`, which commits only `build/`.

Every write reloads the page, since the server has just regenerated `build/`.
The view rides along in the URL — filters, search (`?q=`), fill, folded lanes,
the needs-you lens, isolate, pan and zoom, and the open node — and the result
message is shown again for a few seconds after the reload. Opening a node pans
the map only if the node is out of sight.

**`build/graph.html` still works with the server off**, which is what makes the
process an enhancement rather than a dependency. Open the file directly and the
panel is the read-only page it always was, composing a command for the clipboard.
The write controls are not hidden with CSS — they are never rendered, because
`/api/health` did not answer.

Security is three rules and no configuration, which is all a writer on the machine
you are already sitting at should need:

- it binds `127.0.0.1`, and that is not configurable — the moment this is
  reachable from another machine it needs auth and a review surface, and that is
  the webapp, not this
- it sends **no CORS headers, ever**, and serves the page itself so that writes
  are same-origin. A `file://` page has the opaque origin `null`; allowing that
  would mean allowing every sandboxed iframe on the web that can claim the same
- it checks the `Host:` header, because binding to loopback does not stop DNS
  rebinding — the packets really do arrive on loopback, and the header is what
  still names the attacker

The design rationale is in `2026-08-27-cairn-living-view`. Meeting notes still arrive through
`cairn import_note`, since they are a file rather than a node.

### Chat in the map

With `cairn serve` running, the map can also take a question — "what did we
already try on solvation?", "draft the follow-up to this dead end". Each message
runs one turn of **your own coding CLI** as a subprocess: Claude Code
(`claude -p`) or the OpenAI Codex CLI (`codex exec`), whichever is on `PATH`.
There is no API key in Cairn and no hosted service. The CLI runs signed in as
whoever is at the machine, so a collaborator signs into Claude Code or Codex
themselves, once, in a terminal (`claude`, or `codex login`).
`/api/health` reports which CLIs it found.

The model works in the graph root and writes the way everything else does,
**only through `bin/cairn`**. For Claude Code that is enforced: Bash is
allowlisted to the `bin/cairn` prefix in `dontAsk` mode, so anything else is
refused without a prompt. The subcommands that are a human's act are denied
outright: `review` (it would mark the chat's own draft as read), `edit`,
`discard`, `policy` and `sync`. For Codex, the guard is the `workspace-write` sandbox:
writes stay inside the graph, `.git` is read-only, and approvals are off. So
Codex cannot commit at all. Either way, **a node the chat creates is a draft**:
it sits uncommitted, the answer names the file, and you read it in the panel
before it is committed. Design decision 6 holds with a model in the loop.

In the map it is a drawer under the canvas, beside the panel. `chat` in the
header or `k` opens it. It has a select of the CLIs it found, a transcript, and
a box where Enter sends and Shift+Enter starts a new line. It also has **stop**
and **new conversation**. Each message carries the open node, if there is one.
The answer streams in as it arrives. Each command the CLI ran shows as a grey
line (`▸ cairn standup --project polyid`, marked if it was denied), errors show
in red, and `[[node-id]]` references become links that open the node.
Conversations resume by session id, which the page keeps per CLI for the tab.
A reload, which every write triggers, continues the same conversation with the
drawer open and the last 50 messages in place. **new conversation** forgets it.
**stop** ends the request, and the server ends the CLI turn.

The turn ends with a line that says whether `build/` was regenerated. The
server rebuilds after every clean turn, so the page compares the new build with
the one it shows. It reloads, keeping the view, only when the graph actually
changed, and then says "the chat wrote to the graph — reloaded". A node the chat
drafted then shows the hollow not-committed dot until you review it.

What each CLI emits, and what was verified about it, is in
[docs/chat-backends.md](docs/chat-backends.md).

`cairn serve --no-chat` switches it off: `/api/health` reports `chat: {}`,
`/api/chat` refuses, and the map draws no chat control at all. Neither does the
`file://` copy or a page from any other static server.

## Design decisions

These are settled. See `docs/schema.md` for the field reference and `CLAUDE.md`
for the conventions the agent follows.

1. **Separate repo.** One graph spans all projects; nodes carry `project:`.
   This is what makes the laptop/HPC split tractable. The tool is a repo of its
   own too, so it can be shared without anyone's record.
2. **Reference commits, never branches.** Branches get merged and deleted, and
   the most valuable nodes here are the dead ends git is designed to garbage
   collect.
3. **One file per node, append-only.** Never delete a node; change its status.
   Files never move; `id` is permanent.
4. **Tiny schema.** Every optional field is a field that stops getting filled in.
5. **Status is an event log.** `history:` gives the time axis for free, which
   is what makes replay and the weekly digest work.
6. **Nothing enters unread without saying so.** Under `commit_mode: ask` the
   agent drafts, shows, then commits; under `auto` it commits only nodes about
   work it did, says so, and `cairn review --list` keeps them visible as unread.
   An auto-populated graph nobody *can tell* is unread is the failure this
   project exists to avoid — the policy changes who presses commit, not whether a
   reader can see what a human has weighed in on. Unprompted capture goes to
   `inbox/` instead.
7. **Capture ≠ structure.** `inbox/` accepts unstructured junk from anywhere;
   a separate triage pass turns junk into nodes. Never require filing at
   capture time — that's how capture dies.
8. **Artifacts stay where they are.** Nodes reference big outputs by
   `host:/path`. The graph stays small forever, so it syncs instantly and diffs
   stay readable.
9. **One graph, many writers, synced through git.** No auth, no real-time
   editing, no discussion threads, and no server the graph depends on — `cairn
   serve` is an optional localhost writer the map degrades gracefully without,
   never a deployment. Multi-writer was never the thing being refused. One file
   per node, append-only and never renamed, is what makes two people
   non-colliding, and `git log --diff-filter=A` already
   answers "whose node is this?" without a field for it. Add collaborators to
   the repo; don't shard the graph per project, or you lose the cross-project
   edges that are the hardest part to reconstruct.

## Two machines, or two people

Clone the tool and the graph on every machine you work on — the graph from one
shared remote — and run `cairn onboard` on each. Neither machine ever needs to
reach the other: nodes reference code by `repo` + `commit` and outputs by
`host:/path`.

```sh
cairn sync                     # pull, then say what still needs you
cairn sync --push              # regenerate build/, commit build/, push
cairn sync --check             # no network; local state only
```

The friction here was never storage (asked and refuted in
`2026-08-21-cairn-database-question`). It is a **habit gap**: forgetting to pull
before working, and — the expensive one — forgetting to push after.

So `sync` automates the half that is safe to automate and *reports* the half
that isn't. **It never commits a node**, whatever the commit policy: it cannot
tell a node an agent meant to commit from a stray draft, so `--push` commits
only `build/`, which is generated. Uncommitted nodes get named instead, because a
node file that has never been committed is almost always a draft nobody has read
yet. And if a rebase dies half-way and leaves git stuck, `sync` says so and names
the stash holding your work rather than reporting that nothing needs you.

Conflicts are near-impossible: nodes are separate append-only files. The only
shared-file contention is `build/`, and `sync` resolves that itself — when a
rebase stops *only* on `build/`, it regenerates rather than merging, and
continues. A conflict anywhere else is left for a human, because anywhere else it
means something interesting happened.

With `install_context` in place, the pull happens on its own at session start
and the "you have unpushed work" warning at session end. Neither replaces
`sync --push`; they make forgetting visible.

**The same mechanism carries a second person.** A collaborator is a
collaborator on the graph's git remote and nothing more — with their own commit
policy if they like, since the mode is policy over identical data. The one
genuine collision is two people creating the same id on the same day; git
catches that as a real conflict rather than losing one of them.

## Status

**215 nodes across 19 projects** as of 2026-10-14, 27 of them refutations, with
66 typed relations — zero validation errors. The first 61 were backfilled from
five weeks of Claude sessions; the rest were written as the work happened.

The next step is deliberately *not* more features. The failure mode for a
project like this is building the whole system and then not using it.

What the first backfill found — the silent YAML corruption, the interpreter
probe that tested the wrong thing, and the argument that produced `relates` —
is written up on the site: **[what the backfill found][site-learned]** and
**[the comma that ate seventeen nodes][site-comma]**.

`refs:` is deliberately thin. The sessions cite plenty of papers, but a DOI
recalled rather than resolved is worse than no DOI — populate the papers
registry with verified metadata rather than backfilling it from memory.

[site-learned]: https://jlaw9.github.io/cairn/design.html#learned
[site-comma]: https://jlaw9.github.io/cairn/blog/2026-08-05-the-comma.html
