---
name: cairn-log
description: Record what a work session produced as a node in Cairn's research graph — a result, a failed approach, a literature finding, or a commitment with a deadline. Use at the end of a session that settled something, or when asked to log, record, or write up work. Requires the user present to confirm the interpretation; if they are not, use cairn-capture instead.
---

# Log a session to Cairn

Cairn is a git-backed graph of research activity: one markdown file per node,
append-only, never deleted. This skill writes a node for work that just happened.

**Prerequisite: the user is present.** A node asserts a finding, and an
unreviewed assertion is exactly the failure Cairn exists to prevent — the graph's
value is that everything in it has been read by a human. If nobody can confirm
the interpretation, use `cairn-capture` and let triage handle it.

`$CAIRN_PATH` below is the Cairn clone; on a shared filesystem,
`/kfs2/projects/bpms/jlaw/tools/Cairn-graph`. Always invoke through
`bin/cairn`, never `scripts/*.py` — the dispatcher picks a Python that can
actually run the scripts, and on an HPC login node the default `python3` often
cannot even compile them.

## 1. Read the work; don't ask about it

From the **project repo** you are in — not the graph repo:

```sh
git log --oneline -20 && git status
git rev-parse HEAD          # the SHA to record
git remote get-url origin   # the repo field
hostname -s
```

A node pointing at a dirty tree is a lie. If the tree is dirty, say so and ask
whether to commit first.

Reference **commits, never branches.** The validator rejects anything that isn't
a SHA, because branches get merged and deleted and the most valuable nodes here
are the ones ordinary git workflow garbage-collects.

## 2. Decide: new node, or status change?

**Prefer updating.** A session continuing yesterday's experiment is a new history
entry, not a new node. Check what's already open:

```sh
$CAIRN_PATH/bin/cairn standup --project <key>
```

Then either:

```sh
$CAIRN_PATH/bin/cairn new_node --update <id> --status <status> \
  --note "<one line: what changed and why>" --commit <sha>

$CAIRN_PATH/bin/cairn new_node experiment "<title>" --project <key> \
  --parent <id> --repo <url> --commit <sha> --host <host> \
  --note "<one line>"
```

Rules that bite if ignored:

- **`--project` is checked against keys already in the graph.** It is the one
  field whose typo validates cleanly, so a wrong key silently splits a project in
  two. An unrecognised key is refused with near-matches listed. Starting a
  genuinely new project needs `--new-project` — **ask the user first**; the usual
  cause is a typo or a key that exists under another name.
- **Pass `--note` at creation, not only on updates.** Without it the first
  history entry reads `created`, which throws away the one sentence you had.
- **Never hand-edit `status:`.** Use `--update`, which moves `status`, `updated`
  and `history` in lockstep. The validator catches drift; this is the most likely
  way the graph rots.
- **`--status planned` for an experiment that hasn't started.** `running` means
  running. A claim written before the result is a pre-registration; written
  after, it's a story.
- `--parent` is lineage: what this grew out of. Guess if it's obvious, ask if not.

## 3. Fill the body

Convention is `## Claim` / `## What I did` / `## Result` / `## Next`. Write
Claim, What I did and Next yourself — the diff and the commit messages are the
evidence. Write `## Next` even when it feels obvious: it is what `standup` reads
back, and it is what makes the project resumable weeks later.

**`## Result` is the one thing to ask about.** It's the interpretation and it
isn't in the diff. Ask one focused question, not a form. If the answer is a
sentence, that sentence is the section — don't inflate it.

**If it failed, set `--status dead` and write down why.** Dead ends are the
highest-value nodes here. Do not soften them to `parked`: parked means "paused,
will resume", dead means "we learned this doesn't work."

Add a typed relation if this bears on another node — no status change needed:

```sh
$CAIRN_PATH/bin/cairn new_node --update <id> \
  --relate "contradicts:<other-id>:<why in one line>"
```

Four types only: `supports`, `contradicts`, `supersedes`, `resolves`. Use one
when a result bears on another, rather than burying it in prose that only reads
correctly from one end. In a body, refer to another node as `[[<node-id>]]`.

## 4. A literature finding is an experiment

No separate type, and reaching for one is a mistake: a finding has a claim, a
method and a result, and `repo`/`commit`/`host` are optional. Write **the claim
it settles**, not a summary of what you read — `status: dead` on a claim the
literature refuted means the same downstream as a job that failed. One claim per
node. `--ref <doi>` the evidence and register it with
`$CAIRN_PATH/bin/cairn add_paper <doi>`; never write a DOI from memory.

## 5. Show, then commit

Print the node. **Wait for confirmation.** Then:

```sh
cd $CAIRN_PATH && make build && git add -A \
  && git commit -m "log: <node id>" && git push
```

The pre-commit hook validates. If it fails, fix the node — do not `--no-verify`
past a validation error.

## 6. Make it visible from the other machine

A committed node is still invisible from the laptop until it is pushed.

```sh
$CAIRN_PATH/bin/cairn sync --push
```

That regenerates `build/`, commits **only** `build/`, and pushes. It never
commits a node — so if it reports uncommitted drafts, those are yours to show
Jeff and commit, not for it to sweep in.

## Do not

- **Do not write a `## Notes` bullet.** That section is where *Jeff* reacts to a
  node, and `cairn note` stamps his handle on it. Your observations go in the
  history note of the status change, where they are correctly attributed.

- Do not commit a node the user hasn't seen.
- Do not copy large outputs in. Reference them as `host:/path` in `artifacts`.
  One small summary figure may go in `$CAIRN_PATH/assets/`. One.
- Do not add schema fields. Every optional field is one that stops getting
  filled in; adding one is a real decision made in `lib.TYPES` and
  `docs/schema.md`, not in passing.
- Do not delete or rename a node. Ever. Change its status.
- Do not log a commitment as an experiment. A deadline with no scientific claim
  is a `task` with a `--due`.
