# Node schema

The schema is deliberately tiny. Every optional field is a field that stops
getting filled in; the ones below earned their place. The authoritative copy
of this table is `lib.TYPES` — if you change one, change both.

## Common frontmatter (every type)

```yaml
id: 2026-08-02-prekd-cosmo-baseline   # permanent; equals the filename stem
type: experiment                       # experiment|direction|seed|milestone|task
title: COSMO-RS baseline on the 40-solvent set
project: prekd
status: running                        # must be valid for the type, see below
created: 2026-08-02
updated: 2026-08-05                    # = date of the last history entry
parents: [2026-07-20-prekd-scoping]    # DAG edges; [] for roots
relates:                               # typed, non-DAG; see below
  - {to: 2026-06-25-prekd-scramble, type: contradicts, note: opposite sign, same control}
refs: [10.1021/acs.jced.3c00123]       # bare DOIs; any node type may cite
history:
  - {date: 2026-08-02, status: running, note: kicked off on kestrel}
  - {date: 2026-08-05, status: dead, note: solvation model wrong for ionics}
```

`id`, `type`, `title`, `project`, `status`, `created`, `updated` are required.
`history` must have at least the creation entry.

### Why both `status` and `history`

They're the same fact, and storing a fact twice invites drift. `history` is the
source of truth — it's what gives the time axis, the replay slider, and the
weekly digest for free. `status` is a cache of `history[-1].status`, kept
because it's what you actually grep for and what reads well in a diff.

The validator enforces `status == history[-1].status`. Use
`Node.set_status()`, which moves both plus `updated` atomically. Hand-editing
`status:` is the most likely way this graph rots.

## `parents` vs `relates`

Two edge sets, doing different jobs.

`parents` is **lineage**: what this work grew out of. It is a DAG, it is
cycle-checked, it drives the layout and the "isolate lineage" view, and it
carries no meaning beyond descent — every arrow looks the same.

`relates` is the **meaning** layer. It was added 2026-08 because the backfill
produced three findings that could only be connected in prose: a scramble panel
that *contradicted* an earlier one, an epitaxial design that *superseded* a
refuted H-bond hypothesis, and a task that *resolves* a live threat to a paper's
central claim. On the map those were three identical grey arrows.

| type | means | reads from the other end |
|---|---|---|
| `supports` | this result strengthens that one, ideally by an independent route | supported by |
| `contradicts` | these two results are in tension; a reader must see both | contradicted by |
| `supersedes` | this replaces that as the approach or answer to use | superseded by |
| `resolves` | this closes that open question, threat or gap | resolved by |

```yaml
relates:
  - {to: <node-id>, type: contradicts, note: why, in one line}
```

Rules that differ from `parents`:

- **Not cycle-checked.** Two results really can contradict each other, and that
  is a fact about the research rather than a defect.
- **May point backwards in time.** A result from August can contradict one from
  June.
- **Backlinked.** The renderer shows the inverse phrasing on the target, so a
  contradiction is equally findable from either node — otherwise you only find
  it from whichever node happened to be written second, which is the node the
  reader hasn't got to yet.
- **A pair joined by both lineage and a relation draws one arrow**, styled by
  the relation. The typed edge is the more specific claim.
- `note` is optional but warned about. A typed edge with no reason is an arrow
  nobody can act on.

Four types, and the bar for a fifth is a real node that needs it. Resist the
urge to add `refines`, `inspires`, `relates-to` — an edge vocabulary nobody can
keep in their head is an edge vocabulary that gets used inconsistently, and an
inconsistently-typed edge is worse than an untyped one.

Add relations to an existing node without a status change:

```sh
scripts/new_node.py --update 2026-07-31-mplastic-r1-scramble-panel \
  --relate "contradicts:2026-06-25-mplastic-scramble-control:composition, not order"
```

Adding an edge is not a state transition, so this appends no history entry.

## Types

