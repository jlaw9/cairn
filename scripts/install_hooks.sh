#!/bin/sh
# Point a graph repo's git hooks at this tool's tracked hook. Once per clone.
#
#   cairn install_hooks                  # graph = $CAIRN_ROOT, or the cwd's repo
#   cairn install_hooks /path/to/graph
#
# core.hooksPath is set to an *absolute* path into the tool repo, so the hook is
# maintained in one place and every graph on the machine gets fixes for free.
set -e

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
tool=$(dirname -- "$here")

graph=${1:-${CAIRN_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || true)}}
[ -n "$graph" ] || {
    echo "cairn install_hooks: no graph given, no CAIRN_ROOT, not in a git repo." >&2
    echo "  usage: cairn install_hooks /path/to/your-research-graph" >&2
    exit 2
}
graph=$(CDPATH= cd -- "$graph" && pwd -P)

[ -d "$graph/nodes" ] || {
    echo "cairn install_hooks: $graph has no nodes/ — is that a graph?" >&2
    echo "  create one with: cairn init $graph" >&2
    exit 2
}
git -C "$graph" rev-parse --git-dir >/dev/null 2>&1 || {
    echo "cairn install_hooks: $graph is not a git repo." >&2
    exit 2
}

chmod +x "$tool/.githooks/pre-commit"
git -C "$graph" config core.hooksPath "$tool/.githooks"
echo "cairn: pre-commit validation enabled for $graph"
echo "       (core.hooksPath = $tool/.githooks)"
