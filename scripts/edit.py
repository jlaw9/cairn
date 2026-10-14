#!/usr/bin/env python3
"""Correct an existing node: its body, and a whitelist of frontmatter fields.

    cairn edit 2026-08-02-prekd-cosmo-baseline --title "COSMO-RS on the 40-solvent set"
    cairn edit 2026-08-20-prekd-read-tether --due 2026-11-01
    cairn edit 2026-08-20-prekd-read-tether --clear due
    cairn edit 2026-08-02-prekd-cosmo-baseline --parent 2026-07-20-prekd-scoping \\
        --relate "contradicts:2026-06-25-prekd-old:opposite sign, same control"
    cairn edit 2026-08-02-prekd-cosmo-baseline --body - < body.md
    cairn edit 2026-08-02-prekd-cosmo-baseline --commit 3f9c21a --dry-run

The gap this fills: `new_node` writes a node once and `new_node --update` moves
its status, so everything else about a node — a title that turned out wrong, a
due date that moved, a parent nobody recorded, a body that needs its Result —
could only be fixed by hand-editing YAML. That is the one thing the map must
never do, and at a terminal it is how quoting bugs and schema drift get in. This
is the single command that does it instead, through the same serializer and the
same validator as every other write.

**What it may change.** The body, verbatim; the scalars in SCALARS where the
node's type carries them; and the lists — parents, refs, artifacts, relates — by
adding or dropping one entry at a time. **What it may not**, each refused by name
with the command to use instead: `id` and `created` are permanent (rule 1),
`type` is a creation-time decision, and `status`, `updated` and `history` move
together and only through `new_node --update` (rule 4).

**It does not touch `updated` or `history`.** An edit is a correction, not a
claim about the state of the work — the same reasoning that keeps `cairn note`
off them. If it moved `updated`, the replay slider would show a status change
that never happened, and `digest` would report a thread as having moved when all
that changed was a typo in its title.

**Nothing is written on error.** The modified node is swapped into the loaded
graph and checked there first (`lib.check_nodes`); any error the edit introduces
— a parent that closes a cycle, a relation to a node that does not exist, a
commit that is not a SHA — refuses the whole edit and leaves the file alone. A
refusal also follows an edit that changes nothing, and one that names a field
the node's type does not have.

**It commits, the way `cairn note` does** — with `--only`, so it never drags
another draft along, and with a `Cairn-Review:` trailer, because whoever is
correcting a node has by definition just read it. `--no-commit` leaves it on
disk for an agent drafting a correction someone else should look at. The file is
written before the commit is attempted, so a commit that fails costs nothing.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib
import new_node
import note

#: The scalars an edit may set. `title` and `project` belong to every type; the
#: rest only where `lib.TYPES` gives the node's type that field. `contacts` is
#: absent on purpose: it is a list of mappings, and there is no flag shape for
#: one that would not be a small YAML editor.
SCALARS = ("title", "project", "due", "date", "venue", "url",
           "repo", "commit", "host", "origin", "source")

#: Fields every type carries, so the per-type check does not apply to them.
COMMON_EDITABLE = {"title", "project", "parents", "refs", "relates"}

#: Scalars that hold an ISO date, stored as one.
DATES = {"due", "date"}

#: Fields that are never edited, and what to use instead. Named rather than left
#: to argparse, whose "unrecognised argument" reads as a typo instead of a rule.
FORBIDDEN = {
    "id": "id is permanent and equals the filename (rule 1) — a node is never "
          "renamed; create a new one and relate it with `supersedes`",
    "type": "type is a creation-time decision — create a node of the right type "
            "and relate it with `supersedes`",
    "status": "status moves only with history — use "
              "`cairn new_node --update <id> --status <status> --note \"why\"`",
    "created": "created is permanent — it dates the id",
    "updated": "updated moves only with a status change — use "
               "`cairn new_node --update <id> --status ...`; an edit is a "
               "correction and leaves it alone",
    "history": "history is append-only and written only by a status change — use "
               "`cairn new_node --update <id> --status ... --note ...`",
}


def refuse(message: str) -> None:
    sys.exit(f"cairn edit: {message}")


def carries(node: lib.Node, field: str) -> bool:
    if field in COMMON_EDITABLE:
        return True
    spec = node.spec
    return bool(spec and field in set(spec.required) | set(spec.optional))


def require_field(node: lib.Node, field: str) -> None:
    if field in FORBIDDEN:
        refuse(FORBIDDEN[field])
    if field not in SCALARS and field not in COMMON_EDITABLE | {"artifacts"}:
        refuse(f"'{field}' is not a field `cairn edit` can change "
               f"(scalars: {', '.join(SCALARS)})")
    if not carries(node, field):
        spec = node.spec
        own = ", ".join(spec.optional) if spec and spec.optional else "none"
        refuse(f"a {node.type} has no '{field}' field "
               f"(its own fields: {own})")


def scalar_value(field: str, raw: str):
    value = raw.strip()
    if not value:
        refuse(f"--{field} is empty — to remove it, use --clear {field}")
    if "\n" in value or "\r" in value:
        refuse(f"--{field} must be one line")
    if field in DATES:
        when = lib.as_date(value)
        if when is None:
            refuse(f"--{field}: not an ISO date: {value!r}")
        return when
    if field == "commit" and not lib.SHA_RE.match(value):
        refuse(f"--commit {value!r} is not a git SHA — reference commits, never branches")
    return value


def read_body(source: str) -> str:
    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            refuse(f"--body: cannot read {source}: {exc}")
    if not text.strip():
        refuse("an empty body would erase the node — nodes are never deleted; "
               "send the body you want, or leave --body out")
    return text


def apply(node: lib.Node, args: argparse.Namespace) -> list[str]:
    """Apply the requested changes to `node` in place; return what changed.

    A scalar set to the value it already has is silently skipped, because a form
    sends every field it shows. A list operation that would do nothing — adding a
    parent already there, dropping one that is not — is refused, because it means
    the caller's picture of the node is out of date.
    """
    meta = node.meta
    changed: list[str] = []

    for field in SCALARS:
        raw = getattr(args, field)
        if raw is None:
            continue
        require_field(node, field)
        value = scalar_value(field, raw)
        if field == "project" and value != node.project:
            # Exactly new_node's guard, and without its escape hatch: moving a
            # node into a project the graph has never seen is a creation-time
            # decision, not a correction.
            try:
                new_node.check_project(value, allow_new=False)
            except SystemExit as exc:
                # Its last line offers --new-project, which is not on offer here.
                lines = [l for l in str(exc.code).splitlines()
                         if "--new-project" not in l]
                refuse("\n".join(lines) + "\n  edit cannot start a project — a "
                       "node's project is new only at creation")
        if meta.get(field) != value:
            meta[field] = value
            changed.append(field)

    for field in args.clear:
        require_field(node, field)
        if field not in SCALARS:
            refuse(f"--clear empties a scalar; '{field}' is a list — "
                   f"drop its entries one at a time")
        spec = node.spec
        if field in lib.COMMON_REQUIRED or (spec and field in spec.required):
            refuse(f"'{field}' is required and cannot be cleared")
        if field not in meta:
            refuse(f"{node.id} has no '{field}' to clear")
        del meta[field]
        changed.append(f"-{field}")

    def edit_list(field: str, label: str, add: list[str], drop: list[str],
                  same=lambda a, b: a == b) -> None:
        if not (add or drop):
            return
        require_field(node, field)
        items = list(meta.get(field) or [])
        for value in drop:
            value = value.strip()
            kept = [item for item in items if not same(str(item), value)]
            if len(kept) == len(items):
                refuse(f"{value} is not a {label} of {node.id}")
            items = kept
            changed.append(f"-{label} {value}")
        for value in add:
            value = value.strip()
            if not value:
                refuse(f"an empty {label}")
            if any(same(str(item), value) for item in items):
                refuse(f"{value} is already a {label} of {node.id}")
            items.append(value)
            changed.append(f"+{label} {value}")
        meta[field] = items

    edit_list("parents", "parent", args.parent, args.drop_parent)
    # DOIs are case-insensitive, and the registry keys them lowercased.
    edit_list("refs", "ref", args.ref, args.drop_ref,
              same=lambda a, b: a.lower() == b.lower())
    edit_list("artifacts", "artifact", args.artifact, args.drop_artifact)
    if "artifacts" in meta and not meta["artifacts"]:
        del meta["artifacts"]                     # optional: absent beats []
    if "refs" in meta and not meta["refs"]:
        del meta["refs"]

    if args.relate or args.unrelate:
        relates = [dict(r) for r in (meta.get("relates") or [])]
        for spec in args.unrelate:
            kind, _, target = spec.partition(":")
            kind, target = kind.strip(), target.strip()
            if kind not in lib.RELATIONS or not target:
                refuse(f"--unrelate {spec!r}: want kind:node-id, kind one of "
                       f"{', '.join(sorted(lib.RELATIONS))}")
            kept = [r for r in relates
                    if not (str(r.get("type")) == kind and str(r.get("to")) == target)]
            if len(kept) == len(relates):
                refuse(f"{node.id} has no '{kind}' relation to {target}")
            relates = kept
            changed.append(f"-{kind} {target}")
        for spec in args.relate:
            entry = new_node.parse_relation(spec)
            if any(str(r.get("type")) == entry["type"] and str(r.get("to")) == entry["to"]
                   for r in relates):
                refuse(f"{node.id} already {entry['type']} {entry['to']} — "
                       f"--unrelate it first to change the note")
            relates.append(entry)
            changed.append(f"+{entry['type']} {entry['to']}")
        if relates:
            meta["relates"] = relates
        else:
            meta.pop("relates", None)

    if args.body is not None:
        body = read_body(args.body)
        # Compared and written stripped, because that is what the serializer
        # does to every body on every write — so a body sent back unchanged is
        # no change at all, and `## Notes` survives byte for byte.
        if body.strip() != node.body.strip():
            node.body = body
            changed.append("body")

    return changed


def introduced_errors(nodes: dict[str, lib.Node], edited: lib.Node) -> list[lib.Issue]:
    """Errors present with the edit and absent without it. Errors the graph had
    already are someone else's business and do not block a correction."""
    def key(issue: lib.Issue) -> tuple[str, str]:
        return issue.where, issue.message
    before = {key(i) for i in lib.check_nodes(nodes) if i.level == "error"}
    after = lib.check_nodes({**nodes, edited.id: edited})
    return [i for i in after if i.level == "error" and key(i) not in before]


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn edit", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # No prefix matching: `--stat` would otherwise reach the --status
        # refusal by accident, and `--d` would be a puzzle about ambiguity.
        allow_abbrev=False)
    p.add_argument("node", help="the node id, exactly")
    for field in SCALARS:
        p.add_argument(f"--{field}", metavar="ISO_DATE" if field in DATES else "VALUE")
    p.add_argument("--clear", action="append", default=[], metavar="FIELD",
                   help="empty an optional scalar field")
    p.add_argument("--parent", action="append", default=[], metavar="ID")
    p.add_argument("--drop-parent", action="append", default=[], metavar="ID")
    p.add_argument("--ref", action="append", default=[], metavar="DOI")
    p.add_argument("--drop-ref", action="append", default=[], metavar="DOI")
    p.add_argument("--artifact", action="append", default=[], metavar="HOST:/PATH")
    p.add_argument("--drop-artifact", action="append", default=[], metavar="HOST:/PATH")
    p.add_argument("--relate", action="append", default=[], metavar="TYPE:ID:WHY")
    p.add_argument("--unrelate", action="append", default=[], metavar="TYPE:ID")
    p.add_argument("--body", metavar="FILE",
                   help="replace the whole body with FILE's contents; - for stdin")
    p.add_argument("--dry-run", action="store_true",
                   help="print the diff and write nothing")
    p.add_argument("--no-commit", action="store_true",
                   help="write the edit but leave it uncommitted")
    # Accepted only so they can be refused by name, with what to use instead.
    for field in FORBIDDEN:
        p.add_argument(f"--{field}", dest=f"forbidden_{field}", nargs="?",
                       const="", default=None, help=argparse.SUPPRESS)
    args = p.parse_args()

    for field in FORBIDDEN:
        if getattr(args, f"forbidden_{field}") is not None:
            refuse(FORBIDDEN[field])

    nodes, load_errors = lib.load_nodes()
    node = nodes.get(args.node)
    if node is None:
        if any(args.node in e for e in load_errors):
            refuse(f"{args.node} does not parse — fix it by hand first:\n  "
                   + "\n  ".join(e for e in load_errors if args.node in e))
        refuse(f"no such node: {args.node} (the id must be exact)")

    original = node.path.read_text(encoding="utf-8")
    edited = lib.parse_file(node.path)
    changed = apply(edited, args)
    if not changed:
        refuse(f"nothing would change on {node.id}")

    problems = introduced_errors(nodes, edited)
    if problems:
        refuse("refused, nothing written:\n" + "\n".join(f"  {i}" for i in problems))

    text = edited.to_text()
    # The serializer is hand-rolled, so prove this edit round-trips before it is
    # the only copy: these files are the database.
    reparsed = lib.parse_text(text, edited.path)
    if reparsed.meta != edited.meta or reparsed.body.strip() != edited.body.strip():
        refuse("refused, nothing written: the edited frontmatter would not read "
               "back as written — please report this, it is a serializer bug")

    rel = node.path.relative_to(lib.REPO_ROOT)
    if args.dry_run:
        sys.stdout.writelines(difflib.unified_diff(
            original.splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        print(f"\n  dry run: {', '.join(changed)} — nothing written")
        return 0

    edited.path.write_text(text, encoding="utf-8")
    # First line is the path: serve.py derives `committed` from it.
    print(rel)
    print(f"  {', '.join(changed)}")
    for issue in lib.check_nodes({**nodes, edited.id: edited}):
        if issue.level == "warn" and issue.where == edited.path.name:
            print(f"  {issue}", file=sys.stderr)

    if args.no_commit:
        print("\n  not committed (--no-commit). It won't reach your other machine "
              "until it is.")
        return 0

    summary = ", ".join(changed)
    message = (f"edit {node.id}: {summary[:200]}"
               f"\n\n{lib.review_trailer(note.whoami(), node.id)}\n")
    code, out = note.git("commit", "--only", str(rel), "-m", message)
    if code == 0:
        print("  committed. `cairn sync --push` to make it visible elsewhere.")
    else:
        print("\n  The edit is written, but the commit failed — nothing is lost:")
        for line in out.splitlines()[:10]:
            print(f"    {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
