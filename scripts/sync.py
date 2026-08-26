#!/usr/bin/env python3
"""Keep two machines' clones in step, and say what still needs a human.

The laptop/kestrel friction was never a storage problem — that question was
asked and refuted in 2026-08-21-cairn-database-question. What actually goes
wrong is a habit gap at two moments: forgetting `git pull --rebase` before
working, and forgetting to push after. Both are silent, and the second one is
the expensive one, because the work is written down and simply not visible from
the other machine.

So this automates the half that is safe to automate and *reports* the half that
isn't:

    cairn sync              # pull, then say what still needs you
    cairn sync --check      # no network; report local state only
    cairn sync --push       # pull, regenerate build/, commit build/, push
    cairn sync --quiet      # speak only if something needs attention

**It never commits a node.** Design decision 6 says nothing enters the graph
unreviewed, and an auto-commit is exactly the mechanism that would break it. It
commits `build/` and nothing else, because `build/` is generated — regenerating
it is the documented way to resolve it, so a machine is free to overwrite it.

That last point is also the one merge conflict this repo can actually produce.
Nodes are separate append-only files, so two writers do not collide; `build/`
is one file both machines rewrite. When a rebase stops *only* on `build/`, this
resolves it the way CLAUDE.md already says to — regenerate, don't merge — and
carries on. A conflict anywhere else is left alone for a human, because
anywhere else it means something interesting happened.

Deliberately not an error when the network is down. A login node behind a
firewall, a laptop on a plane: `cairn sync` reporting "couldn't reach the
remote" and exiting 0 is correct, because the alternative is a session-start
hook that fails and gets removed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# No `import lib`, for the same reason capture.py has none: this runs at session
# start on whatever machine you happen to be on, and a sync that cannot pull
# because PyYAML is missing somewhere is worse than useless. The one step that
# genuinely needs a working interpreter — regenerating build/ — is shelled out
# to bin/cairn, which picks its own.
REPO_ROOT = Path(os.environ.get("CAIRN_ROOT") or Path(__file__).resolve().parent.parent)


def git(*args: str, timeout: int = 120) -> tuple[int, str]:
    """Run git in the graph repo. Returns (returncode, combined output)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return 127, "git not found on PATH"
    except subprocess.SubprocessError as exc:
        return 1, f"git {' '.join(args)} failed: {exc}"
    return done.returncode, (done.stdout + done.stderr).strip()


def out(*args: str) -> str:
    """Just the stdout of a git command, empty on failure."""
    code, text = git(*args)
    return text if code == 0 else ""


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------


def porcelain() -> list[tuple[str, str]]:
    """[(xy, path), ...] from `git status --porcelain`."""
    entries = []
    for line in out("status", "--porcelain").splitlines():
        if len(line) > 3:
            # Renames read "R  old -> new"; the destination is the one that matters.
            path = line[3:].split(" -> ")[-1].strip().strip('"')
            entries.append((line[:2], path))
    return entries


def upstream() -> str:
    return out("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")


def ahead_behind() -> tuple[int, int]:
    """Commits (ahead, behind) relative to the tracked upstream."""
    if not upstream():
        return 0, 0
    counts = out("rev-list", "--left-right", "--count", "@{upstream}...HEAD").split()
    if len(counts) != 2:
        return 0, 0
    behind, ahead = counts
    return int(ahead), int(behind)


def build_is_stale() -> bool:
    """Is any node newer than the rendered graph?

    mtime rather than git, because the question is "did someone edit a node and
    not rebuild", and an uncommitted edit is exactly the case that matters.
    """
    html = REPO_ROOT / "build" / "graph.html"
    if not html.exists():
        return True
    newest = 0.0
    for folder in ("nodes", "papers"):
        for path in (REPO_ROOT / folder).glob("*.md"):
            newest = max(newest, path.stat().st_mtime)
    return newest > html.stat().st_mtime


def unreviewed() -> tuple[list[str], list[str]]:
    """(modified node/paper files, untracked ones) — i.e. drafts awaiting review.

    Untracked is the interesting bucket. A node file that exists and has never
    been committed is almost always a draft an agent wrote and nobody has read
    yet, which is precisely the thing design decision 6 says must not slip in
    unnoticed. Naming it every session is how it stops being forgotten.
    """
    changed, new = [], []
    for xy, path in porcelain():
        if not (path.startswith("nodes/") or path.startswith("papers/")):
            continue
        (new if xy == "??" else changed).append(path)
    return sorted(changed), sorted(new)


# --------------------------------------------------------------------------
# Pull, with the one conflict this repo can produce
# --------------------------------------------------------------------------


def conflicted() -> list[str]:
    return [p for p in out("diff", "--name-only", "--diff-filter=U").splitlines() if p]


def regenerate() -> bool:
    """`cairn build`, via the dispatcher so the interpreter question stays solved."""
    try:
        done = subprocess.run(
            [str(REPO_ROOT / "bin" / "cairn"), "build"],
            capture_output=True, text=True, timeout=300, cwd=str(REPO_ROOT),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def resolve_build_conflict(log: list[str]) -> bool:
    """If a rebase stopped only on build/, regenerate and continue.

    CLAUDE.md: "Never merge those by hand; regenerate with `make build`." This
    is that instruction, executed. Anything outside build/ in the conflict list
    means a human should look, so we bail and say so.
    """
    files = conflicted()
    if not files or any(not f.startswith("build/") for f in files):
        return False
    if not regenerate():
        log.append("  build/ conflicted and `cairn build` failed — resolve by hand")
        return False
    git("add", "build")
    env_code, text = _rebase_continue()
    if env_code != 0:
        log.append(f"  build/ regenerated but the rebase would not continue:\n{text}")
        return False
    log.append(f"  resolved {len(files)} build/ conflict(s) by regenerating")
    return True


def _rebase_continue() -> tuple[int, str]:
    # GIT_EDITOR=true so `rebase --continue` reuses the existing message instead
    # of hanging on an editor that has no terminal in a session hook.
    env = dict(os.environ, GIT_EDITOR="true")
    try:
        done = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rebase", "--continue"],
            capture_output=True, text=True, timeout=120, env=env,
        )
    except subprocess.SubprocessError as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def rebase_in_progress() -> bool:
    git_dir = out("rev-parse", "--git-dir")
    if not git_dir:
        return False
    base = Path(git_dir)
    if not base.is_absolute():
        base = REPO_ROOT / base
    return (base / "rebase-merge").exists() or (base / "rebase-apply").exists()


