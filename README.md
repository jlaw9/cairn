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

## Quick start

```sh
pip install pyyaml
make setup        # install the pre-commit validation hook (once per clone)

scripts/new_node.py experiment "COSMO-RS baseline on the 40-solvent set" \
  --project prekd --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

make build        # regenerate build/graph.html and build/graph.md
open build/graph.html
```

From inside a project repo, `/log` at the end of a session does all of that for
you: it reads the git log, drafts the node, asks only for the interpretation it
can't infer, and commits.

## What's here

```
nodes/       the graph — one file per node, append-only, never deleted
papers/      one page per cited paper, keyed by DOI
meetings/    raw meeting notes
inbox/       unstructured capture awaiting triage
assets/      small figures only
build/       generated: graph.html (self-contained) and graph.md (Mermaid)
scripts/     lib.py, validate.py, build_graph.py, new_node.py
docs/        schema.md and worked examples
```

`make validate` · `make build` · `make test`

## The map

`build/graph.html` is a single self-contained file — no server, no CDN, no
build step beyond `make build`. Open it from disk.

Layout is **time-ordered**, not force-directed: x is the creation date, y is a
project lane. Research history has a real time axis and a force layout throws
it away; it also means node positions are stable between builds, so the map
stays memorable.

- colour = status, shape = type, filter by project / type / status
- click a node → rendered body, commit link, parents, children, paper backlinks
- **the "as of" slider replays history** from the `history` log — drag it back
  and the graph shows what was known then, with the statuses of that date

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
6. **Capture ≠ structure.** `inbox/` accepts unstructured junk from anywhere;
   a separate triage pass turns junk into nodes. Never require filing at
   capture time — that's how capture dies.
7. **Artifacts stay where they are.** Nodes reference big outputs by
   `host:/path`. The repo stays small forever, so it syncs instantly and diffs
   stay readable.

## Two machines

Clone on both the laptop and kestrel, synced through this remote. Neither
machine ever needs to reach the other: nodes reference code by `repo` +
`commit` and outputs by `host:/path`.

`git pull --rebase` at the start of a session, commit and push at the end.
Conflicts are near-impossible — nodes are separate append-only files. The only
shared-file contention is `build/`, which should be regenerated, never merged.

## Status

Phase 0 and Phase 1 tooling are built. **Next step is 20 real backfilled nodes,
then two weeks of living with it** — before `/weekly`, `/capture`, `/triage`,
the papers registry, or `/review`. The failure mode for this project is
building the whole system and then not using it.
