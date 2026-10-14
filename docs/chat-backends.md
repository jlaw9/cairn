# Chat backends: what the CLIs actually do

Verified 2026-10-14, for the map's chat (`POST /api/chat` in `cairn serve`,
the `chat_backends` module beside it). This is a record of what was checked and how, not
what anyone remembered. Re-check it when either CLI's major behavior changes.
The captures it describes are replayed by the test suite
(`tests/fixtures/chat/`), so a changed stream shows up as a failing test.

| | Claude Code | Codex CLI |
|---|---|---|
| version checked | 2.1.300 (`claude --version`, installed) | 0.162.1 (`npx -y @openai/codex@0.162.1`, not installed) |
| one turn | `claude -p … -- <prompt>` | `codex exec --json … -- <prompt>` |
| resume | `--resume <session-id>` | `codex exec resume … -- <session-id> <prompt>` |
| session id | `session_id` on every line | `thread_id` on `thread.started` |
| guard | `--permission-mode dontAsk` + `--allowedTools` | `sandbox_mode="workspace-write"` + `approval_policy="never"` |
| extra system text | `--append-system-prompt` | `-c developer_instructions="…"` |
| text streaming | token deltas (`--include-partial-messages`) | whole message at `item.completed` |
| instructions file | `CLAUDE.md` | `AGENTS.md` (`CLAUDE.md` via fallback, see below) |
| skills | `~/.claude/skills`, plugins | `~/.agents/skills` and others, symlinks followed |
| session-start hook | yes, installed by `install_context` | yes, but not installed by Cairn (trust gate) |

## Claude Code 2.1.300

**Sources.** `claude --help`; the CLI reference at
<https://code.claude.com/docs/en/cli-reference>; and four real runs on this
machine (logged in), in a scratch directory.

- `-p` is print mode. `--output-format stream-json` needs `--verbose`. That is
  documented, and it is how every run here was made.
  `--include-partial-messages` adds `stream_event` lines that carry the raw
  API stream events.
- `--max-turns` works but **is not in `claude --help`**. The CLI reference
  documents it ("Exits with an error when the limit is reached") and says
  `--help` does not list every flag. A run with `--max-turns 1` exited 0.
- `--allowedTools` is variadic. The prompt therefore goes after `--`. A run with
  `--allowedTools … -- "-0.4 eV is the number…"` treated the dash-led prompt as
  the prompt. The same run showed that `--append-system-prompt` took effect.
- `--permission-mode dontAsk` refuses anything not on the allowlist and never
  prompts. With `--allowedTools "Bash(<abs>/bin/cairn *)" Read Grep Glob Skill`:
  - `<abs>/bin/cairn standup --project x` ran.
  - `ls /` was refused.
  - `<abs>/bin/cairn note x hello; ls /` was refused **whole**: the allowed
    prefix does not carry a compound command through.
  - Through the server later, `B=<abs>/bin/cairn; $B note --help` was also
    refused.
- `--resume <id>` continued the conversation. The model recalled the earlier
  turn, and the id was unchanged.
- **The system prompt is recorded on the first request and reused on resume**
  (CLI reference, "System prompt flags in resumed conversations"). That is why
  the open node goes in the turn's prompt and not in `--append-system-prompt`.
- The user's own hooks run. Every run emitted `system/hook_started` and
  `system/hook_response` for `SessionStart:startup`. On a machine with
  `install_context`, a chat turn therefore runs `cairn session_hook`, which
  includes the throttled `sync` pull.

Events seen (one JSON object per line):