def pull(log: list[str]) -> bool:
    """`git pull --rebase --autostash`. True if the tree ended up clean.

    --autostash so an uncommitted node draft doesn't block the pull. That is the
    whole point: the draft is the normal state of this repo at session start,
    and a pull that refuses because of one is a pull that stops being run.
    """
    if rebase_in_progress():
        log.append("  a rebase is already in progress — finish it first "
                   "(`git rebase --continue` or `--abort`)")
        return False
    if not upstream():
        log.append("  no upstream branch; nothing to sync with")
        return False

    code, text = git("pull", "--rebase", "--autostash")
    if code == 0:
        if "Already up to date" in text or "up to date" in text.lower():
            log.append("  already up to date")
        else:
            log.append("  pulled")
        return True

    # Distinguish "the network is unreachable" from "your history diverged".
    lowered = text.lower()
    if any(s in lowered for s in ("could not resolve", "unable to access",
                                 "connection refused", "timed out",
                                 "network is unreachable", "no route to host",
                                 "permission denied (publickey)")):
        log.append("  couldn't reach the remote — working offline, nothing lost")
        return False

    if rebase_in_progress() and resolve_build_conflict(log):
        return True

    log.append("  pull needs a human:")
    log.extend("    " + line for line in text.splitlines()[:12])
    return False


# --------------------------------------------------------------------------
# Push
# --------------------------------------------------------------------------


def push(log: list[str]) -> None:
    """Regenerate build/, commit *only* build/, push.

    Committing generated output is safe in a way committing a node is not: it is
    derived, so it can be wrong without being a lie, and `make build` fixes it.
    Nodes are left exactly where they are, uncommitted, for a human to read.
    """
    if build_is_stale():
        if regenerate():
            log.append("  regenerated build/")
        else:
            log.append("  `cairn build` failed — pushing without regenerating")

    dirty_build = [p for _, p in porcelain() if p.startswith("build/")]
    if dirty_build:
        git("add", "build")
        code, text = git("commit", "-m", "build: regenerate")
        if code == 0:
            log.append(f"  committed build/ ({len(dirty_build)} file(s))")
        else:
            log.append("  build/ commit failed:")
            log.extend("    " + line for line in text.splitlines()[:6])

    ahead, _ = ahead_behind()
    if not ahead:
        log.append("  nothing to push")
        return
    code, text = git("push")
    if code == 0:
        log.append(f"  pushed {ahead} commit(s)")
    else:
        log.append("  push failed:")
        log.extend("    " + line for line in text.splitlines()[:8])


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def report() -> list[str]:
    """What still needs a human. Empty list means nothing does."""
    lines: list[str] = []
    changed, new = unreviewed()

    if new:
        lines.append(f"{len(new)} node(s) never committed — draft(s) awaiting review:")
        lines.extend(f"    {p}" for p in new[:10])
        if len(new) > 10:
            lines.append(f"    … and {len(new) - 10} more")
    if changed:
        lines.append(f"{len(changed)} node(s) edited and not committed:")
        lines.extend(f"    {p}" for p in changed[:10])
        if len(changed) > 10:
            lines.append(f"    … and {len(changed) - 10} more")

    ahead, behind = ahead_behind()
    if ahead:
        lines.append(f"{ahead} commit(s) not pushed — invisible from your other machine")
    if behind:
        lines.append(f"{behind} commit(s) on the remote you don't have")
    if build_is_stale():
        lines.append("build/ is older than the nodes — `make build`")
    return lines


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn sync",
        description="Pull the graph, and say what still needs a human.",
    )
    p.add_argument("--push", action="store_true",
                   help="also regenerate build/, commit it, and push")
    p.add_argument("--check", action="store_true",
                   help="don't touch the network; report local state only")
    p.add_argument("--quiet", action="store_true",
                   help="print nothing unless something needs attention")
    args = p.parse_args()

    if not (REPO_ROOT / ".git").exists():
        print(f"cairn: {REPO_ROOT} is not a git clone", file=sys.stderr)
        return 1

    log: list[str] = []
    if not args.check:
        pull(log)
        if args.push:
            push(log)

    needs = report()

    if args.quiet and not needs:
        return 0

    branch = out("rev-parse", "--abbrev-ref", "HEAD") or "?"
    if not args.quiet:
        print(f"cairn sync — {REPO_ROOT} on {branch}")
        for line in log:
            print(line)

    if needs:
        if not args.quiet:
            print()
        print("Needs you:" if not args.quiet else "cairn: the graph needs you:")
        for line in needs:
            print(f"  {line}" if not line.startswith("    ") else line)
        if not args.push:
            print("\n  `cairn sync --push` regenerates build/ and pushes. It never "
                  "commits a node —\n  read the drafts first, then commit them yourself "
                  "(or via /log).")
    elif not args.quiet:
        print("\nNothing needs you. Both machines see the same graph.")

    # Always 0. This is wired into a session-start hook, and a hook that fails
    # is a hook that gets deleted.
    return 0


if __name__ == "__main__":
    sys.exit(main())
