# Cairn — conventions for the agent

**This repo is the tool.** The graph — the actual record of experiments, dead
ends, open threads, papers, milestones — lives in a separate repo, one per
person, found through `$CAIRN_ROOT`. This repo holds the code that reads and
writes it, the schema, and these conventions.

Two paths, and confusing them is the first thing that goes wrong:

| variable | means | holds |
|---|---|---|
| `$CAIRN_PATH` | this repo, the tool | `bin/`, `scripts/`, `skills/`, `docs/` |
| `$CAIRN_ROOT` | a graph | `nodes/`, `papers/`, `meetings/`, `inbox/`, `build/` |

A clone from before the split — `nodes/` sitting beside `scripts/` — still works
unchanged: `CAIRN_ROOT` falls back to this repo when it is unset. Everything
below is about the graph, whichever repo it is in.

The graph exists so that "did we already try this, and what happened?" has an
answer six months from now.

**The one rule that overrides every other rule in this file: capture wins.**
Every previous attempt at this kind of system died on capture cost, not on
missing features. If a choice ever trades reliable capture for a nicer schema,
take the capture. A node with a messy body beats a missing node, every time. A
graph at 60% coverage is worse than no graph, because you can't trust a missing
node to mean "not tried."

## Session protocol

`bin/cairn sync` at the start, `bin/cairn sync --push` at the end. That is
`git pull --rebase --autostash` and then regenerate-commit-`build/`-and-push,
plus a report of what still needs a human.

**`sync` never commits a node**, and never will. Design decision 6 is that
nothing enters the graph unread *without saying so*: under `commit_mode: ask`
nothing is committed unreviewed, and under `auto` an agent commits only a node
it wrote about work it did, right then, and says so. `sync` can tell neither
apart from a stray draft, so it commits only `build/`, which is generated. Nodes
stay exactly where they are, uncommitted, and `sync` names them — a node file
that has never been committed is almost always a draft nobody has read.

Merge conflicts are near-impossible by design — nodes are separate append-only
files. The only shared-file contention is generated output under `build/`, and
`sync` resolves that itself the way this file already prescribed: when a rebase
stops *only* on `build/`, it regenerates rather than merging, and continues. A
conflict anywhere else is left for a human, because anywhere else it means
something interesting happened.

On a machine that has run `bin/cairn install_context`, the pull half happens on
its own — a `SessionStart` hook runs `sync` (throttled) and injects the graph's
state into the session, and a `SessionEnd` hook says what is unpushed. Neither
replaces running `sync --push` yourself; they make forgetting visible.

## What goes where

In the **graph** repo (`$CAIRN_ROOT`):

| path | contents |
|---|---|
| `nodes/<id>.md` | the graph. One file per node, never deleted, never moved |
| `papers/<doi-slug>.md` | one page per cited paper, CrossRef-verified metadata |
| `datasets/<key>.md` | one page per dataset nodes reference via `data:` — sha256, host:path, tier |
| `meetings/<date>-<who>.md` | meeting notes, raw |
| `inbox/<date>-<hhmm>.md` | unstructured capture, awaiting triage |
| `assets/` | small figures only — one per node, for the HTML thumbnail |
| `build/` | generated. Never hand-edit |
| `CLAUDE.md` | the graph's own conventions, including its one setting: `commit_mode: ask\|auto` |

In **this** repo (`$CAIRN_PATH`):

| path | contents |
|---|---|
| `scripts/` | the tooling |
| `bin/cairn` | the dispatcher. Run everything through it |
| `skills/<name>/SKILL.md` | path-addressed skills, so agents in *other* repos can use the graph |
| `example/` | generated: a scrubbed copy of the `cairn` subgraph, so the tool ships with a real graph |
| `docs/github.md` | tasks as GitHub Issues: what works, what's unverified |
| `docs/literature.md` | corpora of thousands of papers: clusters, and what earns a node |
| `docs/openviking.md` | the optional OpenViking seam: what crosses it, in which direction |

Nothing heavy ever enters this repo. Big outputs are referenced by
`host:/path`, code by `repo` + `commit`. The repo stays text-only and small
forever, so it syncs instantly and diffs stay readable.

## Node rules

Read `docs/schema.md` for the field-by-field reference. The rules that matter
most in practice:

1. **`id` is permanent and equals the filename stem.** Format
   `YYYY-MM-DD-<lowercase-slug>`. Never rename a file, never reuse an id.
