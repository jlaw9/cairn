#!/usr/bin/env python3
"""Make every Claude session on this machine see the graph. Dry run by default.

The gap: `README` says to add one line to each project repo's `CLAUDE.md`, and
that step is the one that decides whether the graph gets maintained. It is also
the step that doesn't happen — it covers the repos you remembered when you set
them up, it needs redoing for every new repo, and a session started in a
directory with no `CLAUDE.md` at all gets nothing.

Three machine-level installs fix that once, and none of them is per-project:

1. **`~/.claude/CLAUDE.md`** — user-level memory, loaded in every session in
   every directory. Gets a marked block naming the graph and the four commands.
2. **A `SessionStart` hook** running `cairn session_hook`, which pulls and then
   returns the graph's current state as `additionalContext`. This is the part a
   pointer cannot do: an agent mid-task doesn't go and read a pointer, but state
   already in context gets used. Plus a `SessionEnd` hook that says what is
   unpushed, because that is the other half of the two-machine habit gap.
3. **The slash commands**, symlinked into `~/.claude/commands` so `/log`,
   `/standup`, `/capture`, `/triage` and `/digest` resolve from any repo rather
   than only from a session rooted in this one.

    cairn install_context              # say what would change, touch nothing
    cairn install_context --apply
    cairn install_context --remove     # take the managed block and hooks back out
    cairn install_context --project ~/work/polyid --apply   # one project only

**Scope is a fact on disk, not a setting.** Machine-wide, the three installs
land under `~/.claude` and every session on the machine sees the graph. With
`--project <path>` the same three land inside that project instead — its
`CLAUDE.local.md` and `.claude/settings.local.json` (the two files Claude Code
reads but git convention leaves untracked, so this machine's absolute paths
never reach collaborators) and its `.claude/commands/` — and only sessions
started there see it. `doctor` reads both back; nothing has to
remember which was chosen.

**Dry run by default, like `sync_issues`.** These are files outside the repo
that affect every session on the machine, so the default has to be to print the
diff and let a human agree to it.

Everything written is inside markers, so `--remove` is exact and re-running
`--apply` replaces rather than appends. The one thing this never touches is a
setting it did not write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import policy  # stdlib only

#: The tool. Where bin/cairn, the skills and the slash commands live.
TOOL_ROOT = Path(__file__).resolve().parent.parent
#: The graph. Separate repo since the split; falls back to a pre-split clone.
GRAPH_ROOT = Path(os.environ.get("CAIRN_ROOT") or TOOL_ROOT).expanduser()

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
MEMORY = CLAUDE_DIR / "CLAUDE.md"
SETTINGS = CLAUDE_DIR / "settings.json"
COMMANDS = CLAUDE_DIR / "commands"


def scope_to(project: Path | None) -> None:
    """Point the three targets at one project instead of the machine.

    A project's `CLAUDE.md` is the memory file; `.claude/settings.local.json`
    holds the hooks, because it is the file Claude Code treats as per-checkout
    and leaves out of git — a hook command carrying this machine's absolute
    path has no business in a shared `settings.json`; and `.claude/commands/`
    makes the slash commands resolve there and nowhere else.
    """
    global CLAUDE_DIR, MEMORY, SETTINGS, COMMANDS
    if project is None:
        return
    CLAUDE_DIR = project / ".claude"
    # CLAUDE.local.md, not CLAUDE.md: the block carries this machine's absolute
    # paths, and Claude Code reads the .local file while git convention keeps it
    # out of the shared repo — the same reason the hooks go to settings.local.json.
    MEMORY = project / "CLAUDE.local.md"
    SETTINGS = CLAUDE_DIR / "settings.local.json"
    COMMANDS = CLAUDE_DIR / "commands"

BEGIN = "<!-- cairn:begin — managed by `cairn install_context`; edits here are overwritten -->"
END = "<!-- cairn:end -->"

#: Stamped into each hook entry so --remove and re---apply can find exactly the
#: entries this wrote, and nothing else. A hook has no id field, so the marker
#: has to live in the command string — which is fine, since the command is the
#: thing being identified.
HOOK_MARK = "session_hook"


def memory_block(tool: Path, graph: Path) -> str:
    """The user-level memory block.

    Short on purpose. It is loaded in every session in every directory, so it
    carries the pointer and the four verbs and stops; the state and the detail
    come from the SessionStart hook and from `standup`, which are read on demand.
    """
    return f"""{BEGIN}
## Cairn — the research record

Research activity — experiments, dead ends, open threads, deadlines — is
recorded in **Cairn**, a git-backed graph. The tool is at `{tool}`
(`$CAIRN_PATH`); the graph itself is at `{graph}` (`$CAIRN_ROOT`). It exists so
that "did we already try this, and what happened?" has an answer.

- **Before proposing work**, read what the project already settled:
  `{tool}/bin/cairn standup --project <key>`. A `dead` node is a claim already
  refuted with the reason attached — cite it rather than re-running it.