```
{"type":"system","subtype":"init","session_id":"…","cwd":"…","tools":[…],"model":"…","permissionMode":"dontAsk",…}
{"type":"stream_event","event":{"type":"message_start","message":{"id":"msg_…",…}},"session_id":"…"}
{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"pong"}},…}
{"type":"stream_event","event":{"type":"content_block_start","content_block":{"type":"tool_use","name":"Bash",…}},…}
{"type":"assistant","message":{"id":"msg_…","content":[{"type":"tool_use","name":"Bash","input":{"command":"…"}}]},…}
{"type":"user","message":{"content":[{"type":"tool_result","content":"…","is_error":false}]},…}
{"type":"system","subtype":"permission_denied","tool_name":"Bash","tool_use_id":"…","message":"…"}
{"type":"result","subtype":"success","is_error":false,"result":"pong","session_id":"…","num_turns":1,"permission_denials":[…],…}
```

Things that are easy to get wrong:

- The complete `assistant` message repeats text that already arrived as deltas.
  One API message can also arrive as several `assistant` lines, one per content
  block, all with the same `message.id`.
- **`subtype` is not the verdict.** With DNS down, the run sent ten
  `system/api_retry` lines. Then came an `assistant` message with
  `"model":"<synthetic>"` and the text "API Error: Can't reach the API
  server…". Then came a `result` with `"subtype":"success"`, `"is_error":true`
  and `"terminal_reason":"api_error"`. The process exited 1. Only `is_error`
  and the exit code tell you the turn failed.
- Rate-limit and status lines (`rate_limit_event`, `system/status`) also appear.
  They are ignored.

## Codex CLI 0.162.1

**Sources.** `codex --help`, `codex exec --help`, `codex exec resume --help`,
`codex features list`, `codex debug prompt-input` and `codex sandbox`. All
were run from the npx-cached binary with an isolated `CODEX_HOME`, so this
machine's Codex state was not touched. Also used: the event and field names
compiled into that binary, and the official docs. The docs at
`developers.openai.com/codex/*` now redirect (308) to `learn.chatgpt.com/docs/…`:

- non-interactive mode: <https://learn.chatgpt.com/docs/non-interactive-mode>
- skills: <https://learn.chatgpt.com/docs/build-skills>
- hooks: <https://learn.chatgpt.com/docs/hooks>
- AGENTS.md: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>

**No real model turn was run against OpenAI.** The network was down for part
of the session, and the only credentials on the machine belong to the user's
Codex app. So the JSONL below has two sources:

- Captured from a real `codex exec --json` run with no network: `thread.started`,
  `turn.started`, top-level `error` and an `item.completed` error item.
- Built from the documented event list and the field names in the binary:
  `command_execution`, `file_change`, `agent_message` and `turn.completed`.

These are the facts I was least sure of, and the first to re-check against a
real signed-in turn.

- `codex exec` runs non-interactively. `--json` prints JSONL, and `-C/--cd`
  sets the working root. `-s/--sandbox` takes `read-only` (the documented
  default for `exec`), `workspace-write` or `danger-full-access`.
- `exec` has **no `-a/--ask-for-approval`** (only the interactive `codex` has
  it). The approval policy is set with `-c approval_policy="never"`.
  `codex debug prompt-input -c approval_policy="never"` reports "Approval
  policy is currently never".
- `codex exec resume [SESSION_ID] [PROMPT]` exists. It takes **neither `-s`
  nor `-C`**, but it does take `-c`, `--json` and `--`. So Cairn sets the sandbox
  with `-c sandbox_mode="workspace-write"` on both forms, and sets the working
  directory on the process. Resuming an unknown id exits 1 with "no rollout
  found for thread id …" on stderr and nothing on stdout.
- `-c developer_instructions="…"` adds developer text. The value is parsed as
  TOML, so a JSON-escaped string with `\n` and `\"` comes through intact. This
  was checked with `codex debug prompt-input`.