2. **Never delete a node.** Change its status. Dead ends are the most valuable
   nodes here — they're the ones ordinary git workflow is designed to garbage
   collect, and they're what make a methods section writable.
3. **Reference commits, never branches.** Branches get merged and deleted;
   a SHA is forever. The validator rejects anything that isn't a SHA.
4. **`status` and `history` move together.** Never hand-edit `status:`. Use
   `bin/cairn new_node --update` (or `lib.Node.set_status`), which appends a
   history entry and moves `status`/`updated` in lockstep. The validator will
   catch you if you don't; that check exists because this is the single most
   likely way the graph rots.
5. **Resist new fields.** Every optional field is a field that stops getting
   filled in. Adding one is a real decision — put it in `lib.TYPES` and
   `docs/schema.md`, or don't add it.
6. **`parents` is lineage; `relates` is meaning.** When one result contradicts,
   supersedes, supports or resolves another, say so with a typed relation and a
   one-line reason, rather than burying it in prose that only reads correctly
   from one of the two nodes. Four types, no more — see `docs/schema.md`.
   Relations can be added later without a status change:
   `bin/cairn new_node --update <id> --relate "contradicts:<other-id>:why"`.
7. **Refer to another node in prose as `[[<node-id>]]`.** It renders as a link
   titled with the target's node title, and `validate` warns if the target
   doesn't exist. Use it for the soft connections that aren't lineage and aren't
   one of the four relation types — "this builds on the wD-MPNN core", "see the
   schema task first". A cross-project dependency goes here, in the body, rather
   than in `parents`.

## Writing nodes

Create with the script rather than hand-assembling YAML:

```sh
bin/cairn new_node experiment "COSMO-RS baseline on the 40-solvent set" \
  --project prekd --parent 2026-07-20-prekd-scoping \
  --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

bin/cairn new_node --update 2026-08-02-prekd-cosmo-baseline \
  --status dead --note "solvation model wrong for ionics, MAE 1.4"
```

**Pass `--note` at creation too, not just on `--update`.** It becomes the first
history entry; without it the entry reads `created`, which throws away the one
sentence you had in hand at the moment you had it.

**`--body` writes the opening section** — `## Claim` for an experiment, its
analogue for the other types — instead of seeding it with the title. Use it
whenever you have the claim in hand, which for a `planned` experiment is the
whole point: a claim written before the result is a pre-registration, written
after it, it is a story.

**`--project` is checked against the keys already in the graph.** An unrecognised
key is refused with the near-matches listed, because it is the only field whose
typo validates cleanly and it silently splits a project in two. Starting a
genuinely new project takes `--new-project` — ask the user before using it
rather than assuming, since the usual cause is a typo or a key that already exists under
a different name.

**Use `--status planned` for an experiment that hasn't started.** `running` means
running. Creating with no `--status` still gives `running`, which is what you want
when logging work that already happened.

Body convention for experiments — `## Claim` / `## What I did` / `## Result` /
`## Next`. **Don't enforce it.** Prompting for structure at capture time is
how capture dies.

**Correct an existing node with `bin/cairn edit`, never by hand-editing YAML.**
It replaces the body (`--body FILE`, or `-` for stdin), sets or `--clear`s a
whitelisted scalar the node's type carries (`title`, `project`, `due`, `date`,
`venue`, `url`, `repo`, `commit`, `host`, `origin`, `source`), and adds or drops
one `--parent`, `--ref`, `--data`, `--artifact` or `--relate` at a time. It refuses, by
name, `id`, `type`, `created`, `status`, `updated` and `history` — the last three
move only together, through `new_node --update`. **It does not touch `updated` or
`history`**: an edit is a correction, not a claim about the state of the work, so
moving them would put a status change on the replay slider that never happened —
the same reason `cairn note` leaves them alone. The edited node is validated in
memory first, so a parent that closes a cycle or a relation to a missing node is
refused with nothing written. It commits like `note` does (with a review trailer,
since whoever corrects a node has just read it); an agent drafting a correction
for the user to look at passes `--no-commit`, and `--dry-run` shows the diff.

### `## Notes` is where a human reacts to a node

`bin/cairn note <id> "..."` appends a dated bullet under `## Notes`:

```
- **2026-08-26** (jlaw) the spread looks bimodal — does it track the seed?
```

