# Cairn — conventions for the agent

This repo is a persistent record of research activity across all of Jeff's
projects: experiments, dead ends, open threads, conference ideas, tasks,
papers, milestones. It exists so that "did we already try this, and what
happened?" has an answer six months from now.

**The one rule that overrides every other rule in this file: capture wins.**
Every previous attempt at this kind of system died on capture cost, not on
missing features. If a choice ever trades reliable capture for a nicer schema,
take the capture. A node with a messy body beats a missing node, every time. A
graph at 60% coverage is worse than no graph, because you can't trust a missing
node to mean "not tried."

## Session protocol

At the start of a session in this repo: `git pull --rebase`.
At the end: `make build`, commit, push.

Merge conflicts are near-impossible by design — nodes are separate
append-only files. The only shared-file contention is generated output under
`build/`. Never merge those by hand; regenerate with `make build`.

## What goes where

| path | contents |
|---|---|
| `nodes/<id>.md` | the graph. One file per node, never deleted, never moved |
| `papers/<doi-slug>.md` | one page per cited paper, CrossRef-verified metadata |
| `meetings/<date>-<who>.md` | meeting notes, raw |
| `inbox/<date>-<hhmm>.md` | unstructured capture, awaiting triage |
| `assets/` | small figures only — one per node, for the HTML thumbnail |
| `build/` | generated. Never hand-edit |
| `scripts/` | the tooling |

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
   `scripts/new_node.py --update` (or `lib.Node.set_status`), which appends a
   history entry and moves `status`/`updated` in lockstep. The validator will
   catch you if you don't; that check exists because this is the single most
   likely way the graph rots.
5. **Resist new fields.** Every optional field is a field that stops getting
   filled in. Adding one is a real decision — put it in `lib.TYPES` and
   `docs/schema.md`, or don't add it.

## Writing nodes

Create with the script rather than hand-assembling YAML:

```sh
scripts/new_node.py experiment "COSMO-RS baseline on the 40-solvent set" \
  --project prekd --parent 2026-07-20-prekd-scoping \
  --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

scripts/new_node.py --update 2026-08-02-prekd-cosmo-baseline \
  --status dead --note "solvation model wrong for ionics, MAE 1.4"
```

Body convention for experiments — `## Claim` / `## What I did` / `## Result` /
`## Next`. **Don't enforce it.** Prompting for structure at capture time is
how capture dies.

The `## Result` section is the one thing worth asking Jeff about, because it's
the interpretation and you usually can't infer it from a diff. Everything else
— what changed, which commit, which host — read it out of the git log yourself.

## Drafting rules

**Never commit a node Jeff hasn't seen.** Draft it, show it, then commit. An
auto-populated graph nobody trusts is the exact failure mode this project
exists to avoid.

If you're tempted to write a node without review — for instance from a Stop
hook — write to `inbox/` instead and let `/triage` handle it later. `inbox/`
is explicitly a junk drawer: unstructured text, no schema, no validation.
That's what makes it safe to write to unprompted.

## Cross-machine

Jeff works on a laptop and on NLR's HPC (`kestrel`). Both clone this repo from
the same remote. Neither machine needs to reach the other: nodes reference
project code by `repo` + `commit` and heavy outputs by `host:/path`, so a node
written on kestrel is fully readable from the laptop without resolving
anything.

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
only research commitments. No server, no auth, no collaboration. A static HTML
file in a git repo.
