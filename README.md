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
make python       # show which interpreter Cairn picked, if you're curious

scripts/new_node.py experiment "COSMO-RS baseline on the 40-solvent set" \
  --project prekd --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

make build        # regenerate build/graph.html and build/graph.md
open build/graph.html
```

From inside a project repo, `/log` at the end of a session does all of that for
you: it reads the git log, drafts the node, asks only for the interpretation it
can't infer, and commits.

Cairn needs **Python >= 3.7 with PyYAML**, and nothing else. `make` finds a
suitable interpreter itself (`scripts/find_python.sh`) rather than assuming
`python3` is one — on Kestrel the default `python3` is 3.6.8 *with* PyYAML while
`python3.9` has none, and picking either blindly fails. Override with
`export CAIRN_PYTHON=/path/to/python` if the search guesses wrong.

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
