#!/usr/bin/env python3
"""Set up Cairn on this machine: `doctor`'s forward mode.

    cairn onboard                      # ask the three questions, act, then run doctor
    cairn onboard --yes                # take every default, ask nothing
    cairn onboard --graph ~/research-graph --commit-mode auto --scope machine

Three questions, each of whose answer becomes a fact on disk that `doctor`
reads back — there is no config file (2026-08-27-cairn-onboarding-and-node-
location: onboarding asks only what cannot be inferred, and a stored preference
is a second copy of a truth that can disagree with the first):

1. **Where is your graph?** Detected from `CAIRN_ROOT` when it already points at
   one; otherwise created with `cairn init`.
2. **Commit policy** — `ask` (an agent drafts, shows, waits) or `auto` (an agent
   commits the nodes it writes about work it did; you edit afterward). One line
   in the graph's own `CLAUDE.md`, changed later with `cairn policy`.
3. **Which sessions see the graph?** Every Claude Code session on this machine
   (`install_context --apply`), or only sessions started in one project
   directory (`install_context --project <path> --apply`). Scope is where the
   hook landed, nothing more.

Then one optional thing: if the `ov` command (OpenViking) is on this machine,
offer to register the graph with it so its retrieval covers your research
record. Cairn works fully without it.

What it refuses to ask: where nodes should live. Nodes stay in the one graph;
a project repo gets a generated view (`cairn export`). That decision is cheap to
make badly, silently lossy and irreversible, so it is explained, not offered.

Imports nothing from lib: this is the first command a new machine runs, and it
must not be able to fail on a missing PyYAML — everything that needs one is
shelled out to `bin/cairn`, which finds an interpreter that has it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import policy  # stdlib only

TOOL_ROOT = Path(__file__).resolve().parent.parent
CAIRN = TOOL_ROOT / "bin" / "cairn"
DEFAULT_GRAPH = Path.home() / "research-graph"


class Answers:
    """Prompt, or take the default when `--yes` or the flag already answered it."""

    def __init__(self, assume_yes: bool):
        self.assume_yes = assume_yes
        self.interactive = sys.stdin.isatty() and sys.stdout.isatty()

    def ask(self, prompt: str, default: str, choices: tuple[str, ...] | None = None) -> str:
        if self.assume_yes:
            return default
        if not self.interactive:
            sys.exit("cairn onboard: not a terminal — pass --yes to take the defaults, or "
                     "answer with flags (--graph, --commit-mode, --scope, --openviking)")
        while True:
            try:
                raw = input(f"{prompt} [{default}] ").strip()
            except EOFError:
                return default
            value = raw or default
            if choices is None or value in choices:
                return value
            print(f"  one of: {', '.join(choices)}")

    def confirm(self, prompt: str, default: bool) -> bool:
        value = self.ask(prompt + (" (Y/n)" if default else " (y/N)"), "y" if default else "n")
        return value.lower().startswith("y")


def run(*args: str, env: dict | None = None) -> int:
    print(f"  $ {' '.join(str(a) for a in args)}")
    try:
        return subprocess.run([str(a) for a in args], env=env, timeout=600).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  failed: {exc}")
        return 1


def has_graph(path: Path) -> bool:
    return (path / "nodes").is_dir()


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn onboard", description="Set up Cairn on this machine.")
    p.add_argument("--graph", metavar="PATH", help="the graph repo (created if absent)")
    p.add_argument("--commit-mode", choices=policy.MODES, help="ask or auto")
    p.add_argument("--scope", metavar="machine|project[=PATH]",
                   help="which sessions see the graph; project defaults to the cwd")
    p.add_argument("--openviking", choices=("yes", "no"),
                   help="register the graph with OpenViking if `ov` is installed")
    p.add_argument("--allow-nested", action="store_true",
                   help="let the graph sit inside another git repo (passed to cairn init)")
    p.add_argument("--yes", action="store_true", help="take every default; ask nothing")
    args = p.parse_args()
    a = Answers(args.yes)

    print(f"cairn onboard — tool {TOOL_ROOT}\n")

    # 1. The graph.
    env_root = os.environ.get("CAIRN_ROOT", "")
    if args.graph:
        graph = Path(args.graph).expanduser().resolve()
    elif env_root and has_graph(Path(env_root).expanduser()):
        graph = Path(env_root).expanduser().resolve()
        print(f"1. Graph: {graph}  (from CAIRN_ROOT)")
    else:
        print("1. Your graph is its own git repo, outside every project repo. One graph")
        print("   spans all your projects; the cross-project edges are the part worth having.")
        graph = Path(a.ask("   Where should it live?", str(env_root or DEFAULT_GRAPH))).expanduser().resolve()
    env = dict(os.environ, CAIRN_ROOT=str(graph))

    # 2. Commit policy — asked before init so init can write it.
    print()
    print("2. Commit policy. `ask`: an agent drafts a node, shows it, and commits only")
    print("   after you confirm — nothing enters the graph unread. `auto`: an agent")
    print("   commits the nodes it writes about work it did and tells you; you edit")
    print("   afterward, and `cairn review --list` shows what nobody has read yet.")
    mode = args.commit_mode or a.ask("   ask or auto?", policy.DEFAULT, policy.MODES)

    print()
    if has_graph(graph):
        print(f"   {graph} already holds a graph.")
        current = policy.read_commit_mode(graph)
        if current != mode:
            if run(CAIRN, "policy", mode, env=env) != 0:
                return 1
        else:
            print(f"   commit_mode: {mode} (unchanged)")
        # Hooks, in case this clone predates them or was cloned rather than init'd.
        run(CAIRN, "install_hooks", graph, env=env)
    else:
        init_args = [CAIRN, "init", graph, "--commit-mode", mode]
        if args.allow_nested:
            init_args.append("--allow-nested")
        if run(*init_args) != 0:
            print("  (a graph inside another git repo is refused; --allow-nested overrides,")
            print("   but keeping it outside every project repo is the point)")
            return 1

    # 3. Scope.
    print()
    print("3. Which sessions should see the graph?")
    print("   machine  — every Claude Code session on this machine (a SessionStart hook")
    print("              in ~/.claude, the slash commands, a block in ~/.claude/CLAUDE.md)")
    print("   project  — only sessions started in one project directory (the same three,")
    print("              inside that project; nothing outside it changes)")
    scope = args.scope or a.ask("   machine or project?", "machine")
    doctor_cwd = None
    if scope == "machine":
        code = run(CAIRN, "install_context", "--apply", env=env)
    elif scope.startswith("project"):
        _, _, where = scope.partition("=")
        if not where and not args.scope:
            where = a.ask("   Which project directory?", os.getcwd())
        project = Path(where or os.getcwd()).expanduser().resolve()
        if project == TOOL_ROOT:
            sys.exit("cairn onboard: the project directory is the Cairn tool itself — run this "
                     "from the project you want wired, or pass --scope project=<path>")
        doctor_cwd = project
        code = run(CAIRN, "install_context", "--project", project, "--apply", env=env)
    else:
        sys.exit(f"cairn onboard: --scope must be machine or project[=PATH], not {scope!r}")
    if code != 0:
        return 1

    # 4. OpenViking, only if it is here.
    print()
    if shutil.which("ov"):
        print("4. OpenViking (`ov`) is installed. Registering the graph with it lets its")
        print("   retrieval surface your research record in every session it serves.")
        want = args.openviking or ("yes" if a.confirm("   Register the graph?", True) else "no")
        if want == "yes":
            run(CAIRN, "openviking", "push", "--apply", env=env)
    else:
        print("4. OpenViking: not installed. Optional — Cairn is complete without it. See")
        print("   docs/openviking.md if you want shared agent memory around the graph.")

    # Where nodes live is explained, never asked.
    print()
    print("Nodes stay in the one graph. A project repo that wants to show what was tried")
    print("gets a generated view: `cairn export --project <key> --dest <repo>/docs/research`.")

    print()
    if os.environ.get("CAIRN_PATH") != str(TOOL_ROOT) or os.environ.get("CAIRN_ROOT") != str(graph):
        print("Add these to your shell profile — the tool, then your graph:")
        print(f"  export CAIRN_PATH={TOOL_ROOT}")
        print(f"  export CAIRN_ROOT={graph}")
        print()
    print("An empty graph means nothing for months, and a missing node then means 'we")
    print("had not started', not 'not tried'. Backfill before trusting a gap:")
    print(f"  {TOOL_ROOT}/docs/backfill.md")
    print()
    # doctor reads a project-scoped hook from the cwd, so run it where it landed.
    if doctor_cwd is not None:
        os.chdir(doctor_cwd)
    run(TOOL_ROOT / "scripts" / "doctor.sh", env=env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
