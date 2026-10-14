# Cairn with OpenViking

Cairn works on its own: a git repo of markdown nodes, a Python tool with one
dependency, Claude Code commands and a map rendered from disk. Nothing in this
document is required. It is here because the two systems answer neighbouring
questions and are better together, and because the boundary between them has to
be drawn once, deliberately, or it will be drawn badly by accident.

## What each one is for

**[OpenViking](https://github.com/volcengine/OpenViking) is an agent's memory.**
A context database presented as a filesystem — `viking://resources/` for
documents and repos, `viking://user/<you>/memories/` for what has been learned
about you and your work, `viking://.../skills/` for procedures — with semantic
retrieval over all of it and tiered summaries (an abstract, an overview, the
content) so an agent can decide what to read before reading it. Its Claude Code
plugin injects relevant memories before every prompt, captures each turn, and
commits sessions for memory extraction in the background. It is general: it
remembers coding habits and a project's entities as readily as a result.

**Cairn is the research record.** Not what an agent remembers but what the
science concluded: one node per claim, with a status that can be `dead`, a
lineage, typed relations, a time axis you can replay, and a review derivation
that says which claims a human has actually weighed in on. Everything in it has
a reason attached, because the question it answers — *did we already try this,
and what happened?* — is only worth answering if the answer can be trusted six
months later.

The difference that decides the design: **memory is extracted; a record is
asserted.** What OpenViking distils from a session is a summary nobody has
read. What enters `nodes/` is a claim somebody stands behind. The first is
exactly what Cairn's `inbox/` exists to hold, and the second is what a memory
system cannot produce on its own.

## The seam

Two directions, and they are not symmetric.

### The graph is a resource (Cairn → OpenViking)

```sh
cairn openviking status          # is `ov` here, is a server up, what would be pushed
cairn openviking push            # dry run: prints the `ov add-resource` commands
cairn openviking push --apply    # registers them
```

`nodes/`, `build/graph.md` and `build/report.md` are registered under
`viking://resources/cairn/<graph-name>/`. OpenViking then does what it does to
any resource — abstracts, overviews, embeddings — and "did we already try this?"
is answered by its recall in every session it serves, as well as by
`cairn standup`. Re-running `push` refreshes the same targets in place; it never
mints a second copy.

Only those three. `inbox/` is unreviewed by definition; `meetings/` is raw and
often not yours alone to share; `papers/` is already indexed by a DOI. If a
retriever should see more, that is a decision to make on purpose.

### Memories are capture (OpenViking → Cairn)

What OpenViking extracts from a session — an event, a case, a trajectory — may
well be a research finding. It still enters Cairn through the front door:

```sh
cairn capture --project <hint> --title "<one line>" "<the memory, verbatim>"
```

and `/triage` decides whether it is a node, a history entry on one that exists,
a task, or nothing. **Nothing writes a node from a memory.** Design decision 7
(capture is not structure) and the commit policy both say so, and the reason is
the same one that makes the graph worth keeping: a missing node must mean "not
tried", and it only can if every present node was put there on purpose.

The agent is the one that reads `viking://~/memories/` — through OpenViking's
own tools, which its plugin provides — and the one that decides a memory is
worth a capture. Cairn provides the destination and the rule.

### What does not cross

- **No import.** OpenViking's Python package is AGPLv3 and needs an embedding
  model, a vision-language model and a running server. Cairn's one dependency
  is PyYAML, and `cairn capture` has to work on a login node with none of the
  above. `cairn openviking` shells out to the `ov` command and says, in one
  sentence, when it is absent.
- **No OpenViking state in `nodes/`.** Not a memory id, not a `viking://` URI
  field. The graph format is identical with and without OpenViking; that is what
  lets two collaborators on one graph make different choices about it.
- **No server in Cairn's path.** The map, the hook, `standup`, `sync` and the
  validator never wait on anything but git and disk.

## Two setup paths

Both are first-class, and `cairn onboard` offers the second only when `ov` is
already installed.

**Standalone.** `cairn onboard`, answer three questions, done. The session hook
gives every session the graph's state; `/log`, `/capture`, `/triage` and the
skills do the writing; the map does the reading. This is the complete tool.

**With OpenViking.** Install OpenViking and its Claude Code plugin first
([their docs](https://docs.openviking.ai/)), then `cairn onboard` — it detects
`ov` and offers to register the graph. From then on, OpenViking recalls the
record alongside everything else it knows, and the agent treats memories about
research as captures to be triaged. Why you would want both: OpenViking makes an
agent *remember*; Cairn makes the research *legible* — the dead ends, the
lineage, who has reviewed what, and how it looked in June. Neither does the
other's job.

## Overlaps worth knowing about

- **Session mining.** `cairn mine_sessions` surveys Claude Code transcripts to
  backfill a graph; OpenViking's `openviking-server ingest` imports the same
  transcripts into its own sessions for memory extraction. They read the same
  files for different ends. Backfill the graph with the former; let the latter
  build memory. Neither writes a node.
- **Session start.** Both install a `SessionStart` hook. They coexist —
  `install_context` appends its hook group and leaves others in place — and say
  different things: OpenViking injects memories relevant to the prompt, Cairn
  injects what the graph says needs attention and the commit policy in force.

## Status

The seam is designed and the command is built and tested against a stub `ov`.
It has **not** been run against a live OpenViking server; the `--to` refresh
semantics follow the documented CLI and the dry run exists so a wrong flag costs
a read, not a write. If you run it live, `cairn capture` what happened.
