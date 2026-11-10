#!/usr/bin/env python3
"""Attach a summary figure to a node: the plot or screenshot that tells its story.

    cairn figure 2026-08-02-prekd-cosmo-baseline mae-by-class.png
    cairn figure prekd-cosmo-baseline shot.png --caption "MAE by solvent class; ionics off the chart"
    cairn figure 2026-08-02-prekd-cosmo-baseline plot.png --dry-run
    cairn figure 2026-08-02-prekd-cosmo-baseline plot.png --no-commit

The gap this fills: a closed node is a paragraph, and the reason it closed is
usually a picture — the curve that never came down, the parity plot with the
ionics off to one side. The `assets/<id>.<ext>` convention could hold one, but
getting it there meant knowing the convention, picking the name by hand,
shrinking the file yourself and committing it separately. That is capture cost,
and capture cost is what kills these systems.

**Where it lands.** `assets/<id>.<ext>` for a node's first figure, then
`assets/<id>--2.<ext>`, `--3`, ... — ordered, and still derived from the filename
alone, so there is no field to keep in sync (docs/figures.md).

**Shrinking.** With Pillow importable, a raster image over the size cap or over
1600 px on its long edge is scaled to 1600 px and re-encoded as WebP (quality
82) when that is smaller; a PNG or SVG already small enough is copied untouched,
so a crisp plot stays crisp. Without Pillow the file is copied as-is and the
command warns if it is over the cap. Pillow is strictly optional — PyYAML stays
the only dependency.

**A caption is a body edit, not a status change.** `--caption` appends a dated
bullet under `## Figures`, the same mechanics as `cairn note`: `status`,
`updated` and `history` do not move, because attaching a picture is not a claim
about the state of the work.

**It commits the way `cairn note` does** — the figure and, when there is a
caption, the node, together, with `--only` so nothing else rides along, and a
`Cairn-Review:` trailer. `--no-commit` leaves both on disk; `--dry-run` says
what would happen and writes nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lib
import note

#: The long edge a summary figure is scaled down to. A panel is ~400 px wide and
#: a lightbox a laptop screen; 1600 covers a retina screen at either.
MAX_EDGE = 1600

#: WebP quality. 82 is where text in a screenshot stays sharp and a plot's
#: flat colours stop costing bytes.
WEBP_QUALITY = 82

#: Formats Pillow may re-encode. GIF is left alone (it may be animated) and SVG
#: is text, which is already the best case this repo has.
RASTER = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}

#: Leading bytes per type: a file named `.png` that is not one would render as
#: a broken image on the map, which is the silent failure the validator's type
#: check exists to prevent. SVG is text, so it is checked for its root element.
MAGIC = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
}


def kb(n: int) -> str:
    return f"{n / 1000:.0f} kB" if n >= 1000 else f"{n} B"


def refuse(message: str) -> int:
    print(f"cairn: {message}", file=sys.stderr)
    return 1


def looks_like(data: bytes, suffix: str) -> bool:
    if suffix in MAGIC:
        return data.startswith(MAGIC[suffix])
    if suffix == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if suffix == ".svg":
        head = data[:4096].decode("utf-8", errors="replace").lower()
        return "<svg" in head
    return False


def pillow():
    """`PIL.Image`, or None. Imported here, never at module level, so a machine
    without Pillow runs every other command exactly as before."""
    try:
        from PIL import Image  # type: ignore
    except Exception:          # noqa: BLE001 - ImportError, or a broken install
        return None
    return Image


def encode(image, fmt: str) -> bytes | None:
    """`image` as `fmt` bytes, or None if this Pillow cannot write it (a build
    without libwebp, say)."""
    out = io.BytesIO()
    try:
        if fmt == "WEBP":
            image.save(out, "WEBP", quality=WEBP_QUALITY, method=6)
        elif fmt == "JPEG":
            image.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
        else:
            image.save(out, fmt, optimize=True)
    except Exception:          # noqa: BLE001 - codec missing, or a mode it refuses
        return None
    return out.getvalue()


def shrink(data: bytes, suffix: str) -> tuple[bytes, str, str]:
    """(bytes, suffix, what happened) for the figure as it should be stored.

    Untouched unless it is a raster over the cap or over MAX_EDGE. Then: scale to
    MAX_EDGE, and keep whichever of WebP and the original format is smaller.
    """
    size = len(data)
    if suffix not in RASTER:
        return data, suffix, "copied as-is"
    Image = pillow()
    if Image is None:
        return data, suffix, "copied as-is; Pillow not installed"
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:   # noqa: BLE001 - truncated, or not what it claims
        return data, suffix, f"copied as-is; Pillow could not read it: {exc}"
    width, height = image.size
    if size <= lib.ASSET_MAX_BYTES and max(width, height) <= MAX_EDGE:
        return data, suffix, f"copied as-is, {width}x{height}"

    try:
        from PIL import ImageOps  # type: ignore
        image = ImageOps.exif_transpose(image)
    except Exception:          # noqa: BLE001 - old Pillow; orientation is cosmetic
        pass
    resized = max(width, height) > MAX_EDGE
    if resized:
        ratio = MAX_EDGE / float(max(width, height))
        box = (max(1, round(width * ratio)), max(1, round(height * ratio)))
        resample = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(box, resample)
    if image.mode not in ("RGB", "RGBA"):
        keep_alpha = image.mode in ("LA", "PA") or "transparency" in image.info
        image = image.convert("RGBA" if keep_alpha else "RGB")

    candidates = []
    webp = encode(image, "WEBP")
    if webp is not None:
        candidates.append((len(webp), ".webp", webp))
    if resized:
        same = encode(image, RASTER[suffix])
        if same is not None:
            candidates.append((len(same), suffix, same))
    else:
        candidates.append((size, suffix, data))
    if not candidates:
        return data, suffix, "copied as-is; Pillow could not re-encode it"
    best_size, best_suffix, best = min(candidates, key=lambda c: c[0])
    w, h = image.size
    if best is data:
        return data, suffix, f"copied as-is, {width}x{height}; re-encoding was not smaller"
    return best, best_suffix, (
        f"{suffix[1:]} {width}x{height} {kb(size)} -> "
        f"{best_suffix[1:]} {w}x{h} {kb(best_size)}")


def next_name(node_id: str, suffix: str, nodes: dict) -> str:
    """`<id><suffix>` for a first figure, else `<id>--<n><suffix>` one past the
    highest slot in use — so figures stay in the order they were added even if
    an earlier one is later removed by hand."""
    existing = lib.find_assets(ids=set(nodes)).get(node_id, [])
    if not existing:
        return f"{node_id}{suffix}"
    top = max(lib.figure_slot(path.stem, nodes)[1] for path in existing)
    return f"{node_id}--{top + 1}{suffix}"


def main() -> int:
    p = argparse.ArgumentParser(
        prog="cairn figure",
        description="Copy an image into assets/ as a node's next summary figure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False)
    p.add_argument("node", help="node id, or enough of one to be unambiguous")
    p.add_argument("file", help=f"the image: {' '.join(lib.ASSET_SUFFIXES)}")
    p.add_argument("--caption", default="",
                   help="one line; appended under `## Figures` in the body")
    p.add_argument("--date", default="", help="ISO date for the caption; default today")
    p.add_argument("--no-commit", action="store_true",
                   help="write the figure (and caption) but leave them uncommitted")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would be written, write nothing")
    args = p.parse_args()

    source = Path(args.file).expanduser()
    suffix = source.suffix.lower()
    if suffix not in lib.ASSET_SUFFIXES:
        return refuse(f"{source.name} is not a figure type — the map shows assets in "
                      f"an <img>, so it takes {' '.join(lib.ASSET_SUFFIXES)}. A PDF or "
                      f"a notebook belongs under `artifacts:` as host:/path.")
    if not source.is_file():
        return refuse(f"no such file: {source}")
    data = source.read_bytes()
    if not data:
        return refuse(f"{source.name} is empty")
    if not looks_like(data, suffix):
        return refuse(f"{source.name} does not look like a {suffix[1:]} file — "
                      f"renamed, or truncated? It would render as a broken image.")

    when = lib.as_date(args.date) if args.date else dt.date.today()
    if args.date and when is None:
        return refuse(f"--date {args.date!r} is not an ISO date")

    nodes, errors = lib.load_nodes()
    node = nodes.get(args.node)
    if node is None:
        if any(args.node in e for e in errors):
            return refuse(f"{args.node} does not parse — fix it by hand first:\n  "
                          + "\n  ".join(e for e in errors if args.node in e))
        node = note.resolve(nodes, args.node)       # prints its own refusal
        if node is None:
            return 1

    root = lib.REPO_ROOT
    commit = not (args.no_commit or args.dry_run)
    # Committing is half of what this does, so a graph git cannot see is refused
    # rather than half-done. --no-commit is the way to write one anyway.
    if commit:
        code, out = note.git("rev-parse", "--is-inside-work-tree")
        if code != 0 or out.strip() != "true":
            return refuse(f"the graph at {root} is not a git repo, so the figure "
                          "cannot be committed; pass --no-commit to write it anyway.")

    stored, out_suffix, how = shrink(data, suffix)
    name = next_name(node.id, out_suffix, nodes)
    target = lib.asset_dir(root) / name
    asset_rel = Path("assets") / name
    node_rel = node.path.relative_to(root)
    caption = " ".join(args.caption.split())
    line = lib.format_figure_line(name, caption, when) if caption else ""
    over = len(stored) > lib.ASSET_MAX_BYTES

    if args.dry_run:
        print(f"would write {asset_rel}  {kb(len(stored))} — {how}")
        if line:
            print(f"would append to {node_rel} under ## Figures:\n  {line}")
        if over:
            print(f"  warning: over the {lib.ASSET_MAX_BYTES // 1000} kB cap"
                  + ("" if pillow() else " — install Pillow to have this shrink it"))
        print("would commit" if not args.no_commit else "would leave it uncommitted")
        print("\n  dry run — nothing written")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(stored)
    # serve.py reads these two lines: the asset, then the node file, which is
    # where `committed` and the reopened node come from.
    print(f"{asset_rel}  {kb(len(stored))} — {how}")
    print(node_rel)
    if line:
        lib.append_figure_caption(node, name, caption, when)
        node.write()
        print(f"  {line}")
    if over:
        hint = ("" if pillow() else " Install Pillow (`pip install pillow`) and re-add "
                "it to have it scaled and re-encoded, or")
        print(f"  warning: {kb(len(stored))} is over the "
              f"{lib.ASSET_MAX_BYTES // 1000} kB cap.{hint} re-export it smaller; "
              f"the full-size file belongs under `artifacts:`.", file=sys.stderr)

    if not commit:
        print("\n  not committed (--no-commit). It won't reach your other machine "
              "until it is.")
        return 0

    # A draft node is the user's to admit (`cairn review`); its figure waits
    # with it, untracked, so `cairn discard` can still take both.
    if note.working_state(node_rel) == "untracked":
        print(f"\n  {node.id} is not committed yet — `cairn review {node.id}` "
              f"first, then `git add {asset_rel} && git commit`.")
        return 1

    paths = [str(asset_rel)] + ([str(node_rel)] if line else [])
    code, out = note.git("add", "--", str(asset_rel))
    if code == 0:
        message = (f"figure on {node.id}: {name}"
                   + (f" — {caption[:60]}" if caption else "")
                   + f"\n\n{lib.review_trailer(note.whoami(), node.id)}\n")
        code, out = note.git("commit", "--only", *paths, "-m", message)
    if code == 0:
        print("  committed. `cairn sync --push` to make it visible elsewhere.")
    else:
        print("\n  The figure is written, but the commit failed — nothing is lost:")
        for out_line in out.splitlines()[:10]:
            print(f"    {out_line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
