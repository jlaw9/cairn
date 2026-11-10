# Summary figures

A node records a claim and how it came out. The fastest way to read how it came
out is usually a picture: the loss curve that never came down, the parity plot
with the ionics off to one side, the screenshot of the page that finally
rendered. A summary figure is that picture, kept with the node, so someone
browsing the map months later gets the story without reading the body.

## What a good one is

**The plot or screenshot that would let you skip reading the node.** Not every
figure the work produced. Just the one that shows the result, or the reason the
thread closed.

- **One per closed node is the target.** A `dead` experiment's figure is the most
  valuable kind: it shows *why* it died, which is the thing nobody remembers.
  A second or third figure is fine when the story really has two halves (before
  and after, the failure and the fix). Ten is a gallery, and a gallery belongs
  on a host, not in git.
- **Readable at panel width.** The panel is about 400 px wide. Axis labels you
  can read there, one message per figure, no dashboards.
- **Captioned.** One line saying what to look at: "MAE by solvent class; ionics
  off the chart". The caption is what search and the story view will read.
- **Small.** Under 300 kB. `cairn figure` usually gets you there on its own.
- **SVG for a plot you generate** (it is text, and it can follow the reader's
  dark or light theme from inside an `<img>`). WebP or PNG for a screenshot.

The full-resolution original, the notebook and the raw numbers stay where they
are, linked from `artifacts:`. The figure is a summary, not the archive.

## Adding one

```sh
bin/cairn figure 2026-08-02-prekd-cosmo-baseline parity.png \
  --caption "MAE by solvent class; ionics off the chart"
bin/cairn figure prekd-cosmo-baseline second.png          # a partial id works, as for `note`
bin/cairn figure 2026-08-02-prekd-cosmo-baseline big.png --dry-run
bin/cairn figure 2026-08-02-prekd-cosmo-baseline shot.png --no-commit
```

What it does:

1. **Names it.** The first figure is `assets/<id>.<ext>`. Later ones are
   `assets/<id>--2.<ext>`, `--3`, and so on, one past the highest number in use,
   so the order is the order they were added. There is no field. The filename is
   the link, as it always was.
2. **Shrinks it, if Pillow is installed.** A raster image over 300 kB or wider
   than 1600 px on its long edge is scaled down to 1600 px and re-encoded as WebP
   (quality 82), or kept in its own format if that comes out smaller. A PNG or
   SVG that is already small is copied untouched, so a crisp plot stays crisp.
   GIF and SVG are never re-encoded. Without Pillow the file is copied as-is,
   with a warning if it is over the cap. Pillow is optional. PyYAML is still the
   only thing Cairn needs.
3. **Captions it.** `--caption` adds a dated bullet under `## Figures` in the
   body. It is a body edit, not a status change, so `updated` and `history` do
   not move (the same rule as `cairn note`).
4. **Commits it.** The figure and, when there is a caption, the node, in one
   commit with `--only`, so nothing else comes along, plus a `Cairn-Review:`
   trailer. A node that is still an uncommitted draft keeps its figure
   uncommitted too, so `cairn discard` can still remove both. `--no-commit`
   writes without committing. `--dry-run` writes nothing.

It refuses an unknown node, a file that is not `.svg .png .jpg .jpeg .gif .webp`
(or whose bytes do not match its name), and a graph that is not a git repo,
unless you pass `--no-commit`.

**From the map**, with `cairn serve` running, the panel has an "Add a figure"
box. Drop an image on the panel, paste one, or click to choose a file. The page
scales it to 1600 px WebP before sending it, then the server runs the same
`cairn figure`. With the server off, the map shows figures and never offers to
write.

## Where they show

- **Panel:** every figure, in order, directly under the status pills, each with
  its caption. Click one to open it full size.
- **Map:** a small tab on the top-left corner of the glyph means the node has a
  figure.
- **Hover card:** a thumbnail of the first figure.

## Storage: why this is fine in git

The numbers at the time of writing: **84 nodes, 68 of them terminal, and ~20
new nodes a month.** About four in five nodes end up closed, so call it ~16
closed nodes a month.

| | figures | size each | per month |
|---|---|---|---|
| low | 1 per closed node | ~100 kB | ~1.6 MB |
| high | 2 per closed node | ~150 kB | ~4.8 MB |

So **~3–5 MB a month** in git at the realistic end, plus a one-off ~7–10 MB if
the 68 nodes already closed each get a figure back-filled. That is ~40–60 MB a
year. A clone of a few hundred MB is still quick, and GitHub's guidance
is to keep a repository under 1 GB, which is well over a decade away at this
rate. **This is fine for years.** Nothing here needs Git LFS, a separate
asset repo, or a CDN.

Two things keep it that way:

- **The 300 kB cap.** It is a `validate` warning, not an error, so capture is
  never blocked. The warning says how to shrink the file. A binary in git
  history stays there forever, even after it is deleted, so the cap matters
  more than the total.
- **The escape hatch for anything large is `artifacts:`.** A full-resolution
  image, a video, a 40-page PDF or an interactive plot goes on a host, and the
  node points to it: an `http(s)://…` URL or a `host:/path` entry in
  `artifacts:` (`bin/cairn edit <id> --artifact <url>`). The figure in `assets/`
  stays a summary.

If figures ever really outgrow this, the convention moves cleanly: they are
addressed by filename only, so `assets/` could become a submodule or an LFS path
without changing a single node.