| type | status values | terminal | extra fields |
|---|---|---|---|
| `experiment` | `running` `worked` `dead` `parked` | worked, dead | `repo` `commit` `host` `artifacts[]` |
| `direction` | `open` `parked` `closed` | closed | — |
| `seed` | `seed` `promoted` `killed` | promoted, killed | `origin` `contacts[]` |
| `milestone` | `planned` `submitted` `accepted` `done` | accepted, done | `venue` `date` `url` |
| `task` | `todo` `doing` `done` `dropped` | done, dropped | `due` `source` |

"Terminal" means the thread is finished and the digest should stop nagging
about it. Note `parked` is **not** terminal for an experiment and `closed` is
terminal for a direction — parking is a pause, closing is a decision.

### experiment

```yaml
repo: git@github.com:jlaw9/prekd.git
commit: a3f9c21                        # a SHA. Never a branch name
host: kestrel
artifacts:
  - kestrel:/scratch/jlaw/prekd/run-0142/summary.json
```

Branches get merged and deleted, and the most valuable nodes here are exactly
the dead ends git is designed to garbage-collect. The validator rejects a
`commit` that isn't a SHA, and an `artifact` that isn't `host:/absolute/path`.

### seed

`contacts` is the highest-value field in the schema. Reviving a conference idea
six months later means emailing the person, and by then the name is gone.

```yaml
origin: ACS Fall 2026, poster session Tue PM
contacts:
  - {name: Dana Whitfield, email: dwhitfield@uw.edu, affiliation: UW ChemE}
```

### milestone

```yaml
venue: JACS
date: 2026-07-30      # the venue/deliverable date — NOT created or updated
url: https://...
```

A milestone is just a node with a lot of parents. An experiment has one or two;
a paper has a dozen. Click the milestone and you see every experiment that fed
it, including the dead ends that shaped the framing — that's the view that
makes methods sections and annual reviews writable. No special edge direction
is involved, just high fan-in.

### task

```yaml
due: 2026-08-28
source: 2026-07-02-prekd-jacs-paper   # the node or meeting that created the commitment
```

Tasks are nodes rather than a side list so they render as the pending frontier
of the graph. An open task with no `due` warns — it will never surface in a
digest, which makes it invisible rather than pending.

## Papers registry

`papers/<doi-slug>.md`, where the slug is the DOI with `/` replaced by `__`.

```yaml
doi: 10.1021/acs.jced.3c00123
title: Solvent effects on nucleophilic substitution rate constants
authors: [R. Okonkwo, M. Feld]
year: 2023
venue: J. Chem. Eng. Data
```

The slug is a **filename only**. Papers are resolved through the `doi:` field,
never by un-slugging a filename — a DOI may itself contain `__`, so the
transform isn't reversibly unique.

The renderer builds backlinks, so each paper shows every node that cites it,
and each citing node shows what else cites the same paper. Use the
`litsearch-workflow` skill to produce verified DOIs; don't reimplement
retrieval.

## What the validator checks

Errors block a commit:

- `id` matches the filename stem and the `YYYY-MM-DD-slug` format; no duplicates
- `type` is known; `status` is valid for that type
- required fields present; dates parse; `updated >= created`
- `history` non-empty, chronological, statuses valid, last entry agrees with `status`
- `parents` all resolve, nothing is its own parent, **no cycles**
- `relates` entries are mappings with a known `type` and a resolving, non-self
  `to` (cycles are legal here)
- history entries carry only `date`/`status`/`note` — an extra key means an
  unquoted comma split the note and turned its tail into a bogus key
- `refs` are bare DOIs; `commit` is a SHA; `artifacts` are `host:/path`

Warnings don't block:

- unknown frontmatter field (schema drift — add it properly or drop it)
- a `relates` entry with no `note` explaining why
- `ref` with no page in `papers/`
- open task with no `due`
- `id` date prefix disagreeing with `created`
