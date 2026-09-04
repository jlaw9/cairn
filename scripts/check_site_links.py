#!/usr/bin/env python3
"""Check every internal link and asset reference in the site.

The site is hand-written HTML on purpose — no generator, no build step — which
means nothing catches a typo in an `href` the way a generator's link resolution
would. This does, and it runs in CI before a deploy.

It checks three things and deliberately nothing else:

1. **Local files resolve.** Every `href`/`src` that isn't external, `mailto:`
   or a bare fragment points at a file that exists.
2. **Fragments resolve.** `model.html#edges` requires an `id="edges"` in
   `model.html`. This is the failure that actually happens: sections get
   renamed and the cross-page links that pointed at them rot silently, landing
   the reader at the top of a long page with no indication anything is wrong.
3. **Every page is reachable.** A page nobody links to is a page nobody reads.

External URLs are *not* fetched. A link checker that needs the network fails
for reasons that have nothing to do with the commit, and a deploy blocked by
somebody else's downtime is a deploy people learn to force past.

    python3 scripts/check_site_links.py site
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: href/src on any element. Single or double quoted, attribute order-insensitive.
REF = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.I)

#: `id="..."` anywhere, which is what a fragment has to land on.
ID = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.I)

EXTERNAL = ("http://", "https://", "mailto:", "tel:", "data:", "//")

#: Generated pages are not hand-written, so a typo is not the failure mode, and
#: their `href`s are built at runtime — `demo/graph.html` writes
#: `href="${esc(n.commitUrl)}"` from JavaScript, which is not a broken link. They
#: are still valid link *targets*; they are just not scanned as sources.
GENERATED = ("demo",)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "site").resolve()
    if not root.is_dir():
        print(f"check_site_links: {root} is not a directory", file=sys.stderr)
        return 2

    pages = sorted(root.rglob("*.html"))
    if not pages:
        print(f"check_site_links: no .html under {root}", file=sys.stderr)
        return 2

    # Collect the anchors each page offers before resolving anything, since a
    # link may point forward to a page not yet read.
    ids: dict[Path, set[str]] = {}
    for page in pages:
        ids[page] = set(ID.findall(page.read_text(encoding="utf-8")))

    errors: list[str] = []
    linked: set[Path] = set()

    for page in pages:
        rel = page.relative_to(root)
        if set(rel.parts) & set(GENERATED):
            continue
        for raw in REF.findall(page.read_text(encoding="utf-8")):
            ref = raw.strip()
            if not ref or ref.startswith(EXTERNAL) or ref.startswith("#"):
                # A bare fragment is same-page; check it against this page.
                if ref.startswith("#") and len(ref) > 1:
                    if ref[1:] not in ids[page]:
                        errors.append(f"{rel}: '#{ref[1:]}' — no such id on this page")
                continue

            path_part, _, frag = ref.partition("#")
            target = (page.parent / path_part).resolve() if path_part else page

            if not target.exists():
                errors.append(f"{rel}: '{ref}' — no such file")
                continue

            if target.suffix.lower() == ".html":
                linked.add(target)
                if frag and frag not in ids.get(target, set()):
                    errors.append(
                        f"{rel}: '{ref}' — {target.relative_to(root)} has no id='{frag}'")

    # index.html is the entry point, so nothing has to link to it. A template
    # is a file you copy, not one you link.
    for page in pages:
        if page in linked or page.name == "index.html" or page.name.startswith("_"):
            continue
        errors.append(f"{page.relative_to(root)}: no page links to this")

    for e in errors:
        print(f"  {e}")

    n = len(pages)
    print(f"check_site_links: {n} page(s), {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
