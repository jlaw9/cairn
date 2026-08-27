#!/bin/sh
# Report whether this clone is actually set up, and what to run if it isn't.
#
# Written in shell, not Python, because the most common thing to be wrong *is*
# the Python — a doctor that can't run on a broken install is no use.
#
# This exists because the first ten minutes of using Cairn on a new machine were
# spent finding out, one failed command at a time, that `make setup` had never
# been run here: no hook, no slash commands, no CAIRN_PATH, and no interpreter
# with PyYAML. Each of those failed differently and none of them said which of
# the four was missing.

tool=$(cd "$(dirname "$0")/.." && pwd)
# The graph is wherever CAIRN_ROOT says, falling back to a pre-split single-repo
# clone. Resolved the same way lib._graph_root() does it; if these two ever
# disagree, doctor is lying, which is worse than doctor being absent.
graph=${CAIRN_ROOT:-$tool}
root=$tool
ok=0
bad=0

say_ok()   { printf '  ok    %s\n' "$1"; ok=$((ok + 1)); }
say_bad()  { printf '  MISS  %s\n' "$1"; printf '        -> %s\n' "$2"; bad=$((bad + 1)); }
say_note() { printf '        %s\n' "$1"; }

printf 'cairn doctor\n'
printf '  tool  %s\n' "$tool"
printf '  graph %s%s\n\n' "$graph" \
    "$([ -n "$CAIRN_ROOT" ] && echo "" || echo "  (CAIRN_ROOT unset — assuming a single-repo clone)")"

# 1. An interpreter that can run Cairn. Everything else depends on this.
py=$("$root/scripts/find_python.sh" 2>/dev/null || true)
if [ -n "$py" ]; then
    say_ok "python: $py"
    say_note "$("$py" --version 2>&1), pyyaml $("$py" -c 'import yaml; print(yaml.__version__)' 2>/dev/null)"
else
    say_bad "no Python >= 3.7 with PyYAML" \
            "install it, or export CAIRN_PYTHON=/path/to/python"
    say_note "conda install pyyaml"
    say_note "python3 -m pip install --user pyyaml"
    say_note "python3 -m venv ~/.cairn/venv && ~/.cairn/venv/bin/pip install pyyaml"
fi

# 2. The pre-commit hook. Without it the graph commits unvalidated. It is set on
#    the *graph* repo and points at an absolute path in the tool, so accept either
#    that or the old in-repo form.
hooks_path=$(git -C "$graph" config core.hooksPath 2>/dev/null || true)
if [ "$hooks_path" = "$tool/.githooks" ] || [ "$hooks_path" = ".githooks" ]; then
    say_ok "pre-commit validation enabled for the graph"
else
    say_bad "pre-commit hook not installed on $graph" \
            "cairn install_hooks $graph"
fi

# 3. /log and /paper, which only work from other repos once symlinked.
if [ -e "$HOME/.claude/commands/log.md" ]; then
    say_ok "/log and /paper reachable from any repo"
else
    say_bad "/log not installed for this machine" "make install-commands"
fi

# 4. CAIRN_PATH — the tool. /log reads it from inside a project repo.
if [ -n "$CAIRN_PATH" ]; then
    if [ "$CAIRN_PATH" = "$tool" ]; then
        say_ok "CAIRN_PATH=$CAIRN_PATH"
    else
        say_bad "CAIRN_PATH points elsewhere: $CAIRN_PATH" \
                "expected $tool — two clones of the tool will drift apart"
    fi
elif grep -qs "CAIRN_PATH" "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bash_profile"; then
    say_ok "CAIRN_PATH set in a shell profile (not in this shell)"
else
    say_bad "CAIRN_PATH is not set" "export CAIRN_PATH=$tool"
    say_note "add it to your shell profile; /log needs it from other repos"
fi

# 4b. CAIRN_ROOT — the graph. Unset is only correct for a pre-split clone, and
#     the failure it causes is the worst kind: a graph of zero nodes reads as
#     "nothing was ever tried".
if [ -n "$CAIRN_ROOT" ]; then
    if [ -d "$CAIRN_ROOT/nodes" ]; then
        say_ok "CAIRN_ROOT=$CAIRN_ROOT"
    else
        say_bad "CAIRN_ROOT has no nodes/: $CAIRN_ROOT" \
                "cairn init $CAIRN_ROOT, or fix the path"
    fi
elif [ -d "$tool/nodes" ]; then
    say_ok "single-repo clone (tool and graph together, pre-split layout)"
elif grep -qs "CAIRN_ROOT" "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bash_profile"; then
    say_ok "CAIRN_ROOT set in a shell profile (not in this shell)"
else
    say_bad "CAIRN_ROOT is not set and this clone has no nodes/" \
            "export CAIRN_ROOT=/path/to/your-research-graph"
    say_note "or start one: cairn init ~/research-graph"
fi

# 5. Is this clone nested inside another git repo? Cairn is meant to be a
#    separate repo spanning every project — nested, `git status` in the parent
#    sees it as an untracked directory and /log's `repo` field gets confusing.
parent=$(cd "$graph/.." 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null || true)
if [ -n "$parent" ]; then
    say_bad "the graph is nested inside the git repo at $parent" \
            "keep the graph outside any project repo, e.g. ~/research-graph"
fi

# 6. The graph itself.
if [ -n "$py" ]; then
    count=$(ls "$graph/nodes"/*.md 2>/dev/null | wc -l | tr -d ' ')
    printf '\n'
    if CAIRN_ROOT="$graph" "$py" "$tool/scripts/validate.py" >/dev/null 2>&1; then
        say_ok "$count node(s), validation clean"
    else
        say_bad "validation is failing" "make validate"
    fi
fi

printf '\n%s ok, %s to fix\n' "$ok" "$bad"
[ "$bad" -eq 0 ] || printf 'Run `make setup` to do the install steps in one go.\n'
exit 0