Read them back with `cairn note --list`; `standup`, `digest` and the map all
surface them. Three things about this are deliberate and worth not undoing:

- **It is a body edit, not a status change.** `status`, `updated` and `history`
  do not move, because a note is not a claim about the state of the work. If it
  moved `updated`, the replay slider would show a status change that never
  happened.
- **No new field.** The line carries its own date, so a note stays findable by
  reading the body — the same way `## Next` is already read. A `notes:` list in
  the frontmatter would be a fifth thing to maintain, against rule 5.
- **"Unanswered" is derived.** A note dated at or after the node's last history
  entry is one no later work has responded to; once the thread moves, the note
  stops being reported. That is what keeps it from becoming a nag list.

A note in the user's voice is theirs to write — `cairn note` commits it, because
a sentence they just typed is by definition one they have seen. If *you* are
recording an observation of your own, that is a history note on a status change
or an `inbox/` capture, not a `## Notes` bullet in their name.

### A literature finding is an experiment

Many projects open with a literature review, and there is no separate node type
for one — an `experiment` already fits, and reaching for a new type or a new
field here is a mistake. A literature finding has a claim, a method and a result;
`repo`, `commit`, `host` and `artifacts` are optional, so nothing about the type
assumes code. The corpus is the instrument, and `status: dead` on a claim the
literature refuted means the same thing downstream as a job that failed.

What to get right:

- **Write the claim the finding settles, not a summary of what you read.** "Can a
  reported final Tg be fitted as Tgp?" with `status: dead` is a node someone
  finds by asking that question. "Tg literature review" is not.
- **One claim per node.** A review touching eight things is eight nodes, or one
  `direction` with eight open questions.
- **`--ref` the DOIs and register the papers** with `bin/cairn add_paper` / `/paper`, so
  the evidence resolves. Never write a DOI from memory.
- **`## What I did` is the corpus and the filter** — how many papers, from where,
  what was excluded. That is this node's methods section, and it's what tells a
  reader later how much weight the result carries.

A constraint discovered this way usually generates its own follow-up: an
experiment to test whether it holds on our own material, a task for the schema
change it forces. Make those children of the finding rather than siblings — the
lineage is the argument.

The `## Result` section is the one thing worth asking the user about, because
it's the interpretation and you usually can't infer it from a diff. Everything else
— what changed, which commit, which host — read it out of the git log yourself.

## Drafting rules

**Follow the graph's commit policy.** It is one line in the graph repo's
`CLAUDE.md` — `commit_mode: ask` or `commit_mode: auto` — stated in the
session-start context and printed by `bin/cairn policy`:

- **`ask`** (the default): draft the node, show it, and commit only after the
  user confirms. Never commit a node they haven't seen.
- **`auto`**: commit the node you wrote about work you did, right away, and say
  what you committed — the user edits afterward. Still never commit a node about
  work you did not do, never hand-edit `status:`, and never write in the user's
  voice. `cairn review --list` is how an unread node stays visible rather than
  absent; that derivation is what makes `auto` safe to offer at all.

An auto-populated graph nobody *can tell* is unread is the failure mode this
project exists to avoid — the policy changes who presses commit, not whether a
reader can see what a human has weighed in on.

A draft nobody wants is the other outcome of reading one, and `bin/cairn
discard <id>` is how to say so: it deletes a node file git has never seen (and
its untracked asset). It refuses anything committed or modified, a non-git
graph, and a node another node lists in `parents` or `relates` — so it is not
an exception to "never delete a node", only to a draft that never became one.

If you're tempted to write a node without review — for instance from a Stop
hook — write to `inbox/` instead and let `/triage` handle it later. `inbox/`
is explicitly a junk drawer: unstructured text, no schema, no validation.
That's what makes it safe to write to unprompted.

Use `bin/cairn capture` for that rather than writing the file yourself: it
records host, cwd, repo and commit, which is the context you can't reconstruct
weeks later and can't infer from the text. It deliberately does not commit —
committing runs the validation hook, and a capture that can fail because of
schema drift somewhere else is not a capture.

For a file that already exists elsewhere — a meeting's org buffer, a pasted
mail, notes someone sent — use `bin/cairn import_note`. With `--meeting --who
<name>` it writes two files on purpose: the record lands in
`meetings/<date>-<who>.md`, and a one-line pointer lands in `inbox/`. The record
is permanent; the *obligation to read it* is the queue item `/triage` consumes.
Content is verbatim, always — org markup in a `.md` file is not a problem to be
solved.

