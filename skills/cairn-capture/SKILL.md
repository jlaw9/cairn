---
name: cairn-capture
description: Save a research thought, observation, result, meeting note or open question to Cairn's inbox for later triage. Use when something worth keeping happens and there is no time or no reason to file it properly — an idea mid-session, a number that looked wrong, a decision from a meeting, a dead end you don't want rediscovered. Works from any repo on any machine. Never blocks, never validates, never asks which project.
---

# Capture to Cairn

Cairn is a persistent graph of research activity across all projects. This skill
writes to its **inbox**, which is the deliberately unstructured half: no schema,
no validation, no required fields.

Use it freely. The graph's design rule is that **capture wins** — a messy note
beats a missing one, every time, because a graph with gaps can't be trusted and
an untrusted graph gets abandoned.

## Do this

```sh
$CAIRN_PATH/bin/cairn capture --project <hint> --title "<one line>" "<the note>"
```

If `$CAIRN_PATH` is unset, use the absolute path to the Cairn clone. On a shared
filesystem that is `/kfs2/projects/bpms/jlaw/tools/Cairn-graph`.

Other input forms, when the note isn't a single string:

```sh
# a file written elsewhere — org-mode, markdown, anything, verbatim
$CAIRN_PATH/bin/cairn capture --from-file ~/notes/meeting.org --title "meeting with Dave"

# piped output — a traceback, a log tail, a table of numbers
tail -40 slurm-12345.out | $CAIRN_PATH/bin/cairn capture --title "why the md33 run died"
```

`--project` is a **hint for triage, not a validated key.** Pass your best guess
and move on; a wrong guess costs nothing here, and this is the one place in
Cairn where that is true. Do not go looking for the right key.

The command records host, working directory, and the repo and commit if the note
was written inside a git tree. That context is free here and unreconstructable
later, which is why it is worth the one call.

## When to use this instead of a node

**Default to this.** Reach for `cairn-log` only when a session produced a result
you can state as a claim, and only when the user is present to confirm the
interpretation.

Capture rather than log when any of these is true:

- The user is not around to review a node. **Never commit a node nobody has
  seen** — an auto-populated graph nobody trusts is the failure Cairn exists to
  avoid. The inbox is the correct destination for unsupervised writing, and it is
  safe precisely because nothing there claims to be a finding.
- It's a thought or a question rather than a result.
- It came from somewhere Cairn can't see — a conversation, a web session, a
  whiteboard, a hallway.
- You aren't sure which project it belongs to, or it spans several.
- It's a meeting. Meeting notes go in raw; see below.

## Meetings

A meeting has its own directory and doesn't need triage to be useful:

```sh
$CAIRN_PATH/meetings/<YYYY-MM-DD>-<who>.md
```

Write it raw — attendees, what was said, what was decided, what was promised.
No schema. If the meeting produced a commitment with a deadline, that is a `task`
node later, and noting "→ task: X by Friday" inline is enough for triage to find
it.

## Do not

- **Do not validate, reformat, or convert the content.** Org markup in a `.md`
  file is fine. Inbox files are never parsed.
- **Do not commit.** Capture leaves the file uncommitted on purpose: a commit runs
  the validation hook, which can fail for reasons elsewhere in the graph, and a
  capture that can fail is not a capture. Triage commits.
- **Do not ask clarifying questions before writing.** Write first. A prompt at
  capture time is how capture dies — this is the one rule that overrides the
  others.
- **Do not create nodes in `nodes/`.** That is `cairn-log`'s job, and it needs
  review.
