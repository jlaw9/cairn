#!/usr/bin/env python3
"""Add a paper to the registry: DOI in, `papers/<doi-slug>.md` out.

Collapses the manual loop — download, Zotero for a bib key, MinerU for
markdown, copy to kestrel — into one command, because the friction of that loop
is what stops papers getting recorded at all.

    scripts/add_paper.py 10.1038/s41586-021-03819-2
    scripts/add_paper.py 10.1038/s41586-021-03819-2 --pdf ~/Downloads/af.pdf \\
        --bib ~/overleaf/prekd/references.bib

The DOI is the join key. The same DOI keys the registry page, the BibTeX entry
Overleaf cites, the MinerU markdown on kestrel, and a node's `refs:` — so one
identifier ties the citation you wrote to the full text an agent can read.

Metadata is CrossRef-verified and the script refuses to write without it. A DOI
recalled rather than resolved is worse than no DOI: it looks like a citation.

Stdlib only, like the rest of Cairn. MinerU and rsync are shelled out when
configured and skipped cleanly when not, so this degrades to "fetch metadata,
write the page" on a machine that has neither.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import lib

CROSSREF = "https://api.crossref.org/works/"
DOI_ORG = "https://doi.org/"
UA = "Cairn/0.1 (research graph; mailto:jeffrey.law@nlr.gov)"

#: Skipped when deriving a BibTeX key, matching Better BibTeX's default
#: `auth+year+shorttitle` so keys generated here collide with what Zotero
#: would have produced rather than diverging from an existing library.
TITLE_STOPWORDS = {
    "a", "an", "the", "on", "of", "in", "for", "to", "and", "with", "from",
    "is", "are", "at", "by", "via", "using", "towards", "toward",
}


def normalise_doi(raw: str) -> str:
    """Accept a bare DOI, a doi.org URL, or a 'doi:' prefix."""
    doi = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi.strip().strip("/")


def fetch(url: str, accept: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def crossref(doi: str) -> dict:
    try:
        raw = fetch(CROSSREF + urllib.parse.quote(doi, safe="/"), "application/json")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            sys.exit(f"CrossRef has no record for '{doi}' — check the DOI")
        sys.exit(f"CrossRef returned HTTP {exc.code} for '{doi}'")
    except urllib.error.URLError as exc:
        sys.exit(
            f"could not reach CrossRef ({exc.reason}).\n"
            "  Kestrel compute nodes have no outbound network; run this from a\n"
            "  login node or your laptop. Metadata is never guessed."
        )
    return json.loads(raw)["message"]


def author_names(message: dict) -> list[str]:
    names = []
    for author in message.get("author") or []:
        full = " ".join(p for p in (author.get("given"), author.get("family")) if p)
        names.append(full or author.get("name", ""))
    return [n for n in names if n]


def derive_bibkey(message: dict) -> str:
    authors = message.get("author") or []
    family = (authors[0].get("family") if authors else "") or "anon"
    year = ((message.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0] or "nd"
    title = (message.get("title") or [""])[0]
    words = [w for w in re.findall(r"[A-Za-z]+", title.lower()) if w not in TITLE_STOPWORDS]
    stub = words[0] if words else ""
    return re.sub(r"[^a-z0-9]", "", f"{family}".lower()) + str(year) + stub


def bibtex_for(doi: str, bibkey: str) -> str | None:
    """CrossRef's BibTeX, re-keyed so it matches the registry page."""
    try:
        entry = fetch(DOI_ORG + doi, "application/x-bibtex").strip()
    except (urllib.error.HTTPError, urllib.error.URLError):
        return None
    return re.sub(r"^@(\w+)\s*\{\s*[^,]*,", rf"@\1{{{bibkey},", entry, count=1)


def append_bib(bib_path: Path, entry: str, bibkey: str) -> str:
    """Append to references.bib unless the key is already there."""
    existing = bib_path.read_text(encoding="utf-8") if bib_path.exists() else ""
    if re.search(rf"@\w+\s*\{{\s*{re.escape(bibkey)}\s*,", existing):
        return "already present"
    bib_path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    bib_path.write_text(existing + separator + entry + "\n", encoding="utf-8")
    return "appended"


