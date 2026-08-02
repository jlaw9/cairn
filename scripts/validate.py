#!/usr/bin/env python3
"""Validate the graph. Exit non-zero on errors; warnings are advisory.

Run directly, or let the pre-commit hook run it (scripts/install_hooks.sh).
"""

from __future__ import annotations

import argparse
import sys

import lib


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors")
    parser.add_argument("--quiet", action="store_true", help="only print problems")
    args = parser.parse_args()

    issues = lib.validate()
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warn"]

    for issue in sorted(issues, key=lambda i: (i.level != "error", i.where, i.message)):
        print(issue, file=sys.stderr if issue.level == "error" else sys.stdout)

    nodes, _ = lib.load_nodes()
    if not args.quiet:
        summary = f"\n{len(nodes)} node(s), {len(errors)} error(s), {len(warnings)} warning(s)"
        print(summary)

    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
