# Installing and using Cairn

For someone who has never used Cairn, on any machine. Ten minutes, one
dependency, and two repos to keep straight:

| variable | means | holds |
|---|---|---|
| `$CAIRN_PATH` | the **tool** — this repo | `bin/`, `scripts/`, `skills/`, `docs/` |
| `$CAIRN_ROOT` | your **graph** — its own repo | `nodes/`, `papers/`, `meetings/`, `inbox/`, `build/` |

The tool can be shared without shipping anyone's research record, and one tool
can serve several graphs. Confusing the two is the first thing that goes wrong,
which is why every command below says which one it is talking to.

If a command fails at any point, run `cairn doctor` before debugging anything
else. It reports which install step is missing, and it runs without a working
Python — which matters, because the interpreter is the most common thing to be
wrong and none of the failures names itself.

---

## 1. Clone the tool

```sh
git clone https://github.com/jlaw9/cairn ~/cairn
cd ~/cairn
```

`~/cairn` is a suggestion; anywhere works.

## 2. Get a Python that can run it

Cairn needs **Python >= 3.7 with PyYAML**, and nothing else. Ever. That is the
whole dependency list, and it is deliberate: this has to run on a laptop and on
a cluster login node without a virtualenv dance.

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

## 3. Onboard this machine

```sh
bin/cairn onboard
```

Three questions, each of whose answer becomes a fact on disk that `doctor` reads
back — there is no config file:

1. **Where is your graph?** It is created if it does not exist (`cairn init`):
   the directories, a `.gitignore`, a `CLAUDE.md` with the conventions, `git
   init`, and the validation hook. Keep it **outside every project repo** — one
   graph spans all your projects, and `init` refuses to nest one inside another
   git repo for exactly that reason.
2. **Commit policy.** `ask` (the default): an agent drafts a node, shows it, and
   commits only after you confirm — nothing enters the graph unread. `auto`: an
   agent commits the nodes it writes about work it did and tells you; you edit
   afterward, and `cairn review --list` shows what nobody has read yet. It is one
   line in the graph's `CLAUDE.md`; `cairn policy auto|ask` changes it later.
3. **Which sessions see the graph?** `machine`: every Claude Code session on this
   machine (a `SessionStart` hook under `~/.claude`, the slash commands, a block
   in `~/.claude/CLAUDE.md`). `project`: only sessions started in one directory
   (the same three, inside that project, with the hook in
   `.claude/settings.local.json` so your absolute paths never reach a
   collaborator through git).

If [OpenViking](openviking.md) is installed, a fourth, optional offer: register
the graph with it. Cairn is complete without it.

Then export the two paths, and add them to your shell profile:

```sh
export CAIRN_PATH=$HOME/cairn               # the tool
export CAIRN_ROOT=$HOME/research-graph      # your graph
export PATH=$CAIRN_PATH/bin:$PATH           # optional: plain `cairn` anywhere
```

Both are needed. The slash commands and skills reach the tool through
`CAIRN_PATH`; the tool finds the graph through `CAIRN_ROOT`, and without it
every read reports an empty graph — which this tool refuses to do, loudly,
because an empty graph reads as "nothing was ever tried". The `PATH` line is
convenience only.

```sh
cairn doctor                                 # confirm every step took
```

Every question has a flag, so an agent can run it: `cairn onboard --graph
~/research-graph --commit-mode auto --scope project=. --yes`.

**Doing it by hand instead** — the same facts, one command each:

```sh
cairn init ~/research-graph --commit-mode ask
cairn install_context --apply                # or: --project <path> --apply
cairn install_hooks ~/research-graph         # only if you cloned a graph rather than init'd it
```

**Do this on every machine you work on.** Laptop and cluster both; the graph is
one remote, cloned on each.

## 4. Where nodes live, and what a project repo gets instead

This is the question every newcomer asks, and `onboard` deliberately does not
ask it back: **nodes stay in the one graph.** A record scattered across project
repos loses the cross-project edges — the hardest part to reconstruct and the
most valuable thing in it — and makes a permissions boundary look identical to
a gap in the record.

What a project repo gets is a **generated view**:

```sh
cairn export --project <key> --dest <repo>/docs/research
```

A filtered, self-contained `graph.html`, a Mermaid fallback that renders on
GitHub, and an index whose "already settled" section is the one that stops
repeated work. It is generated and says so; the graph stays authoritative.

The older, narrower route to making the conventions reachable still works and is
worth knowing about: one line in a project repo's own `CLAUDE.md`.

```markdown
Research activity is recorded in Cairn. To capture a note, resume a project, or
log a session, read the matching skill under `$CAIRN_PATH/skills/`.
```

Three skills become reachable — `cairn-capture`, `cairn-resume`, `cairn-log` —
and none costs anything until used. Do not copy them into project repos: a copy
drifts, silently. See [`skills/README.md`](../skills/README.md).

---

## Using it: the daily shape

### Starting a session

```sh
cairn sync                        # pull, then say what still needs you
cairn standup                     # every project, most-needs-you first
cairn standup --project <key>     # the resume packet for one project
```

Where `onboard` wired the session hook, the `sync` half happens on its own — at
most every 30 minutes — and the graph's state, plus the commit policy in force,
is injected into the session. `cairn session_hook --dry-run` prints exactly what
a session is told.

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

