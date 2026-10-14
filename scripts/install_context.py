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
    cairn install_context --codex      # the same for the OpenAI Codex CLI

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

#: The tool. Where bin/cairn, the skills and the slash commands live.
TOOL_ROOT = Path(__file__).resolve().parent.parent
#: The graph. Separate repo since the split; falls back to a pre-split clone.
GRAPH_ROOT = Path(os.environ.get("CAIRN_ROOT") or TOOL_ROOT).expanduser()

CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
MEMORY = CLAUDE_DIR / "CLAUDE.md"
SETTINGS = CLAUDE_DIR / "settings.json"
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

Research activity across all projects — experiments, dead ends, open threads,
deadlines — is recorded in **Cairn**, a git-backed graph. The tool is at
`{tool}` (`$CAIRN_PATH`); the graph itself is at `{graph}` (`$CAIRN_ROOT`). It
exists so that "did we already try this, and what happened?" has an answer.

- **Before proposing work**, read what the project already settled:
  `{tool}/bin/cairn standup --project <key>`. A `dead` node is a claim already
  refuted with the reason attached — cite it rather than re-running it.
- **After doing work**, record it: `/log` from inside the project repo.
- **A thought you don't want to file**: `{tool}/bin/cairn capture "..."`.
  Never refuses, never prompts; lands in `inbox/` for later triage.
- **A reaction to an existing node**: `{tool}/bin/cairn note <node-id> "..."`.

Never commit a node Jeff hasn't seen — draft it, show it, then commit. Anything
written unprompted goes to `inbox/` instead. Full conventions in
`{tool}/CLAUDE.md`; the path-addressed skills are under `{tool}/skills/`.
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
        if link.is_symlink() and link.resolve() == source.resolve():
            out.append(("ok", link, source))
        elif link.exists() or link.is_symlink():
            out.append(("update", link, source))
        else:
            out.append(("add", link, source))
    return out


# --------------------------------------------------------------------------
# Codex (`--codex`)
# --------------------------------------------------------------------------
#
# What Codex reads, as verified against Codex CLI 0.162.1 on 2026-10-14 (see
# docs/chat-backends.md): skills are directories holding a SKILL.md, found
# under `$HOME/.agents/skills` among other roots, and symlinked skill folders
# are followed; instructions come from AGENTS.md, walked from the git root down
# to the working directory. So the install is the same shape as Claude's —
# symlinks so the skills stay current, and a marked block so it is exact to
# remove — just in two different places.
#
# No hook is installed. Codex 0.162.1 has a SessionStart hook, but it runs only
# after the user has reviewed and trusted that exact definition in the TUI, so
# writing one here would install something that silently does nothing.


def agents_block() -> str:
    """The AGENTS.md pointer. Machine-neutral, because this file lives in the
    graph repo and every collaborator's clone of the tool is somewhere else."""
    return f"""{BEGIN}
## Cairn

This directory is a Cairn research graph. Before writing anything here, read
`CLAUDE.md` in this directory, then the conventions it points to,
`$CAIRN_PATH/CLAUDE.md` and `$CAIRN_PATH/docs/schema.md`. They are written for
Claude Code and bind every agent: write only through `$CAIRN_PATH/bin/cairn`,
never hand-edit a node's frontmatter, and never commit a node a human has not
read. The skills are `cairn-capture`, `cairn-resume` and `cairn-log`.
{END}"""


def plan_codex_block(path: Path, remove: bool) -> tuple[str, str]:
    """(verdict, new text) for the AGENTS.md block: 'ok', 'add' or 'update'.
    The same marker logic as the memory block, kept separate so this section
    stays self-contained."""
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if remove:
        if BEGIN not in current:
            return "ok", current
        head, _, rest = current.partition(BEGIN)
        _, _, tail = rest.partition(END)
        return "update", (head.rstrip("\n") + "\n" + tail.lstrip("\n")).lstrip("\n")
    wanted = agents_block()
    if not path.exists():
        return "add", wanted + "\n"
    if BEGIN not in current:
        joiner = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
        return "add", current + joiner + wanted + "\n"
    head, _, rest = current.partition(BEGIN)
    _, _, tail = rest.partition(END)
    replaced = head + wanted + tail
    return ("ok" if replaced == current else "update"), replaced