## Reading the graph before you add to it

`bin/cairn standup` before proposing work, and `--project <key>` before working
in one. The "already settled" section of the resume packet is the point: a `dead`
node there is a claim someone refuted, with the reason attached, and citing it
beats re-running it. Treat a missing node as "not tried" only where the project
is well covered — in a thin project it means the graph doesn't know yet, and
that's the honest thing to say.

`standup` ranks by what needs attention; `digest` is chronological. Don't
substitute one for the other. Neither writes anything.

`build/report.md` (regenerated by `make build`) is the third view and the one to
read before trusting a *gap*. Its coverage table gives the two numbers that make
the "missing node = not tried" rule usable: how many nodes a project has, and
what share of them were committed within a week of the work they describe. A
project at 0% is a reconstruction, and a reconstruction is biased toward what
worked — so a gap there means the graph doesn't know, not that nobody tried.

## Cross-machine

The usual shape is a laptop and an HPC login node, both cloning the graph from
the same remote. Neither machine needs to reach the other: nodes reference
project code by `repo` + `commit` and heavy outputs by `host:/path`, so a node
written on the cluster is fully readable from the laptop without resolving
anything.

## When a command fails

Run `make doctor` before debugging anything else. It reports which install step
is missing — interpreter, pre-commit hook, slash commands, `CAIRN_PATH`,
`CAIRN_ROOT` — and it runs without a working Python, because the interpreter is
the most common thing to be wrong. Each of those fails in a different way and
none of the failures names itself.

**"0 nodes" is never a real answer.** If a read reports an empty graph, the cause
is `CAIRN_ROOT` pointing somewhere without a `nodes/`, not an empty graph. Every
read path here treats absence as evidence, so `load_nodes` refuses that case
instead of returning nothing — but if you see a zero, check the path first.

**Run everything through `bin/cairn`, never `scripts/*.py` directly.** The
dispatcher is `/bin/sh`, so it picks the interpreter via `find_python.sh` — the
same one `make` and the hook use. Calling a script directly hands the choice to
whatever `#!/usr/bin/env python3` resolves to, and on an HPC login node that is
routinely a Python too old to *compile* the file. A re-exec inside the script
cannot rescue that: compilation precedes execution, so the SyntaxError lands
before any shim can run.

"cairn: no usable Python found" therefore means what it says — no interpreter on
this machine has Python >= 3.7 with PyYAML. Don't work around it by invoking a
specific python by hand; install PyYAML or set `CAIRN_PYTHON`, so `make`, the
hook and `bin/cairn` all agree with you.

## Before committing

`make validate` runs automatically via the pre-commit hook
(`scripts/install_hooks.sh`, once per clone). Errors block the commit.
Warnings don't, but they're worth reading — they're mostly "this field will
make the graph less useful later."

Silent schema drift is how this rots. Don't `--no-verify` past a validation
error without fixing it afterwards.

## Not in scope

Not an experiment tracker — W&B/MLflow own metrics and curves, the graph links
out to them. Not a replacement for project repos. Not a general task manager,
only research commitments. No auth, no real-time editing, no discussion
threads. A static HTML file in a git repo.

**`cairn serve` is the one server, and it is optional.** A localhost writer that
lets the map leave a note, move a status, or create a node — including in a
project the graph has never seen — always by shelling out to `bin/cairn`, never
by touching a file itself, so the node stays the only copy and `check_project`
still guards the key. Two rules hold it in scope: `build/graph.html` must stay fully usable with
the server off, and nothing in the view may hand-edit frontmatter. Anything
needing auth, or reachability from the other machine, is the webapp
([[2026-08-05-cairn-webapp]]) and a different decision. Its chat runs the
user's own Claude Code or Codex CLI as a subprocess, signed in as them. It is
never a hosted service and never holds an API key, and the model writes only
through `bin/cairn`, like the panel.

**One graph, many writers, synced through git.** This is in scope and always was:
one file per node, append-only, never renamed, means two people cannot collide,
and `git log --diff-filter=A` already says who wrote which node without a field
for it. Don't add an `author:` — derive it. See
[[2026-08-05-cairn-collaboration]] for what stays refused and why.