A reaction to a node that already exists is a different thing, and has its own
command — it belongs *on* the node, not in a queue:

```sh
cairn note 2026-07-20-polyid-run-variance "the spread looks bimodal — seeds?"
cairn note polyid-run-variance    # a unique suffix is enough; opens $EDITOR
cairn note --list                 # every note, newest first
```

A file that already exists elsewhere — a meeting's org buffer, a pasted mail —
goes through `import_note`. With `--meeting` it writes the record to
`meetings/<date>-<who>.md` *and* a one-line pointer to `inbox/`, so the record is
permanent and the obligation to read it is a queue item:

```sh
cairn import_note ~/notes/2026-08-26-dave.org --meeting --who dave
```

Capture writes to `inbox/`, which has **no schema and no validation**. It never
refuses, never prompts, never asks which project. That is not laziness in the
design; it is the design. Every previous attempt at a system like this died on
capture cost, so anything that puts a question between you and a written note is
a bug. `--project` here is a *hint for triage*, not a validated key.

### Ending a session

From inside the project repo, `/log` in Claude Code: it reads the git log,
drafts the node, asks only for the interpretation it cannot infer, and — under
`ask` — shows it and waits; under `auto` — commits it and says so. Or by hand:

```sh
cairn new_node experiment "<the claim>" --project <key> --parent <id> \
  --repo $(git remote get-url origin) --commit $(git rev-parse HEAD) \
  --host $(hostname -s) --note "<one line>"
```

Then, in the graph repo:

```sh
cd $CAIRN_ROOT && git add nodes/<id>.md && git commit -m "log: <id>"
cairn sync --push                 # regenerate build/, commit build/, push
```

`sync --push` **never commits a node**, whatever the policy — it cannot tell a
deliberate draft from a stray one, so it names your uncommitted files instead of
sweeping them in.

### Weekly-ish

```sh
/triage                           # turn inbox notes into nodes, or discard them
cairn build && open $CAIRN_ROOT/build/graph.html
less $CAIRN_ROOT/build/report.md  # where to start, and how much to trust a gap
cairn review --list               # which claims nobody has read yet
```

Triage is the pass that pays for capture being free. Separating them is the whole
reason capture can stay cheap — and "this note went nowhere, delete it" is a
normal, correct outcome. Deleting an inbox file is fine; the never-delete rule is
about nodes.

---

## Two machines, or two people

Same problem, same answer: clone the graph from the same remote on each, run
`cairn onboard` on each, then `cairn sync` at the start of a session and
`cairn sync --push` at the end.

`sync` also resolves the one merge conflict this repo can produce. Nodes are
separate append-only files, so two writers don't collide; `build/` is one file
both machines rewrite. When a rebase stops *only* on `build/`, `sync` regenerates
rather than merging and carries on. A conflict anywhere else is left alone,
because anywhere else it means something interesting happened. And if a rebase
dies half-way and leaves git stuck, `sync` says so and names the stash holding
your work rather than reporting that nothing needs you.

Neither machine ever needs to reach the other. Nodes reference code by `repo` +
`commit` and heavy outputs by `host:/path`, so a node written on a cluster is
fully readable from a laptop without resolving anything.

A collaborator is a collaborator on the graph's git remote and nothing more.
Two people with different commit policies still hold one graph — the mode is
policy over identical data. Don't shard the graph per project: the cross-project
edges are the hardest part to reconstruct and the most valuable thing in it.

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
cairn onboard        set up this machine: graph, commit policy, which sessions see it
cairn init           create a graph repo; --commit-mode ask|auto
cairn policy         read or set the commit policy
cairn doctor         check the install
cairn standup        what to pick up today; --project for a resume packet
cairn digest         what changed, and what needs you
cairn capture        append a note to inbox/ — no schema, never refuses
cairn note           a dated note on a node's body; --list to read them back
cairn review         mark a node read; --list for what nobody has read
cairn import_note    a meeting or an outside file, verbatim, into the graph
cairn sync           pull; --push to regenerate build/ and push; --check for state
cairn new_node       create a node, or append a status change to one
cairn add_paper      DOI in, CrossRef-verified papers/ entry out
cairn add_dataset    register a dataset in datasets/, sha256-verified when it can be
cairn validate       check every node against the schema
cairn build          regenerate build/graph.html, graph.md and report.md
cairn report         build/report.md on its own; --project for one project
cairn export         one project's generated view, for that project's own repo
cairn mine_sessions  survey Claude Code transcripts (read-only)
cairn sync_issues    mirror open task nodes to GitHub Issues (docs/github.md)
cairn openviking     register the graph with an OpenViking server (docs/openviking.md)
cairn install_context wire this machine's sessions to the graph; --project for one
cairn install_hooks  enable validation on a graph repo you cloned rather than init'd
cairn session_hook   the hook payload itself; --dry-run to see it
```

`cairn <command> --help` for a command's own options. Slash commands: `/standup`,
`/digest`, `/capture`, `/log`, `/triage`, `/paper`.

`capture`, `sync`, `policy`, `onboard` and `openviking` work on a machine where
Cairn is otherwise broken: none imports PyYAML, and `bin/cairn` probes for an
interpreter without demanding it for them. Losing a thought — or being unable to
pull, or to set the machine up in the first place — because of a dependency
error is the failure they exist to prevent.
