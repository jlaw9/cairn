#!/usr/bin/env python3
"""The map's chat, as a subprocess of the user's own coding CLI.

`cairn serve` can answer a question typed into the map by running one turn of
**Claude Code** (`claude -p`) or the **OpenAI Codex CLI** (`codex exec`), signed
in as whoever is sitting at the machine. There is no API key here, no hosted
service and no model of Cairn's own: the CLI the user already trusts in their
terminal is the whole backend, and its own permission system is the guard.

This module is the part that knows about the CLIs. Per backend it has three
pure functions — `available()`, `argv()` and `events()` — and one runner,
`run()`, that starts the process and turns its output into Cairn's common event
shape. `serve.py` only validates the request and writes the stream.

The common event shape, one JSON object per line on the wire:

    {"type": "text",  "delta": "..."}
    {"type": "tool",  "name": "Bash", "summary": "bin/cairn standup --project x"}
    {"type": "error", "message": "..."}
    {"type": "done",  "session": "<id or null>", "backend": "claude|codex",
                      "ok": true, "code": 0, "rebuilt": true}

`tool` may also carry `"denied": true` (the CLI refused it). `done` is always
the last line and there is exactly one; `rebuilt` is added by the server.

What each CLI emits was captured from real runs on 2026-10-14 — Claude Code
2.1.300 and Codex CLI 0.162.1 — and is written up, with sources, in
`docs/chat-backends.md`. The test suite replays those captures through fake
executables, so a change in either CLI's output shows up as a failing
translation test rather than as a silent blank panel.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterator

TOOL_ROOT = Path(__file__).resolve().parent.parent
CAIRN = TOOL_ROOT / "bin" / "cairn"

#: A turn that is still running after this long is stopped. Long enough for a
#: `standup` plus a few reads and a node draft; short enough that a wedged
#: process does not hold a server thread for the afternoon.
TURN_TIMEOUT = 15 * 60

#: Claude Code's agentic-turn cap for one chat message. `--max-turns` is
#: documented (code.claude.com/docs/en/cli-reference) though `claude --help`
#: does not list it.
MAX_TURNS = 30

#: One line of a summary is enough to say what ran; the full command is in the
#: CLI's own transcript.
SUMMARY_CHARS = 200

#: bin/cairn subcommands the chat may not run, though they go through bin/cairn.
#: Each one is a human's act or reaches past the graph:
#: - `review` commits a draft *as read by a human*. The chat running it would
#:   forge the one signal design decision 6 depends on.
#: - `discard` declines a draft, and `edit` rewrites a committed node and
#:   commits it. Both are the panel's job, done by the person at it.
#: - `policy` and `install_*`/`onboard` change how agents behave.
#: - `sync` pulls or pushes, `sync_issues` writes to GitHub, and `export`,
#:   `export_example` and `init` write outside the graph.
#: Claude Code enforces this list with deny rules, which beat the bin/cairn
#: allow rule (checked on 2.1.300). Codex is only told about it, and its sandbox
#: stops the committing and networked ones anyway.
REFUSED = ("review", "discard", "edit", "policy", "install_context",
           "install_hooks", "onboard", "sync", "sync_issues", "export",
           "export_example", "init")

SYSTEM = """\
You are answering inside the Cairn map: a browser view of a research graph, \
served on this machine by `cairn serve`. The person typing is looking at the map.

- The graph root is {graph} and it is your working directory. Its conventions \
are in {graph}/CLAUDE.md (if present) and {tool}/CLAUDE.md; read them before \
writing anything.
- Write only through `{cairn}`. Never create, edit or delete a file under \
nodes/ yourself, and never hand-edit a node's frontmatter: `status` and \
`history` move together only through `{cairn} new_node --update`.
- Never run `git commit` or `git push`. `bin/cairn` commands that commit on \
their own, such as `cairn note`, are fine — but `cairn note` is for words the \
user gave you. An observation of your own is `{cairn} capture`, not a note in \
their name.
- A node you create is a draft the user reviews in the map's panel before it \
is committed. This holds whatever the graph's commit policy says (it is \
`{mode}` here): from the map's chat you never commit a node, and you never \
run `cairn {refused}`. Those are the user's acts, done in the panel or a \
terminal. Say which file you wrote, using the path bin/cairn printed.
- Before proposing work in a project, run `{cairn} standup --project <key>`. \
A `dead` node there is a claim already refuted, with the reason attached.
- The panel is narrow: answer briefly, and cite nodes as [[<node-id>]].\
"""

#: Said to Codex only, because only Codex's sandbox does this (verified with
#: `codex sandbox` on 0.162.1: `.git/index.lock: Operation not permitted`).
CODEX_ADDENDUM = """

