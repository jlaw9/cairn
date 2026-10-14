#!/usr/bin/env python3
"""Register a dataset: key in, verified datasets/ page out.

    scripts/add_dataset.py dp18-250912 "DP-18 training set, 250912 release" \\
        --host kestrel --path /projects/.../250912/train.csv \\
        --file ~/data/250912/train.csv --rows 3133 --tier review \\
        --generated-by 2026-08-10-photopoly-lit-extraction

A dataset page is a lookup-table row, not a node: no status, no lifecycle, off
the DAG — the same shape as papers/. The join key is `key:`, referenced from
nodes as `data: [<key>]`, and the load-bearing field is `sha256`, which names
the bytes where `host:path` names a location that may since have been
overwritten.

`--file` hashes a *local* copy so the sha256 is measured, never transcribed.
When the file lives on another host, paste the hash from its MANIFEST.csv (or
`sha256sum` output) with `--sha256` instead. Passing both cross-checks them.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import lib


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("key", help="registry key, lowercase [a-z0-9._-] — becomes the filename")
    parser.add_argument("title", help="one-line description of what this data is")
    parser.add_argument("--rows", type=int, help="row count, so a reader can sanity-check a copy")
    parser.add_argument("--host", help="where the file lives, e.g. kestrel")
    parser.add_argument("--path", help="absolute path on that host")
    parser.add_argument("--sha256", help="hash from a manifest — paste, never retype from memory")
    parser.add_argument("--file", type=Path, help="local copy to hash (measured beats transcribed)")
    parser.add_argument("--release", help="release label, e.g. 250912")
    parser.add_argument("--tier", choices=sorted(lib.DATASET_TIERS),
                        help="shareability: public, restricted, or review (needs sign-off)")
    parser.add_argument("--generated-by", metavar="NODE_ID",
                        help="the node whose work produced this file")
    parser.add_argument("--supersedes", metavar="KEY", help="earlier dataset this replaces")
    parser.add_argument("--note", default="", help="one line of provenance for the body")
    parser.add_argument("--force", action="store_true", help="rewrite an existing registry page")
    args = parser.parse_args()

    key = args.key.strip()
    if not lib.DATASET_KEY_RE.match(key):
        sys.exit(f"'{key}' is not a dataset key (lowercase [a-z0-9._-], letter/digit first)")

    path = lib.dataset_dir() / f"{key}.md"
    if path.exists() and not args.force:
        # Same rule as papers: a registry page is rewritten deliberately or not
        # at all. A new release of the same data is a new key plus --supersedes.
        print(f"{path.relative_to(lib.REPO_ROOT)} already exists — use --force to rewrite, "
              f"or register the new release under its own key with --supersedes {key}")
        return 0

    sha = (args.sha256 or "").strip().lower()
    if sha and not lib.SHA256_RE.match(sha):
        sys.exit(f"--sha256 {sha!r} is not 64 hex chars")
    if args.file:
        if not args.file.exists():
            sys.exit(f"no such file: {args.file}")
        measured = sha256_of(args.file)
        if sha and sha != measured:
            sys.exit(
                f"--sha256 disagrees with the file:\n"
                f"  given:    {sha}\n"
                f"  measured: {measured}\n"
                f"one of them names different bytes — resolve that before registering"
            )
        sha = measured
        print(f"  sha256: {sha}  (measured from {args.file})")

    meta: dict = {"key": key, "title": args.title}
    for field, value in [
        ("rows", args.rows), ("host", args.host), ("path", args.path),
        ("sha256", sha or None), ("release", args.release), ("tier", args.tier),
        ("generated_by", args.generated_by), ("supersedes", args.supersedes),
    ]:
        if value is not None and value != "":
            meta[field] = value

    body = args.note.strip() or "_Provenance: not yet written._"
    path.parent.mkdir(parents=True, exist_ok=True)
    lib.Node(path=path, meta=meta, body=body).write()
    print(path.relative_to(lib.REPO_ROOT))

    if not sha:
        print("  note: no sha256 — the page names a location, not bytes. Add one "
              "from the release MANIFEST.csv when it exists.", file=sys.stderr)
    used_by = lib.dataset_backlinks(lib.load_nodes()[0]).get(key, [])
    if used_by:
        print(f"  used by {len(used_by)} node(s): {', '.join(used_by[:3])}")

    issues = [i for i in lib.validate() if i.where == f"datasets/{path.name}"]
    for issue in issues:
        print(f"  {issue}", file=sys.stderr)
    return 1 if any(i.level == "error" for i in issues) else 0


if __name__ == "__main__":
    sys.exit(main())
