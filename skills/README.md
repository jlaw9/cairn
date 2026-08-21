# Cairn's skills

Cairn's conventions only ever reached agents working *inside* this repo, because
they live in this repo's `CLAUDE.md`. An agent in a project repo — which is
where the research actually happens — had no idea the graph existed.

These directories fix that, and the fix is a path. Each is a self-contained
skill in the format Claude Code already reads: a `SKILL.md` with `name` and
`description` frontmatter. An agent in any repo on any machine uses one by
reading it, which is why nothing needs installing.

| skill | when |
|---|---|
| `cairn-capture/` | a thought, a result, a meeting note — anything worth keeping |
| `cairn-resume/` | starting or returning to work on a project |
| `cairn-log/` | a work session produced a result worth a node |

## Wiring it up

One line in a project's `CLAUDE.md` is the whole integration:

```markdown
Research activity is recorded in Cairn. To capture a note, resume a project, or
log a session, read the matching skill under `$CAIRN_PATH/skills/`.
```

That is the entire point of the [@skills protocol][paper] (Yin et al.,
arXiv:2608.12610): content, persistence and triggering are three different
things, and only triggering has to sit in the prompt. One line of prompt
residency, three skills reachable, zero tokens spent until one is used. Cairn
already worked this way for everything else — nodes by `id`, artifacts by
`host:/path`, code by `repo` + `commit` — so path-as-address is not a new idea
here, just one applied to procedures instead of data.

If `$CAIRN_PATH` is not set in the environment the agent is running in, the
absolute path works and is the more reliable form on a shared filesystem:

```markdown
… read the matching skill under
/kfs2/projects/bpms/jlaw/tools/Cairn-graph/skills/.
```

**Not vendored, not copied.** A copy in each project repo is a copy that drifts,
and the drift is silent — five projects each with a slightly different idea of
what `--status dead` means is worse than no convention. Reference the path.

## Using them off this filesystem

For a collaborator who has cloned Cairn rather than sharing a filesystem, the
same skills resolve from their own clone; only the path differs. If Cairn's
remote is reachable and they would rather not clone, the [`atskills`][repo] CLI
addresses these directly:

```sh
atskills get gh:jlaw9/Cairn-graph/skills/cairn-capture
```

The CLI is not required for anything above and is not a dependency of Cairn.
Reading a file at a path is the protocol; the CLI is a convenience for fetching
that path over the network.

[paper]: https://arxiv.org/abs/2608.12610
[repo]: https://github.com/SylphAI-Inc/atskills
