---
description: Record the current work session as a node in the research graph
---

Record what happened in this work session as a node in Cairn.

$ARGUMENTS may name the node to update, or describe what was done. If it's
empty, work it out from the repo.

## 1. Read the work, don't ask about it

From the **current project repo** (not the graph repo), gather:

- `git log --oneline -20` and `git status` — what changed, and is it committed?
- `git rev-parse HEAD` — the SHA to record. If the tree is dirty, say so and
  ask whether to commit first; a node pointing at a dirty tree is a lie.
- `git remote get-url origin` — the `repo` field.
- `hostname` — `laptop` or `kestrel`.

Infer the project key from the repo name unless it's obvious it differs.

## 2. Decide: new node, or status change?

Prefer updating an existing node. A session that continues yesterday's
experiment is a new `history` entry, not a new node.

Check `nodes/` for an open node in this project whose subject matches. If one
exists and this session moved it forward:

```sh
scripts/new_node.py --update <id> --status <status> --note "<one line>" --commit <sha>
```

Otherwise create one:

```sh
scripts/new_node.py experiment "<title>" --project <key> \
  --parent <id> --repo <url> --commit <sha> --host <host>
```

Set `--parent` to whatever this work grew out of — the direction it belongs to,
or the experiment it followed. Ask if genuinely ambiguous; guess if not.

## 3. Fill the body

Write `## Claim`, `## What I did`, `## Next` yourself from the diff and the
commit messages. You have the evidence for all three.

**`## Result` is the one thing to ask about.** It's the interpretation — what
the numbers mean, whether the thing worked — and it usually isn't in the diff.
Ask one focused question, not a form. If Jeff answers in a sentence, that
sentence is the section; don't inflate it.

If the result is that something failed: set the status to `dead` and write down
*why* in the history note. Dead ends are the highest-value nodes in this repo.
Do not soften them into `parked`. Park means "paused, will resume"; dead means
"we learned this doesn't work."

## 4. Show, then commit

Print the node. Wait for confirmation. Never commit a node Jeff hasn't seen.

Then, in the graph repo:

```sh
make build && git add -A && git commit -m "log: <node id>" && git push
```

The pre-commit hook validates. If it fails, fix the node — don't `--no-verify`.

## Notes

- One small summary figure may go in `assets/` so the HTML has a thumbnail
  without HPC access. **One.** Not a results directory.
- Big outputs are referenced as `host:/path` in `artifacts`, never copied in.
- If this session produced a commitment with a deadline rather than a result,
  that's a `task` node with a `--due`, not an experiment.
