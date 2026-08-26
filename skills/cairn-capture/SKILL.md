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

## A reaction to a node that already exists

If the thought is *about* a specific node — a doubt, a correction, "the number
here looks wrong" — it belongs on the node, not in the queue. The inbox detaches
it from the thing it is about, and nobody re-attaches it later.

```sh
$CAIRN_PATH/bin/cairn note <node-id> "<the sentence>"
```

That appends a dated bullet under `## Notes` in the node body. It does **not**
change `status`, `updated` or `history` — a note is not a claim about the state
of the work. `standup` and `digest` surface it, and a note dated after the node's
last status change is reported as unanswered until the thread moves.

**Write a note in Jeff's voice only when he said it.** If the observation is
yours, it belongs in the history note of a status change (`/log`'s job) or in
`inbox/`. A `## Notes` bullet reads as the human's word, and quietly putting your
inference there makes the graph less trustworthy, not more.

## Meetings

A meeting has its own directory, and there is a command for getting one in:

```sh
$CAIRN_PATH/bin/cairn import_note <file> --meeting --who dave
pbpaste | $CAIRN_PATH/bin/cairn import_note --meeting --who "dave, sarah"
```

That writes **two** files on purpose: the notes land in
`meetings/<YYYY-MM-DD>-<who>.md`, and a one-line pointer lands in `inbox/`. The
record is permanent and found by who was in the room; the *obligation to read it*
is the queue item `/triage` consumes. Content is verbatim — never convert org
markup, never reformat.

Write it raw — attendees, what was said, what was decided, what was promised. No
schema. If the meeting produced a commitment with a deadline, that is a `task`
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
