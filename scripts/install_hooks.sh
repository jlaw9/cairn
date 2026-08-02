#!/bin/sh
# Point git at the tracked hooks directory. Run once per clone (laptop + HPC).
set -e
root=$(git rev-parse --show-toplevel)
chmod +x "$root/.githooks/pre-commit"
git -C "$root" config core.hooksPath .githooks
echo "cairn: pre-commit validation enabled (core.hooksPath = .githooks)"
