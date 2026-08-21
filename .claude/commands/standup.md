---
description: What to pick up today, or where you left off on one project
---

Report the state of research work out of Cairn, and help decide what to touch.

`$ARGUMENTS` may name a project key, in which case give that project's resume
packet instead of the survey. It may also be a question ("what's stalled?",
"what's due?") — answer it from the same data.

The graph is at `$CAIRN_PATH`. If that isn't set, ask for the path rather than
guessing, and mention `make install-commands` in the Cairn clone, which prints
the export line for a shell profile.

## 1. Read

```sh
$CAIRN_PATH/bin/cairn standup                      # every project
$CAIRN_PATH/bin/cairn standup --project <key>      # one project, deeper
```

With no `$ARGUMENTS`, run the survey. With a project key, run the packet. If a
key isn't recognised, the error lists the valid ones — use it, don't guess.

Also check for anything waiting: `ls $CAIRN_PATH/inbox/`. Untriaged items are
work that hasn't entered the graph yet, and they're invisible to every other view.

## 2. Say what needs a decision, not what exists

The command's output is already ordered by what needs attention. Your job is to
turn it into a recommendation, which the command deliberately does not do.

- **Lead with the one thing to pick up**, and why that one. Overdue beats quiet
  beats live; within that, the thread whose `next:` line is most actionable.
- **Name what's blocked on someone else** separately. A thread waiting on a
  collaborator's data isn't stalled and shouldn't be recommended as work.
- **Say what to drop or park.** A `planned` node quiet for two months is usually
  a decision nobody has made rather than work nobody has done, and saying so is
  more useful than listing it again. Parking it is a real option:
  `new_node --update <id> --status parked --note "<why>"`.
- If several projects are quiet, **don't list them all as equally urgent.** Pick
  one to resume and say why the others can wait.

Keep it short. This gets read at the start of a session, before any work.

## Notes

- `standup` ranks by need; `digest` is chronological. If the question is "what
  happened while I was away", use `cairn digest --days N` instead.
- Read `$CAIRN_PATH/nodes/<id>.md` when a summary line isn't enough to advise on.
- Don't write anything. This is a read-only view. If the conversation produces a
  decision worth keeping, that's `/log`, or `cairn capture` for a loose thought.