def codex_skills_dir() -> Path:
    return Path.home() / ".agents" / "skills"


def plan_skills(tool: Path, remove: bool) -> list[tuple[str, Path, Path]]:
    """[(verdict, link, source)] for every skill in this repo.

    A real directory where a link would go is somebody's own skill: it is
    reported as a conflict and left alone, never replaced.
    """
    out = []
    for skill in sorted(p for p in (tool / "skills").iterdir() if (p / "SKILL.md").is_file()):
        link = codex_skills_dir() / skill.name
        ours = link.is_symlink() and link.resolve() == skill.resolve()
        if remove:
            out.append(("remove" if ours else "ok", link, skill))
        elif ours:
            out.append(("ok", link, skill))
        elif link.is_symlink():
            out.append(("update", link, skill))
        elif link.exists():
            out.append(("conflict", link, skill))
        else:
            out.append(("add", link, skill))
    return out


def install_codex(args) -> int:
    root, agents = TOOL_ROOT, GRAPH_ROOT / "AGENTS.md"
    print(f"cairn install_context --codex — tool {root}")
    print(f"                                graph {GRAPH_ROOT}\n")

    verdict, text = plan_codex_block(agents, args.remove)
    skills = plan_skills(root, args.remove)
    label = {"ok": "ok      ", "add": "ADD     ", "update": "UPDATE  ",
             "remove": "REMOVE  ", "conflict": "CONFLICT"}
    print(f"  {label[verdict]}{agents}")
    if verdict != "ok":
        print(f"          {'removing' if args.remove else 'installing'} the "
              f"cairn:begin/end pointer to CLAUDE.md")
    for v, link, source in skills:
        print(f"  {label[v]}{link}  ->  {source}")
        if v == "conflict":
            print("          a directory that is not ours is already there; left alone")

    changing = [verdict] + [v for v, _, _ in skills if v != "conflict"]
    if all(v == "ok" for v in changing):
        print("\nNothing to change. Codex on this machine already sees the graph.")
        return 0
    if args.dry_run or not args.apply:
        print("\nDry run. Nothing written. Re-run with --apply.")
        return 0

    if verdict != "ok":
        agents.write_text(text, encoding="utf-8")
        print(f"\nwrote {agents}")
    for v, link, source in skills:
        if v in ("ok", "conflict"):
            continue
        if link.is_symlink():
            link.unlink()
        if v != "remove":
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(source)
        print(f"{'unlinked' if v == 'remove' else 'linked'} {link}")
    if not args.remove:
        print("\nAGENTS.md is a file in the graph repo, uncommitted: commit it so every")
        print("clone gets it. Codex has no Cairn session hook, so `cairn sync` at the")
        print("start of a session is yours to run.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn install_context",
        description="Make every Claude session on this machine see the graph.")
    p.add_argument("--apply", action="store_true", help="actually write the changes")
    p.add_argument("--remove", action="store_true",
                   help="take the managed block and the cairn hooks back out")
    p.add_argument("--no-hooks", action="store_true",
                   help="memory block and commands only; leave settings.json alone")
    p.add_argument("--codex", action="store_true",
                   help="wire up the OpenAI Codex CLI instead: skills into "
                        "~/.agents/skills, an AGENTS.md pointer in the graph root")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would change and touch nothing (the default)")
    args = p.parse_args()
    if args.codex:
        return install_codex(args)
    if args.dry_run:
        args.apply = False

    root = TOOL_ROOT
    print(f"cairn install_context — tool {root}")
    print(f"                        graph {GRAPH_ROOT}")
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
