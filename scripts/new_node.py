#!/usr/bin/env python3
"""Create a node, or append a status change to an existing one.

This exists so that /log never has to hand-assemble YAML. Hand-assembled
frontmatter is how `status` and `history` drift apart.

    scripts/new_node.py experiment "COSMO-RS baseline" --project prekd \\
        --status running --parent 2026-07-20-prekd-scoping \\
        --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

    scripts/new_node.py --update 2026-08-02-prekd-cosmo-baseline \\
        --status dead --note "solvation model wrong for ionics"
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import lib

BODY_TEMPLATE = {
    "experiment": "## Claim\n\n{title}\n\n## What I did\n\n## Result\n\n## Next\n",
    "direction": "## What this is\n\n{title}\n\n## Open questions\n",
    "seed": "## The idea\n\n{title}\n\n## Why it might matter\n\n## What it would take\n",
    "milestone": "## Scope\n\n{title}\n\n## Contributing work\n",
    "task": "## What\n\n{title}\n\n## Why\n",
}


#: Ids get typed, greped and pasted into commit messages. Keep them short —
#: 2026-04-20-prekd-cosmo-baseline, not the whole title as a slug.
SLUG_MAX = 34

STOPWORDS = {"a", "an", "the", "of", "on", "in", "for", "to", "and", "with", "from"}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def shorten(slug: str, keep: int = 1) -> str:
    """Trim a slug to SLUG_MAX at a word boundary, dropping filler words.

    The first `keep` words (the project key) always survive.
    """
    words = slug.split("-")
    head, tail = words[:keep], [w for w in words[keep:] if w not in STOPWORDS]
    out = list(head)
    for word in tail:
        if len("-".join(out + [word])) > SLUG_MAX and out != head:
            break
        out.append(word)
    return "-".join(out)[:SLUG_MAX].strip("-")


def build(args: argparse.Namespace) -> lib.Node:
    created = lib.as_date(args.date) or dt.date.today()
    spec = lib.TYPES[args.type]
    status = args.status or spec.statuses[0]
    if status not in spec.statuses:
        sys.exit(f"'{status}' is not a valid status for {args.type}: {', '.join(spec.statuses)}")

    stem = args.slug or shorten(slugify(f"{args.project}-{args.title}"))
    node_id = f"{created.isoformat()}-{stem}"
    path = lib.node_dir() / f"{node_id}.md"
    if path.exists():
        sys.exit(f"{path} already exists — nodes are append-only, use --update")

    meta: dict = {
        "id": node_id,
        "type": args.type,
        "title": args.title,
        "project": args.project,
        "status": status,
        "created": created,
        "updated": created,
    }
    for key in ("repo", "commit", "host", "origin", "venue", "url", "due", "source"):
        value = getattr(args, key, None)
        if value:
            meta[key] = lib.as_date(value) if key == "due" else value
    if args.artifact:
        meta["artifacts"] = list(args.artifact)
    meta["parents"] = list(args.parent)
    if args.ref:
        meta["refs"] = list(args.ref)
    meta["history"] = [{"date": created, "status": status, "note": args.note or "created"}]

    body = BODY_TEMPLATE[args.type].format(title=args.title)
    return lib.Node(path=path, meta=meta, body=body)


def update(args: argparse.Namespace) -> lib.Node:
    path = lib.node_dir() / f"{args.update}.md"
    if not path.exists():
        sys.exit(f"no such node: {path}")
    node = lib.parse_file(path)
    if not args.status:
        sys.exit("--update requires --status")
    when = lib.as_date(args.date) or dt.date.today()
    try:
        node.set_status(args.status, args.note or "", when)
    except ValueError as exc:
        sys.exit(str(exc))
    for key in ("commit", "host", "url"):
        if getattr(args, key, None):
            node.meta[key] = getattr(args, key)
    if args.artifact:
        node.meta.setdefault("artifacts", []).extend(args.artifact)
    return node


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("type", nargs="?", choices=sorted(lib.TYPES), help="node type")
    parser.add_argument("title", nargs="?", help="one-line title")
    parser.add_argument("--update", metavar="ID", help="append a status change to an existing node")
    parser.add_argument("--project", help="project key, e.g. prekd")
    parser.add_argument("--status")
    parser.add_argument("--note", default="", help="history note for this change")
    parser.add_argument("--date", help="ISO date; defaults to today")
    parser.add_argument("--slug", help="override the generated id slug")
    parser.add_argument("--parent", action="append", default=[], metavar="ID")
    parser.add_argument("--ref", action="append", default=[], metavar="DOI")
    parser.add_argument("--repo")
    parser.add_argument("--commit")
    parser.add_argument("--host")
    parser.add_argument("--artifact", action="append", default=[], metavar="HOST:/PATH")
    parser.add_argument("--origin")
    parser.add_argument("--venue")
    parser.add_argument("--url")
    parser.add_argument("--due", metavar="ISO_DATE")
    parser.add_argument("--source", metavar="ID")
    args = parser.parse_args()

    if args.update:
        node = update(args)
    else:
        if not (args.type and args.title and args.project):
            parser.error("type, title and --project are required when creating a node")
        node = build(args)

    node.path.parent.mkdir(parents=True, exist_ok=True)
    node.write()
    print(node.path.relative_to(lib.REPO_ROOT))

    issues = [i for i in lib.validate() if i.where == node.path.name]
    for issue in issues:
        print(f"  {issue}", file=sys.stderr)
    return 1 if any(i.level == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