def convert_pdf(pdf: Path, out_dir: Path, slug: str) -> Path | None:
    """PDF -> markdown via MinerU. Override the command with CAIRN_MINERU.

    Untested in this environment — MinerU lives on the laptop. Failure is
    reported and non-fatal: the registry page is still worth writing.
    """
    command = os.environ.get("CAIRN_MINERU", "mineru")
    if not shutil.which(command.split()[0]):
        print(f"  markdown: skipped ({command} not on PATH; set CAIRN_MINERU)", file=sys.stderr)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            command.split() + ["-p", str(pdf), "-o", str(out_dir)],
            check=True, capture_output=True, text=True, timeout=1800,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        print(f"  markdown: FAILED ({detail.strip()[:200]})", file=sys.stderr)
        return None
    produced = sorted(out_dir.rglob("*.md"))
    return produced[0] if produced else None


def push_to_host(local: Path, slug: str) -> str | None:
    """rsync the markdown to the compute host. Returns a host:/path or None.

    CAIRN_PAPER_DEST is `host:/absolute/dir`, e.g. kestrel:/projects/.../refs.
    Big files never enter this repo; the registry page records where they went.
    """
    dest = os.environ.get("CAIRN_PAPER_DEST")
    if not dest:
        return None
    if not re.match(r"^[A-Za-z0-9_.-]+:/", dest):
        print(f"  transfer: skipped (CAIRN_PAPER_DEST={dest!r} is not host:/abs/dir)", file=sys.stderr)
        return None
    remote = f"{dest.rstrip('/')}/{slug}.md"
    try:
        subprocess.run(["rsync", "-q", str(local), remote], check=True, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"  transfer: FAILED ({exc})", file=sys.stderr)
        return None
    return remote


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("doi", help="DOI, doi.org URL, or doi: prefixed")
    parser.add_argument("--pdf", type=Path, help="convert to markdown with MinerU")
    parser.add_argument("--bib", type=Path, help="append the BibTeX entry to this references.bib")
    parser.add_argument("--bibkey", help="override the derived BibTeX key")
    parser.add_argument("--note", default="", help="one line on why this paper matters")
    parser.add_argument("--force", action="store_true", help="rewrite an existing registry page")
    args = parser.parse_args()

    doi = normalise_doi(args.doi)
    if not lib.DOI_RE.match(doi):
        sys.exit(f"'{doi}' is not a bare DOI (expected 10.xxxx/suffix)")

    slug = lib.slug_doi(doi)
    path = lib.paper_dir() / f"{slug}.md"
    if path.exists() and not args.force:
        print(f"{path.relative_to(lib.REPO_ROOT)} already exists — use --force to rewrite")
        return 0

    message = crossref(doi)
    bibkey = args.bibkey or derive_bibkey(message)
    meta = {
        "doi": doi,
        "title": (message.get("title") or [""])[0].strip(),
        "authors": author_names(message),
        "year": ((message.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0],
        "venue": (message.get("short-container-title") or message.get("container-title") or [""])[0],
        "bibkey": bibkey,
    }
    print(f"  {meta['title'][:70]}")
    print(f"  bibkey: {bibkey}")

    if args.pdf:
        if not args.pdf.exists():
            sys.exit(f"no such pdf: {args.pdf}")
        markdown = convert_pdf(args.pdf, Path(os.environ.get("CAIRN_MD_DIR", "/tmp")) / slug, slug)
        if markdown:
            meta["md"] = push_to_host(markdown, slug) or f"local:{markdown}"
            print(f"  markdown: {meta['md']}")

    if args.bib:
        entry = bibtex_for(doi, bibkey)
        if entry:
            print(f"  {args.bib}: {append_bib(args.bib, entry, bibkey)}")
        else:
            print("  bibtex: unavailable from doi.org", file=sys.stderr)

    body = args.note.strip() or "_Why this matters: not yet written._"
    path.parent.mkdir(parents=True, exist_ok=True)
    lib.Node(path=path, meta=meta, body=body).write()
    print(path.relative_to(lib.REPO_ROOT))

    citing = lib.paper_backlinks(lib.load_nodes()[0]).get(doi.lower(), [])
    if citing:
        print(f"  cited by {len(citing)} node(s): {', '.join(citing[:3])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
