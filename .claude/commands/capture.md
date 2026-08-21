---
description: Save a thought, note or observation to Cairn's inbox for later triage
---

Write `$ARGUMENTS` — or whatever in this conversation is worth keeping — to
Cairn's inbox.

The graph is at `$CAIRN_PATH`. The inbox has no schema and nothing there is ever
validated, which is what makes this safe to do without ceremony.

```sh
$CAIRN_PATH/bin/cairn capture --project <hint> --title "<one line>" "<the note>"
```

## Rules

**Write first, ask nothing.** No clarifying questions before the file exists.
A prompt at capture time is how capture dies, and this is the one rule that
overrides every other rule here. If `$ARGUMENTS` is empty, capture what the
conversation just established — a result, a decision, a realisation — and say
what you wrote.

**`--project` is a guess.** It's a hint for triage, not a validated key. Don't go
looking for the right one; a wrong guess costs nothing in the inbox, which is not
true anywhere else in Cairn.

**Keep the user's words.** Don't summarise a thought into something tidier — the
phrasing is often the content, and triage can compress later. Include numbers,
file paths, error text and node ids verbatim if they came up.

**One note per idea.** Two unrelated thoughts are two captures. A single file
holding both is a file triage can only half-file.

**Don't commit.** Capture leaves the file uncommitted on purpose: committing runs
the validation hook, which can fail for reasons elsewhere in the graph, and a
capture that can fail is not a capture. `/triage` commits.

## Meetings go somewhere else

Meeting notes are raw and don't need triage to be useful. Write them directly to
`$CAIRN_PATH/meetings/<YYYY-MM-DD>-<who>.md` — attendees, what was said, what was
decided, what was promised. No schema. Note commitments inline as
`→ task: <what> by <when>` so triage can find them.

## Other input forms

```sh
# a file written elsewhere — org-mode, markdown, anything, verbatim
$CAIRN_PATH/bin/cairn capture --from-file <path> --title "<subject>"

# piped output — a traceback, a log tail
tail -40 <logfile> | $CAIRN_PATH/bin/cairn capture --title "<subject>"
```

Don't convert org markup to markdown. Inbox files are never parsed.

## Not this

If the session produced a **result you can state as a claim** and the user is
here to confirm what it means, that's `/log` — a real node — not a capture.
Capture is for everything else, and for anything written when nobody is watching.
