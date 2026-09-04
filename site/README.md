# The Cairn site

Hand-written static HTML. **No generator, no framework, no build step, no CDN,
no dependency** — the same shape as `build/graph.html`, and for the same reason:
a thing you can open from disk cannot rot because a toolchain moved.

Published to GitHub Pages from this directory by
`.github/workflows/pages.yml`.

## Not published yet

The workflow is **`workflow_dispatch` only**. Merging it deploys nothing;
someone has to run it from the Actions tab.

That is deliberate. `2026-08-05-cairn-release-review` is still `todo` — Cairn was
written on lab time, so NLR holds the release disposition, and that node says
plainly that *"a public GitHub push is a release. Not a draft, not a staging
step."* A Pages site is at least as much a release: it is served to anyone with
the URL and indexed. Add the `on: push` trigger once tech transfer has given a
determination (the commented block in the workflow is the exact change).

## What is here

| path | what |
|---|---|
| `index.html` | overview — the problem, the prior art's rock, the one rule |
| `model.html` | the schema: five node types, two kinds of edge, four relations |
| `workflows.html` | install, the session loop, the four ways work starts |
| `map.html` | the map, with screenshots and the live demo |
| `design.html` | the nine decisions, what it isn't, why this can exist now |
| `blog/` | the notebook — dated entries, `_template.html` to copy |
| `cairn.css` | the whole stylesheet |
| `cairn.js` | theme toggle + table-of-contents highlighting. That is all it does |
| `img/` | the mark, and four screenshots of the real map |
| `demo/graph.html` | **generated** — see below |
| `.nojekyll` | serve the files as they are; no Jekyll processing |

## The visual system is not this site's to invent

The palette, the light/dark pairs, the status colours, the relation hues and the
mono/serif type pairing are lifted from `scripts/graph_template.html`, so the
mark, the map, the deck and this site stay one system.

**If you change a colour, change it there too — the map is the authority.**
`cairn.css` says the same thing at the top of the file.

Three theme states are all defined on purpose: bare `:root` is light, a
`prefers-color-scheme: dark` block guarded with `:not([data-theme="light"])`
follows the OS, and `:root[data-theme="dark"]` lets the toggle win in both
directions.

### Cartoons are inline SVG

Not images. They inherit the theme, stay crisp at any zoom, and diff as text.
Two rules learned the hard way:

- **CSS `var()` does not resolve in SVG *presentation attributes*.**
  `fill="var(--bad)"` silently renders black. Use a class
  (`class="f-bad"`, defined in `cairn.css`) or `style="fill: var(--bad)"`.
- **Every cartoon needs a real `aria-label`** describing what the diagram
  *shows*, not what it is called. The label is the only version a screen reader
  gets.

## Adding a page

Copy the `<header class="masthead">` block from any page, set
`aria-current="page"` on the right nav link, and add the page to the nav in
**every** page — there is no include mechanism and that is the cost of having no
build step. `make site-check` catches a page nothing links to.

## Adding a notebook entry

```sh
cp blog/_template.html blog/2026-09-14-what-broke.html
```

Fill in the `<title>`, `<h1>`, meta description and the `postmeta` line, then add
one `<li>` to the list in `blog/index.html`. That is the whole mechanism.

## The live demo

`demo/graph.html` is a **generated** render of a scrubbed export of the `cairn`
project's own subgraph — the real design record, with real dead ends, which no
synthetic example can be.

```sh
make site-demo            # refuses, and prints the review pass
make site-demo ACK=1      # after you have read it
```

It is gitignored, along with `example/`, until the release review clears — so
`git add -A` cannot sweep a publication of real node bodies into a commit. The
`.gitignore` entry says exactly how to undo that.

`CAIRN_EXAMPLE_EXCLUDE` in the Makefile holds back nodes that must not be
published at all. Exclusions are **named in the generated `example/README.md`**
rather than silently dropped, and the exporter refuses an exclusion that would
leave a dangling `parents` edge or drop a typed relation — a missing edge and a
hidden edge must never look the same.

## Checks

```sh
make site-check           # every internal link and #fragment resolves
make site-serve           # preview at http://localhost:8000
```

`site-check` also runs in the deploy workflow. It does **not** fetch external
URLs: a link checker that needs the network fails for reasons that have nothing
to do with the commit, and a deploy blocked by someone else's downtime is a
deploy people learn to force past.

## Figures go stale

Node and project counts are written into `index.html` and `design.html` as
literal text, dated in the footer. Refresh them when they drift:

```sh
CAIRN_ROOT=<your graph> bin/cairn validate   # prints the node count
```
