---
description: Add a paper to the registry — CrossRef metadata, BibTeX key, full text on the compute host
---

Take a paper from "I found this" to "it's cited, converted and readable by an
agent", in one pass.

$ARGUMENTS is a DOI, a doi.org URL, or a title to look up. It may also name the
node whose `refs:` should gain the DOI.

## The loop this replaces

Download the PDF, import to Zotero for a bib key, run MinerU, copy the markdown
to kestrel, remember to cite it. Five steps, four tools, and the paper often
doesn't get recorded at all — which is the actual cost.

## 1. Get a DOI, don't guess one

If $ARGUMENTS is already a DOI, use it. If it's a title, resolve it — CrossRef
search, or the science connectors if they're available — and **confirm the
match with Jeff before writing anything**. A wrong DOI is worse than none: it
looks like a citation and it silently mis-attributes.

Never hand-write metadata. `add_paper.py` fetches CrossRef and refuses to write
without it, and that refusal is the feature.

## 2. Run it

```sh
$CAIRN_PATH/scripts/add_paper.py <doi> \
  --pdf ~/Downloads/<file>.pdf \
  --bib <path to the Overleaf clone>/references.bib \
  --note "<one line: why this paper matters to us>"
```

- `--pdf` converts with MinerU and rsyncs the markdown to `CAIRN_PAPER_DEST`.
  Both steps skip cleanly if the tool or the env var is missing, so running on
  a machine without MinerU still records the paper.
- `--bib` appends a BibTeX entry keyed to match, and is a no-op if the key is
  already there. Push that to Overleaf as usual.
- `--note` is the only part a human has to write. It's also the only part worth
  reading in six months, so don't skip it and don't pad it.

Environment, set once per machine:

| var | meaning |
|---|---|
| `CAIRN_MINERU` | MinerU command, if not `mineru` on PATH |
| `CAIRN_MD_DIR` | scratch dir for conversion output |
| `CAIRN_PAPER_DEST` | `host:/abs/dir` for the converted markdown, e.g. a project's `refs/` |

## 3. Link it to the work

A paper page nobody cites is a bookmark. If this paper bears on an existing
node, add the DOI to that node's `refs:` — the renderer then shows the paper on
the node, the node on the paper, and every other node citing the same paper.

If it *changes* something — supports a result, or contradicts one — that's a
node-level judgement, not a citation. Say so in the node body, and if it
overturns a finding, use a typed relation between the two nodes.

## 4. Show, then commit

Print the page and the BibTeX key. Wait for confirmation.

```sh
cd $CAIRN_PATH && make build && git add -A \
  && git commit -m "paper: <bibkey>" && git push
```

## Notes

- The DOI is the join key across Zotero, `references.bib`, the MinerU markdown
  and this registry. Keep it canonical and lowercase; `slug_doi()` handles the
  filename.
- The converted markdown never enters this repo — full texts run to tens of
  thousands of words. The page records `md: host:/path`.
- Compute nodes have no outbound network. Run this from a login node or the
  laptop; the script says so if CrossRef is unreachable.