- **The `workspace-write` sandbox makes `.git` read-only**, and the network is
  off. This was checked with
  `codex sandbox -c 'sandbox_mode="workspace-write"' -- sh -c '… git commit …'`:
  writing a file in the working directory worked, while `git add` failed on
  `.git/index.lock: Operation not permitted`, and writing outside it failed too.
  For Cairn this means:
  - `cairn new_node` and `cairn capture` work.
  - `cairn note` writes the note and then reports that its commit failed.
    `note.py` writes before it commits, so nothing is lost.
  - `cairn sync` cannot run.

  The fact that Codex cannot commit is consistent with design decision 6: what
  Codex writes stays uncommitted until a human commits it. The chat's system
  text tells Codex about this restriction.
- Without credentials, `codex exec` does not fail fast. It retries the
  connection and prints `{"type":"error","message":"Reconnecting... n/5 (… 401
  Unauthorized …)"}`. A Codex install with no `codex login` will look slow
  before it fails.

Event types (docs: `thread.started`, `turn.started`, `turn.completed`,
`turn.failed`, `item.*`, `error`). Item types in the binary: `agent_message`,
`reasoning`, `command_execution` (`command`, `aggregated_output`, `exit_code`,
`status`: `in_progress|completed|failed|declined`), `file_change` (`changes`
with `path` and `kind`: `add|delete|update`), `mcp_tool_call`, `web_search`,
`todo_list`, and `error`.

```
{"type":"thread.started","thread_id":"01a13b10-b073-7b51-b9c2-5791cf4bd7e7"}
{"type":"turn.started"}
{"type":"error","message":"Reconnecting... 2/5 (stream disconnected before completion: …)"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Falling back from WebSockets to HTTPS transport. …"}}
```

The top-level `error` lines above are retry notices, not failures. The fatal
signals are `turn.failed` and a non-zero exit. Cairn drops `Reconnecting…`
errors and item-level errors.

**Skills.** The docs list these locations:

- `$CWD/.agents/skills`
- `$CWD/../.agents/skills`
- `$REPO_ROOT/.agents/skills`
- `$HOME/.agents/skills`
- `/etc/codex/skills`
- the bundled skills

They also say symlinked skill folders are followed, and that a `SKILL.md` needs
`name` and `description` frontmatter, which Cairn's skills already have.
`codex debug prompt-input` was run with a skill symlinked into each of
`$CODEX_HOME/skills`, `$HOME/.agents/skills` and `<repo>/.agents/skills`, and
all three were listed. The first location is undocumented, but the bundled
`skill-installer` writes there. `cairn install_context --codex` uses the
documented `~/.agents/skills`.

**AGENTS.md.** Codex reads `AGENTS.override.md` or `AGENTS.md` from
`$CODEX_HOME`. It then walks from the project root (the git root) down to the
working directory, taking at most one file per directory, with a 32 KiB total
(`project_doc_max_bytes`). Other filenames count only if they are listed in
`project_doc_fallback_filenames`. The chat passes
`-c project_doc_fallback_filenames=["CLAUDE.md"]`, so it reads the graph's
`CLAUDE.md` even without the AGENTS.md pointer. `prompt-input` showed the file
loaded with the flag and not loaded without it.

**Hooks.** Codex **does** have a `SessionStart` hook, which the brief assumed
it lacked. `codex features list` shows `hooks stable true`. The docs list:

- events: `SessionStart` (sources `startup|resume|clear|compact|fork`),
  `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and others.
- configuration: `hooks.json` or `[hooks]` in `config.toml`, under `~/.codex/`
  or `<repo>/.codex/`.
- context injection: plain stdout or `hookSpecificOutput.additionalContext`,
  the same contract `cairn session_hook` already emits for Claude Code.

But "before a non-managed hook can run, Codex requires you to review and trust
the exact hook definition" (with `/hooks` in the TUI). The docs do not say
whether hooks run under `codex exec`. **Cairn does not install a Codex hook.**
One written by `install_context` would do nothing until it was trusted by hand.
The cost: a Codex session gets no automatic `cairn sync` pull and no injected
graph state. The user runs `cairn sync` themselves, and the `cairn-resume`
skill is how a Codex agent finds the frontier.
