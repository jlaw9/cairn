#!/usr/bin/env python3
"""Create a node, or append a status change to an existing one.

This exists so that /log never has to hand-assemble YAML. Hand-assembled
frontmatter is how `status` and `history` drift apart.

    scripts/new_node.py experiment "COSMO-RS baseline" --project prekd \\
        --status running --parent 2026-07-20-prekd-scoping \\
        --repo git@github.com:jlaw9/prekd.git --commit a3f9c21 --host kestrel

    scripts/new_node.py --update 2026-08-02-prekd-cosmo-baseline \\
        --status dead --note "solvation model wrong for ionics"

    scripts/new_node.py --update 2026-08-02-prekd-cosmo-baseline \\
        --relate "contradicts:2026-07-20-prekd-scoping:opposite sign on the same set"
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
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

#: Function words that must never *end* an id. Breaking on a word boundary is not
#: enough on its own: "Log-and-restart is cheaper than continuing at high context"
#: trims to `cairn-log-restart-is-cheaper-than`, which reads as though it were cut
#: off mid-sentence. Ids are permanent and appear in commit messages, `[[links]]`
#: and filenames, so there is no fixing one later — the trim has to land on a word
#: that carries meaning.
DANGLING = {
    "is", "are", "was", "were", "be", "been", "being", "than", "then", "as", "at",
    "by", "but", "or", "if", "it", "its", "that", "this", "these", "those", "into",
    "onto", "over", "under", "via", "vs", "do", "does", "did", "can", "could",
    "will", "would", "should", "may", "might", "must", "has", "have", "had", "not",
    "no", "so", "such", "very", "too", "also", "when", "while", "whether", "how",
    "why", "what", "which", "who",
}


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def shorten(slug: str, keep: int = 1) -> str:
    """Trim a slug to SLUG_MAX at a word boundary, dropping filler words.

    The first `keep` words (the project key) always survive, and the result never
    ends on a function word — see DANGLING for why that second rule is needed.
    """
    words = slug.split("-")
    head, tail = words[:keep], [w for w in words[keep:] if w not in STOPWORDS]
    out = list(head)
    for word in tail:
        if len("-".join(out + [word])) > SLUG_MAX and out != head:
            break
        out.append(word)
    while len(out) > keep and out[-1] in DANGLING:
        out.pop()
    return "-".join(out)[:SLUG_MAX].strip("-")


def parse_relation(spec: str) -> dict:
    """`type:node-id[:why]` -> a relates entry.

    The note is part of the same argument rather than a separate flag because a
    typed edge without a reason is an arrow nobody can act on, and a flag you
    have to remember separately is a flag that gets skipped.
    """
    kind, _, rest = spec.partition(":")
    target, _, note = rest.partition(":")
    kind, target, note = kind.strip(), target.strip(), note.strip()
    if kind not in lib.RELATIONS:
        sys.exit(f"'{kind}' is not a relation: {', '.join(sorted(lib.RELATIONS))}")
    if not target:
        sys.exit(f"--relate {spec!r} has no target node id (want type:node-id:why)")
    entry = {"to": target, "type": kind}
    if note:
        entry["note"] = note
    return entry


def check_project(project: str, allow_new: bool) -> None:
    """Refuse an unrecognised project key unless --new-project says so.

    `project:` is free text, and it is the one field whose typo is invisible.
    A mistyped id fails validation, a mistyped status fails validation, but
    `photpoly` for `photopoly` validates cleanly and silently splits a project
    into two lanes — after which a missing node no longer means "not tried",
    which is the one guarantee the whole graph rests on.

    A registry file would be the obvious fix and the wrong one: it is a second
    place to update at exactly the moment you are trying to record something,
    and capture wins. Creation time is the only cheap moment to catch this, and
    one flag is the whole cost of starting a genuinely new project.
    """
    known = sorted({node.project for node in lib.load_nodes()[0].values() if node.project})
    if not known or project in known or allow_new:
        return

    # A hint is only useful if it is short. With keys like polyid, polymd,
    # polysol and polycrystal, edit distance is too blunt — polyid and polymd
    # differ by one character and are different projects — so require either a
    # real shared prefix or a single substitution at equal length.
    def shared(key: str) -> int:
        return len(os.path.commonprefix([key, project]))

    def plausible(key: str) -> bool:
        if shared(key) >= 3:
            return True
        return (len(key) == len(project)
                and sum(a != b for a, b in zip(key, project)) == 1)

    near = sorted((k for k in known if plausible(k)),
                  key=lambda k: (-shared(k), abs(len(k) - len(project))))[:3]
    lines = [f"'{project}' is not a project in this graph."]
    if near:
        lines.append(f"  did you mean: {', '.join(near)}")
    lines.append(f"  known keys:   {', '.join(known)}")
    lines.append(f"  if it really is new: --new-project")
    sys.exit("\n".join(lines))


def build(args: argparse.Namespace) -> lib.Node:
    created = lib.as_date(args.date) or dt.date.today()
    spec = lib.TYPES[args.type]
    status = args.status or spec.default_status
    if status not in spec.statuses:
        sys.exit(f"'{status}' is not a valid status for {args.type}: {', '.join(spec.statuses)}")
    check_project(args.project, getattr(args, "new_project", False))

    if args.slug:
        stem = args.slug
    else:
        full = slugify(f"{args.project}-{args.title}")
        stem = shorten(full)
        # Say so rather than silently choosing a permanent name for someone. The
        # author is the only one who knows whether the short form still reads
        # right, and this is the last moment they can change it cheaply.
        if stem != full:
            print(
                f"note: id shortened to '{stem}'\n"
                f"      full title slug was '{full}'\n"
                f"      ids are permanent — re-run with --slug to choose your own",
                file=sys.stderr,
            )
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
    if getattr(args, "relate", None):
        meta["relates"] = [parse_relation(r) for r in args.relate]
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
    # Relations usually surface later than the node does — you find out a result
    # contradicts an older one months afterwards — so --update takes them alone,
    # with no status change. Adding an edge is not a state transition.
    relate = getattr(args, "relate", None)
    if relate:
        node.meta.setdefault("relates", []).extend(parse_relation(r) for r in relate)
    if not args.status:
        if relate:
            return node
        sys.exit("--update requires --status (or --relate)")
    when = lib.as_date(args.date) or dt.date.today()
    try:
        node.set_status(args.status, args.note or "", when)
    except ValueError as exc:
        sys.exit(str(exc))
    for key in ("commit", "host", "url"):
        if getattr(args, key, None):
            node.meta[key] = getattr(args, key)
    # `due` is settable here and the other creation-time fields are not, because a
    # deadline is the one thing about a task that legitimately moves after it
    # exists — and the validator nags about a task with no date, so there has to be
    # a way to add one without hand-editing the frontmatter.
    if getattr(args, "due", None):
        when_due = lib.as_date(args.due)
        if when_due is None:
            sys.exit(f"--due: not an ISO date: {args.due}")
        node.meta["due"] = when_due
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
    parser.add_argument("--new-project", action="store_true",
                        help="confirm --project names a project that does not exist yet")
    parser.add_argument("--status")
    parser.add_argument("--note", default="", help="history note for this change")
    parser.add_argument("--date", help="ISO date; defaults to today")
    parser.add_argument("--slug", help="override the generated id slug")
    parser.add_argument("--parent", action="append", default=[], metavar="ID")
    parser.add_argument(
        "--relate", action="append", default=[], metavar="TYPE:ID:WHY",
        help="typed relation, e.g. contradicts:2026-06-25-mplastic-scramble-control:only on crystalline",
    )
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