- Your sandbox makes .git read-only and has no network. A bin/cairn command \
that commits (`cairn note`) writes its file and then reports that the commit \
failed: that is expected here, and nothing is lost. Tell the user it is \
uncommitted. `cairn sync` cannot run from here at all.\
"""


def system_prompt(graph: Path, tool: Path = TOOL_ROOT, backend: str = "") -> str:
    """The text appended to the CLI's own system prompt. Static per graph.

    It deliberately does not name the node the user is looking at: Claude Code
    records the system prompt on a conversation's first request and reuses it
    on every `--resume` until compaction (cli-reference, "System prompt flags
    in resumed conversations"), so a node named here would go stale the moment
    the user clicked another one. That goes in `turn_prompt()` instead.
    """
    try:
        import policy                                  # stdlib only
        mode = policy.read_commit_mode(graph)
    except ImportError:                                # a tool predating `cairn policy`
        mode = "ask"
    text = SYSTEM.format(graph=graph, tool=tool, cairn=tool / "bin" / "cairn",
                         mode=mode, refused="|".join(REFUSED))
    return text + (CODEX_ADDENDUM if backend == "codex" else "")


def turn_prompt(message: str, node: tuple[str, str] | None = None) -> str:
    """The user's message, prefixed with what they are looking at, if anything.

    Just the id and the title — the model can read `nodes/<id>.md` itself, and
    pasting the body here would be a second copy of it in the transcript.
    """
    if not node:
        return message
    node_id, title = node
    return (f"[In the map I have node {node_id} open: \"{title}\" "
            f"(nodes/{node_id}.md).]\n\n{message}")


def one_line(text: object, limit: int = SUMMARY_CHARS) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


class Claude:
    """`claude -p --output-format stream-json`, one process per turn.

    Permissions: `--permission-mode dontAsk` with an allowlist, so anything not
    on the list is refused rather than prompted for — there is nobody at a
    terminal to answer a prompt. Bash is allowed only with `bin/cairn` as the
    command prefix; a compound command (`cairn x; ls /`) is refused whole,
    which was checked against 2.1.300 rather than assumed.
    """

    name = "claude"
    binary = "claude"
    install = ("install Claude Code (https://code.claude.com/docs) and sign in "
               "by running `claude` once in a terminal, then restart `cairn serve`")

    @staticmethod
    def available() -> str | None:
        return shutil.which(Claude.binary)

    @staticmethod
    def allowed_tools(tool: Path = TOOL_ROOT) -> list[str]:
        return [f"Bash({tool / 'bin' / 'cairn'} *)", "Read", "Grep", "Glob", "Skill"]

    @staticmethod
    def disallowed_tools(tool: Path = TOOL_ROOT) -> list[str]:
        cairn = tool / "bin" / "cairn"
        # Both forms, so a bare `cairn sync` is caught as well as `cairn sync --push`.
        return [rule for sub in REFUSED
                for rule in (f"Bash({cairn} {sub})", f"Bash({cairn} {sub} *)")]

    @staticmethod
    def argv(prompt: str, session: str | None = None, system: str = "",
             cwd: Path | None = None, tool: Path = TOOL_ROOT,
             binary: str | None = None) -> list[str]:
        # cwd is not a flag for Claude Code — the process's working directory is
        # the project. It is accepted here so both backends share a signature,
        # and `run()` is what actually places the process there.
        args = [binary or Claude.binary, "-p",
                "--output-format", "stream-json", "--verbose",
                "--include-partial-messages",
                "--permission-mode", "dontAsk",
                "--max-turns", str(MAX_TURNS)]
        if system:
            args += ["--append-system-prompt", system]
        if session:
            args += ["--resume", session]
        # Both tool lists are variadic. Each ends at the next flag, and `--`
        # closes the last one: without it the prompt would be read as one more
        # tool name, and a prompt that opens with a dash would be read as a flag.
        args += ["--disallowedTools", *Claude.disallowed_tools(tool),
                 "--allowedTools", *Claude.allowed_tools(tool), "--", prompt]
        return args

    @staticmethod
    def events(line: str, state: dict | None = None) -> list[dict]:
        state = {} if state is None else state
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(msg, dict):
            return []
        kind = msg.get("type")
        if msg.get("session_id"):
            state["session"] = msg["session_id"]

        if kind == "stream_event":
            ev = msg.get("event") or {}
            if ev.get("type") == "message_start":
                # Remember which messages arrive as deltas, so the complete
                # `assistant` message that follows is not printed twice.
                state.setdefault("streamed", set()).add(
                    (ev.get("message") or {}).get("id"))
            elif ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    return [{"type": "text", "delta": delta["text"]}]
            return []

        if kind == "assistant":
            message = msg.get("message") or {}
            out = []
            # "<synthetic>" is Claude Code reporting its own failure (no network,
            # say) in the shape of a reply. The `result` that follows says the
            # same thing as an error, which is where it belongs.
            synthetic = message.get("model") == "<synthetic>"
            streamed = message.get("id") in state.get("streamed", set())
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    out.append({"type": "tool", "name": block.get("name", "?"),
                                "summary": Claude.summarise(block.get("input"))})
                elif (block.get("type") == "text" and block.get("text")
                      and not streamed and not synthetic):
                    out.append({"type": "text", "delta": block["text"]})
            return out

        if kind == "system" and msg.get("subtype") == "permission_denied":
            return [{"type": "tool", "name": msg.get("tool_name", "?"),
                     "summary": "refused: not on the allowlist", "denied": True}]

        if kind == "result":
            out = []
            # `subtype` is not the verdict: an unreachable API ends with
            # subtype "success" and is_error true. Only is_error is.
            if msg.get("is_error") or str(msg.get("subtype", "")).startswith("error"):
                reason = msg.get("result") or msg.get("subtype") or "the turn failed"
                out.append({"type": "error", "message": one_line(reason, 600)})
            out.append({"type": "done", "session": msg.get("session_id")
                        or state.get("session"), "backend": "claude"})
            return out
        return []

    @staticmethod
    def summarise(tool_input: object) -> str:
        if not isinstance(tool_input, dict):
            return one_line(tool_input)
        for key in ("command", "file_path", "pattern", "skill", "path", "url"):
            if tool_input.get(key):
                return one_line(tool_input[key])
        return one_line(json.dumps(tool_input))


# --------------------------------------------------------------------------
# Codex CLI
# --------------------------------------------------------------------------


class Codex:
    """`codex exec --json`, one process per turn.

    Codex has no tool allowlist to speak of: its guard is the sandbox.
    `workspace-write` lets it write inside the graph root and nowhere else,
    keeps `.git` read-only and the network off, and `approval_policy="never"`
    means a command the sandbox refuses fails back to the model instead of
    waiting for a human who is not at a terminal.

    Everything is passed as `-c key=value` rather than as `-s`/`-C`, because
    `codex exec resume` accepts neither of those flags (0.162.1) and a resumed
    turn has to run under the same policy as the first.
    """

    name = "codex"
    binary = "codex"
    install = ("install the Codex CLI (`npm install -g @openai/codex` or "
               "`brew install --cask codex`), sign in with `codex login`, run "
               "`cairn install_context --codex --apply`, then restart `cairn serve`")

    @staticmethod
    def available() -> str | None:
        return shutil.which(Codex.binary)

    @staticmethod
    def config(system: str = "") -> list[str]:
        args = ["-c", 'sandbox_mode="workspace-write"',
                "-c", 'approval_policy="never"',
                # So the graph's CLAUDE.md is read even where nobody has run
                # `install_context --codex` to write an AGENTS.md pointer.
                "-c", 'project_doc_fallback_filenames=["CLAUDE.md"]']
        if system:
            # A JSON string literal is a valid TOML basic string for anything
            # json.dumps emits (\n, \", \\, \uXXXX), so this survives quotes and
            # newlines. Checked with `codex debug prompt-input`.
            args += ["-c", f"developer_instructions={json.dumps(system)}"]
        return args

    @staticmethod
    def argv(prompt: str, session: str | None = None, system: str = "",
             cwd: Path | None = None, tool: Path = TOOL_ROOT,
             binary: str | None = None) -> list[str]:
        exe = binary or Codex.binary
        if session:
            return [exe, "exec", "resume", "--json", *Codex.config(system),
                    "--", session, prompt]
        args = [exe, "exec", "--json", *Codex.config(system)]
        if cwd:
            args += ["-C", str(cwd)]
        return args + ["--", prompt]

    @staticmethod
    def events(line: str, state: dict | None = None) -> list[dict]:
        state = {} if state is None else state
        try:
            msg = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(msg, dict):
            return []
        kind = msg.get("type")

        if kind == "thread.started":
            state["session"] = msg.get("thread_id")
            return []
        if kind == "turn.completed":
            return [{"type": "done", "session": state.get("session"), "backend": "codex"}]
        if kind == "turn.failed":
            err = (msg.get("error") or {}).get("message") or "the turn failed"
            return [{"type": "error", "message": one_line(err, 600)},
                    {"type": "done", "session": state.get("session"), "backend": "codex"}]
        if kind == "error":
            text = str(msg.get("message", ""))
            # Codex reports its own retries as top-level errors ("Reconnecting...
            # 2/5 ..."). They are progress, not failure; a real failure arrives
            # as turn.failed or as a non-zero exit, which run() reports.
            if text.startswith("Reconnecting"):
                return []
            return [{"type": "error", "message": one_line(text, 600)}]

        if kind not in ("item.started", "item.updated", "item.completed"):
            return []
        item = msg.get("item") or {}
        itype = item.get("type")
        seen = state.setdefault("seen", set())

        if itype == "agent_message":
            # Codex emits a reply whole, at item.completed. No deltas to merge.
            if kind == "item.completed" and item.get("text"):
                return [{"type": "text", "delta": item["text"]}]
            return []
        if itype == "command_execution":
            # Said once, when it starts: a long command should show up while it
            # runs, not after. A refusal is reported again, because that is news.
            ident = item.get("id")
            command = item.get("command")
            if isinstance(command, list):
                command = " ".join(map(str, command))
            if kind == "item.completed" and item.get("status") == "declined":
                return [{"type": "tool", "name": "shell", "summary": one_line(command),
                         "denied": True}]
            if ident in seen:
                return []
            seen.add(ident)
            return [{"type": "tool", "name": "shell", "summary": one_line(command)}]
        if itype == "file_change" and kind == "item.completed":
            changes = item.get("changes") or []
            summary = ", ".join(f"{c.get('kind', '?')} {c.get('path', '?')}"
                                for c in changes if isinstance(c, dict))
            return [{"type": "tool", "name": "edit", "summary": one_line(summary)}]
        if itype == "mcp_tool_call" and kind == "item.started":
            return [{"type": "tool", "name": f"{item.get('server', '?')}.{item.get('tool', '?')}",
                     "summary": one_line(json.dumps(item.get("arguments") or {}))}]
        if itype == "web_search" and kind == "item.started":
            return [{"type": "tool", "name": "web_search", "summary": one_line(item.get("query"))}]
        # reasoning, todo_list, and item-level "error" (a warning, e.g. falling
        # back from WebSockets to HTTPS) are not part of the answer.
        return []


BACKENDS = {"claude": Claude, "codex": Codex}


def available() -> dict:
    """{backend: path or None}, read fresh each call so installing a CLI while
    the server runs is picked up without a restart."""
    return {name: b.available() for name, b in BACKENDS.items()}


# --------------------------------------------------------------------------
# Running one turn
# --------------------------------------------------------------------------


def stop(proc: subprocess.Popen) -> None:
    """Terminate the CLI and everything it started. It runs in its own process
    group (start_new_session) precisely so a Bash child goes down with it."""
    if proc.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run(backend, argv: list[str], cwd: Path, env: dict | None = None,
        gone: Callable[[], bool] = lambda: False,
        timeout: float = TURN_TIMEOUT) -> Iterator[dict]:
    """Run one turn and yield common events, ending with exactly one `done`.

    The backend's own end-of-turn marker is folded into that final `done`
    rather than forwarded, so the event that says "finished" is the one written
    after the process has actually exited — which is what the server needs
    before it can decide whether to rebuild.

    `gone()` is polled while the CLI is quiet, so a closed browser tab stops a
    turn that is thinking, not only one that is printing. Closing the generator
    (the server does, when a write to the client fails) stops it too.
    """
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            start_new_session=True)
    except OSError as exc:
        yield {"type": "error", "message": f"could not start {backend.name}: {exc}"}
        yield {"type": "done", "session": None, "backend": backend.name,
               "ok": False, "code": None}
        return
    lines: queue.Queue = queue.Queue()
    stderr: deque = deque(maxlen=40)

    def pump_out():
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    def pump_err():
        for raw in proc.stderr:
            stderr.append(raw.rstrip("\n"))

    for target in (pump_out, pump_err):
        threading.Thread(target=target, daemon=True).start()

    state: dict = {}
    errored = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                if gone():
                    return
                if time.monotonic() > deadline:
                    stop(proc)
                    errored = True
                    yield {"type": "error",
                           "message": f"stopped: the turn ran past {timeout // 60:.0f} minutes"}
                    break
                continue
            if raw is None:
                break
            for event in backend.events(raw, state):
                if event["type"] == "done":
                    state["session"] = event.get("session") or state.get("session")
                    continue
                errored = errored or event["type"] == "error"
                yield event
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            stop(proc)
            code = proc.returncode
        if code != 0 and not errored:
            tail = "\n".join(l for l in stderr if l.strip())[-1500:]
            yield {"type": "error", "message":
                   f"{backend.name} exited {code}" + (f": {tail}" if tail else "")}
        yield {"type": "done", "session": state.get("session"),
               "backend": backend.name, "ok": code == 0, "code": code}
    finally:
        stop(proc)
