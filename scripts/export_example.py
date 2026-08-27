#!/usr/bin/env python3
"""Write a scrubbed, derived copy of one project's subgraph, for publication.

Why this is a script and not a `git mv`
---------------------------------------

The `cairn` project's own nodes are the tool's design record *and* the only
honest demonstration of what the tool is for — a real graph, with real dead ends,
which no synthetic example can be. Publishing them alongside the tool is worth
doing. Keeping two *authoritative* copies of a node is not: node ids are
permanent and never reused, and two editable copies of one id is the fork that
[[2026-08-27-cairn-repo-topology]] ruled out.

So the published copy is **derived** — the same status `build/` has. One
authoritative graph, one generated export, regenerated when the source moves.
Nobody edits the export, so the ids cannot diverge.

Two things it does that a copy would not
----------------------------------------

**Substitution.** Internal hostnames and git hosts are rewritten through an
explicit table, so what leaves is deliberate rather than whatever happened to be
in a `host:` field.

**Refusal.** It greps the selected bodies for things a human has to clear —
other projects' keys, cost and token figures, absolute paths, addresses — prints
them with file and line, and **writes nothing** unless `--acknowledge-review` is
passed. Publication is not recoverable by apologising afterwards, and a review
that is a flag in a script is not a review; the flag exists to make the human's
pass explicit, not to replace it.

**Dangling links are redacted, not dropped.** A `[[node-id]]` pointing outside
the exported set becomes a visible stub. Silently deleting it would make a hidden
edge and a missing edge look identical, which is the one thing this graph must
never do.

    cairn export_example --project cairn                    # review pass
    cairn export_example --project cairn --acknowledge-review
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

#: Rewritten on the way out. Longest first, so a substring never wins.
SUBSTITUTIONS = {
    "github.nrel.gov": "git.internal.example",
    "kestrel": "hpc-cluster",
    "kd3": "workstation",
}

#: Flagged for a human, never rewritten — these need judgement, not a regex.
REVIEW_PATTERNS = [
    ("cost figure", re.compile(r"\$\s?\d")),
    ("token count", re.compile(r"\b[\d.,]+\s*(?:B|M|k)?\s*(?:input |output |cache )?tokens\b", re.I)),
    ("absolute path", re.compile(r"(?:^|[\s(`])/(?:kfs\d|projects|scratch|home)/\S+")),
    ("email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("named platform", re.compile(r"\bHERO\b|\bhero:/")),
]

HEADER = """# Example graph

**Generated. Do not edit.** These node files are a scrubbed, derived copy of the
`{project}` subgraph from a private research graph — the record of Cairn's own
design, kept in Cairn. Regenerate with:

```sh
cairn export_example --project {project} --acknowledge-review
```

They are here because a tool for recording research decisions is best explained by
the record of its own: {count} nodes, {dead} of them dead ends, spanning
{first} to {last}. Open `build/graph.html` after `CAIRN_ROOT=$PWD/example cairn build`.

The authoritative copies live in the private graph. If a claim here disagrees with
one there, there wins — this directory is a projection, like `build/`.

