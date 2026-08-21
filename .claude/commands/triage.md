---
description: Turn inbox notes into nodes, or discard them
---

Work through `$CAIRN_PATH/inbox/` and decide what each note is.

`$ARGUMENTS` may name a single inbox file to triage, or a project to filter on.
With no arguments, take the whole inbox oldest-first.

This is the pass that pays for capture being free. The inbox is a junk drawer by
design — it accepts anything from anywhere, unvalidated — so someone has to sort
it, and separating that from capture is the entire reason capture stays cheap.

## 1. Read the queue

```sh
ls -t $CAIRN_PATH/inbox/
```

Each file carries when it was written, on which host, in which repo at which
commit. That context is often the thing that makes a two-line note legible weeks
later — read it before deciding the note is meaningless.

## 2. For each note, pick one of four

**A node.** It states something that was settled — a result, a refuted claim, a
literature finding. Draft it with `/log`'s rules: `$CAIRN_PATH/bin/cairn new_node
<type> "<title>" --project <key> --parent <id> --note "<one line>"`. The note's
own text usually becomes `## What I did`; the claim has to be stated explicitly,
because a captured thought rarely phrases itself as one.

**A history entry on an existing node.** More common than a new node, and easy to
miss. Check first: `$CAIRN_PATH/bin/cairn standup --project <key>`. If the note is
about a thread that already exists, it's `--update <id> --note "<one line>"`, not
a second node about the same work.

**A task.** A commitment with a deadline and no scientific claim:
`new_node task "<what>" --project <key> --due <YYYY-MM-DD>`.

**Nothing.** Plenty of captures are a thought that went nowhere, a duplicate, or
a note whose content is now obvious. Say so and delete the file. This is a normal
outcome and refusing to do it is how the inbox becomes another backlog nobody
reads. Deleting an *inbox file* is fine — the never-delete rule is about nodes.

If a note contains several unrelated things, split it: several nodes, or one node
plus a deletion. Don't force one file into one node.

## 3. Show, then commit

Print every node you drafted and **wait for confirmation before committing.** The
whole point of triage happening separately from capture is that this is where a
human reads it. Never commit a node nobody has seen.

Then, in the graph repo:

```sh
cd $CAIRN_PATH && make build && git add -A \
  && git commit -m "triage: <n> notes" && git push
```

Remove the inbox files you filed, in the same commit as the nodes they became —
so the diff shows the junk turning into structure, which is the one place that
history is worth reading.

## Notes

- **Ask about interpretation, not about filing.** The project key, the parent, the
  type: infer those. Whether a number means the approach failed: ask.
- A note that can't be triaged without information nobody has is a note to leave
  in the inbox. Say which ones you left and why.
- If a captured item refutes or supersedes an existing node, add the typed
  relation — `--relate "contradicts:<id>:<why>"`. Those cross-links are the
  hardest thing to reconstruct later and the cheapest thing to add now.