- **After doing work**, record it: `/log` from inside the project repo.
- **A thought you don't want to file**: `{tool}/bin/cairn capture "..."`.
  Never refuses, never prompts; lands in `inbox/` for later triage.
- **A reaction to an existing node**: `{tool}/bin/cairn note <node-id> "..."`.

Follow the graph's **commit policy**, which the session-start context states and
`{tool}/bin/cairn policy` prints: `ask` means draft, show, then commit; `auto`
means commit the node you wrote about work you did and say so. Anything written
unprompted goes to `inbox/` either way. Full conventions in `{tool}/CLAUDE.md`;
the path-addressed skills are under `{tool}/skills/`.
{END}"""


def hook_entries(root: Path) -> dict:
    binary = f"{root}/bin/cairn"
    return {
        "SessionStart": {
            "hooks": [{
                "type": "command",
                "command": f"{binary} {HOOK_MARK}",
                "timeout": 30,
                "statusMessage": "Reading the research graph",
            }],
        },
        "SessionEnd": {
            "hooks": [{
                "type": "command",
                "command": f"{binary} {HOOK_MARK} --end",
                "timeout": 20,
            }],
        },
    }


# --------------------------------------------------------------------------
# Memory file
# --------------------------------------------------------------------------


def plan_memory(tool: Path, graph: Path) -> tuple[str, str]:
    """(verdict, new text). Verdict is 'ok', 'add' or 'update'."""
    wanted = memory_block(tool, graph)
    if not MEMORY.exists():
        return "add", wanted + "\n"
    current = MEMORY.read_text(encoding="utf-8")
    if BEGIN not in current:
        joiner = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
        return "add", current + joiner + wanted + "\n"
    head, _, rest = current.partition(BEGIN)
    _, _, tail = rest.partition(END)
    replaced = head + wanted + tail
    return ("ok" if replaced == current else "update"), replaced


def plan_memory_removal() -> tuple[str, str]:
    if not MEMORY.exists():
        return "ok", ""
    current = MEMORY.read_text(encoding="utf-8")
    if BEGIN not in current:
        return "ok", current
    head, _, rest = current.partition(BEGIN)
    _, _, tail = rest.partition(END)
    return "update", (head.rstrip("\n") + "\n" + tail.lstrip("\n")).lstrip("\n")


# --------------------------------------------------------------------------
# Settings file
# --------------------------------------------------------------------------


def load_settings() -> tuple[dict, str]:
    """(parsed settings, error). A malformed file is reported, never overwritten.

    Silently rewriting a settings.json that failed to parse would discard every
    other setting in it, and a broken settings.json already disables all of them
    — so the useful thing is to say which file to fix.
    """
    if not SETTINGS.exists():
        return {}, ""
    try:
        text = SETTINGS.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"cannot read {SETTINGS}: {exc}"
    if not text.strip():
        return {}, ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"{SETTINGS} is not valid JSON ({exc}) — fix it before installing"
    if not isinstance(parsed, dict):
        return {}, f"{SETTINGS} is not a JSON object"
    return parsed, ""


def strip_ours(hooks: dict) -> tuple[dict, int]:
    """Drop every hook entry this tool wrote. Returns (hooks, how many removed)."""
    removed = 0
    out = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept = []
        for group in groups:
            inner = (group or {}).get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list) and inner and all(
                isinstance(h, dict) and HOOK_MARK in str(h.get("command", ""))
                for h in inner
            ):
                removed += 1
                continue
            kept.append(group)
        if kept:
            out[event] = kept
    return out, removed


def plan_settings(root: Path, remove: bool) -> tuple[str, dict, list[str]]:
    """(verdict, new settings, notes). Merges; never replaces the file."""
    settings, error = load_settings()
    if error:
        return "error", {}, [error]

    new = json.loads(json.dumps(settings))          # deep copy, stdlib only
    hooks = new.get("hooks") if isinstance(new.get("hooks"), dict) else {}
    hooks, dropped = strip_ours(hooks)
    notes = []
    if dropped:
        notes.append(f"replacing {dropped} existing cairn hook entr(y/ies)")

    if not remove:
        for event, entry in hook_entries(root).items():
            hooks.setdefault(event, [])
            hooks[event].append(entry)
            # Other people's hooks on the same event are left exactly where they
            # are; appending means ours runs alongside rather than instead.
            others = len(hooks[event]) - 1
            if others:
                notes.append(f"{event}: {others} other hook group(s) left in place")

    if hooks:
        new["hooks"] = hooks
    else:
        new.pop("hooks", None)

    verdict = "ok" if new == settings else ("update" if settings else "add")
    return verdict, new, notes


# --------------------------------------------------------------------------
# Slash commands
# --------------------------------------------------------------------------


def plan_commands(root: Path) -> list[tuple[str, Path, Path]]:
    """[(verdict, link, target)] for every command in this repo."""
    out = []
    for source in sorted((root / ".claude" / "commands").glob("*.md")):
        link = COMMANDS / source.name
        try:
            same = link.resolve() == source.resolve()
        except (OSError, RuntimeError):        # a dangling or looping link
            same = False
        if same:
            # Either already linked, or the target *is* the source file — never
            # unlink that, or the command is gone and a self-loop is left behind.
            out.append(("ok", link, source))
        elif link.exists() or link.is_symlink():
            out.append(("update", link, source))
        else:
            out.append(("add", link, source))
    return out


# --------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn install_context",
        description="Make every Claude session on this machine see the graph.")
    p.add_argument("--apply", action="store_true", help="actually write the changes")
    p.add_argument("--remove", action="store_true",
                   help="take the managed block and the cairn hooks back out")
    p.add_argument("--no-hooks", action="store_true",
                   help="memory block and commands only; leave settings.json alone")
    p.add_argument("--project", metavar="PATH",
                   help="wire one project directory instead of every session on the machine")
    args = p.parse_args()

    project = None
    if args.project:
        project = Path(args.project).expanduser().resolve()
        if not project.is_dir():
            print(f"cairn install_context: {project} is not a directory", file=sys.stderr)
            return 2
        if project == TOOL_ROOT.resolve():
            print("cairn install_context: --project points at the Cairn tool itself. The tool\n"
                  "  already holds the commands; wire a *project* repo, or use machine scope.",
                  file=sys.stderr)
            return 2
        scope_to(project)

    root = TOOL_ROOT
    print(f"cairn install_context — tool {root}")
    print(f"                        graph {GRAPH_ROOT}")
    print(f"  scope:  {'project ' + str(project) if project else 'every session on this machine'}")
    print(f"  target: {CLAUDE_DIR}\n")

    mem_verdict, mem_text = (plan_memory_removal() if args.remove
                             else plan_memory(root, GRAPH_ROOT))
    set_verdict, set_new, set_notes = ("skip", {}, [])
    if not args.no_hooks:
        set_verdict, set_new, set_notes = plan_settings(root, args.remove)
    cmds = [] if args.remove else plan_commands(root)

    label = {"ok": "ok     ", "add": "ADD    ", "update": "UPDATE ",
             "error": "ERROR  ", "skip": "skip   "}

    print(f"  {label[mem_verdict]}{MEMORY}")
    if mem_verdict != "ok":
        print(f"         {'removing' if args.remove else 'installing'} the "
              f"cairn:begin/end block "
              f"({len(memory_block(root, GRAPH_ROOT).splitlines())} lines)")

    print(f"  {label[set_verdict]}{SETTINGS}")
    for note in set_notes:
        print(f"         {note}")
    if set_verdict == "error":
        return 1
    if set_verdict != "ok" and not args.remove:
        print("         SessionStart -> cairn session_hook  (pull + inject graph state)")
        print("         SessionEnd   -> cairn session_hook --end  (what is unpushed)")

    for verdict, link, source in cmds:
        print(f"  {label[verdict]}{link}  ->  {source.name}")

    changing = [mem_verdict, set_verdict] + [v for v, _, _ in cmds]
    if all(v in ("ok", "skip") for v in changing):
        print("\nNothing to change. This machine is already wired up.")
        return 0

    if not args.apply:
        print("\nDry run. Nothing written. Re-run with --apply.")
        return 0

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    COMMANDS.mkdir(parents=True, exist_ok=True)

    if mem_verdict != "ok":
        MEMORY.write_text(mem_text, encoding="utf-8")
        print(f"\nwrote {MEMORY}")
    if set_verdict not in ("ok", "skip"):
        # Two-space indent to match what Claude Code writes, so a later hand-edit
        # of this file doesn't show up as a whole-file reformat in any diff.
        SETTINGS.write_text(json.dumps(set_new, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {SETTINGS}")
    for verdict, link, source in cmds:
        if verdict == "ok":
            continue
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(source)
        print(f"linked {link.name}")

    if not args.remove and project is not None:
        print(f"\nKeep {MEMORY.name}, .claude/settings.local.json and .claude/commands/ out of")
        print("that repo's git (they carry this machine's paths); CLAUDE.local.md and")
        print("settings.local.json are conventionally ignored already.")
    if not args.remove:
        print("\nThe hooks are read when a session starts, so this takes effect in the")
        print("next session, not this one. `cairn session_hook --dry-run` shows exactly")
        print("what a new session will be told.")
        if os.environ.get("CAIRN_PATH", "") != str(root):
            print("\nAlso add this to your shell profile, which the slash commands read:")
            print(f"  export CAIRN_PATH={root}")
        if not os.environ.get("CAIRN_ROOT"):
            print("\nAnd this, which is how the tool finds your graph. Without it every")
            print("read reports an empty graph, and an empty graph reads as 'not tried':")
            print(f"  export CAIRN_ROOT={GRAPH_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