Exported {when}. Internal hostnames and git hosts were rewritten; `[[links]]`
pointing outside the exported project are shown as redacted stubs, because a
missing edge and a hidden edge must not look the same.
"""

STUB = "*(a node in a project not published here)*"


def scrub(text: str) -> str:
    for src, dst in sorted(SUBSTITUTIONS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(re.escape(src), dst, text, flags=re.I)
    return text


#: A node id, and nothing else. `[[wikilinks]]` in prose about the syntax is not a
#: reference to a node, and rewriting it as a redacted stub would corrupt the
#: sentence it sits in — silently, in published text.
NODE_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+$")


def redact_links(text: str, keep: set[str]) -> tuple[str, list[str]]:
    dropped: list[str] = []

    def repl(m: re.Match) -> str:
        target = m.group(1)
        if target in keep or not NODE_ID.match(target):
            return m.group(0)
        dropped.append(target)
        return STUB

    return re.sub(r"\[\[([^\]]+)\]\]", repl, text), dropped


def main() -> int:
    ap = argparse.ArgumentParser(prog="cairn export_example")
    ap.add_argument("--project", default="cairn", help="the project to export")
    ap.add_argument("--dest", default="", help="default: <tool>/example")
    ap.add_argument("--acknowledge-review", action="store_true",
                    help="you have read the flagged lines and they are safe to publish")
    args = ap.parse_args()

    nodes, errors = lib.load_nodes()
    if errors:
        print("cairn export_example: the source graph has parse errors; fix those first",
              file=sys.stderr)
        for e in errors[:5]:
            print("  " + e, file=sys.stderr)
        return 1

    selected = {i: n for i, n in nodes.items() if n.project == args.project}
    if not selected:
        keys = sorted({n.project for n in nodes.values() if n.project})
        print(f"cairn export_example: no nodes with project '{args.project}'.\n"
              f"  known: {', '.join(keys)}", file=sys.stderr)
        return 2

    dest = Path(args.dest).expanduser() if args.dest else lib.TOOL_ROOT / "example"

    # Every other project's key is a leak by definition, and deriving the list
    # beats maintaining one — a new project would otherwise be missed silently.
    other_keys = sorted({n.project for n in nodes.values()
                         if n.project and n.project != args.project})
    key_pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in other_keys) + r")\b") \
        if other_keys else None

    findings: list[tuple[str, int, str, str]] = []
    outputs: dict[str, str] = {}
    all_dropped: list[tuple[str, str]] = []

    for nid, node in sorted(selected.items()):
        raw = node.path.read_text(encoding="utf-8")
        text = scrub(raw)
        text, dropped = redact_links(text, set(selected))
        all_dropped += [(nid, d) for d in dropped]
        outputs[nid] = text.rstrip("\n") + "\n"

        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pat in REVIEW_PATTERNS:
                if pat.search(line):
                    findings.append((nid, lineno, label, line.strip()))
            if key_pattern:
                for m in key_pattern.finditer(line):
                    findings.append((nid, lineno, f"project key '{m.group(1)}'",
                                     line.strip()))

    print(f"cairn export_example — project '{args.project}', "
          f"{len(selected)} node(s) -> {dest}")

    if all_dropped:
        print(f"\n  {len(all_dropped)} link(s) outside the export, shown as stubs:")
        for nid, target in all_dropped:
            print(f"    {nid} -> [[{target}]]")

    if findings:
        print(f"\n  {len(findings)} line(s) a human has to clear before this is public:\n")
        for nid, lineno, label, line in findings:
            snippet = line if len(line) <= 96 else line[:93] + "..."
            print(f"    {nid}:{lineno}  [{label}]")
            print(f"      {snippet}")

    if not args.acknowledge_review:
        print("\nNothing written. This is the review pass.")
        print("Read the lines above, edit the *source* nodes if any of them should")
        print("not be published, then re-run with --acknowledge-review.")
        print("\nEditing the source rather than the export is the point: the export is")
        print("derived, so a fix made here would be lost on the next regeneration.")
        return 1

    if dest.exists():
        shutil.rmtree(dest / "nodes", ignore_errors=True)
    (dest / "nodes").mkdir(parents=True, exist_ok=True)
    (dest / "build").mkdir(exist_ok=True)

    for nid, text in outputs.items():
        (dest / "nodes" / f"{nid}.md").write_text(text, encoding="utf-8")

    dates = sorted(n.created.isoformat() for n in selected.values() if n.created)
    (dest / "README.md").write_text(HEADER.format(
        project=args.project,
        count=len(selected),
        dead=sum(1 for n in selected.values() if n.status in ("dead", "killed")),
        first=dates[0] if dates else "?",
        last=dates[-1] if dates else "?",
        when=dt.date.today().isoformat(),
    ), encoding="utf-8")

    print(f"\n  wrote {len(outputs)} node(s) and README.md")
    print(f"  render it:  CAIRN_ROOT={dest} {lib.TOOL_ROOT}/bin/cairn build")
    print("  then commit example/ — it is generated, and the header says so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
