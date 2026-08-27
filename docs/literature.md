# Literature at corpus scale

**The question.** A project may have hundreds or thousands of downloaded PDFs.
Those can't each get a node. Can papers be clustered, with the *cluster* getting
a node?

**The short answer is yes, but not the way it first looks.** The instinct is a
pipeline that emits one node per cluster. That instinct is wrong here, and the
reason is the rule that overrides everything else in `CLAUDE.md`: an
auto-populated graph nobody trusts is the exact failure this project exists to
avoid. Twenty-five machine-written `direction` nodes are twenty-five nodes nobody
reads, and their presence makes the whole graph feel machine-filled.

So invert it:

> **The map is an artifact. One node describes the mapping run. A cluster becomes
> a node only when it has earned a claim — and the promotion event is a human
> reading it, not the clustering algorithm finishing.**

That is not a compromise. It is the same shape as everything else here: heavy
things stay outside and are referenced (`host:/path`), and a node is something
somebody stands behind.

---

## Where the pipeline lives

**Outside this repo, entirely.** `~/lit-atlas/` on kestrel, its own venv, its own
git repo referenced by `repo` + `commit`. Cairn never sees numpy, never sees a
parquet file, and keeps PyYAML as its only dependency.

```
0.  pdfs/*.pdf ──pdf2doi──▶ dois.txt + unresolved.txt
1.  dois.txt ──OpenAlex snapshot──▶ works.jsonl   (title, abstract, subfield)
             ──pre-computed embeddings──▶ emb.npy (no GPU needed)
2.  emb.npy ──frozen UMAP+HDBSCAN, or evoc──▶ labels
3.  ──toponymy (Anthropic backend)──▶ cluster names from key terms + exemplars
    ──datamapplot──▶ atlas.html
    ──▶ clusters.json  (cluster id, label, terms, exemplar DOIs, N, members, hash)
```

Stages 0–3 never touch this repo. Stage 4 is where Cairn comes in, and it is
small.

### The parts worth naming

| what | package | why this one |
|---|---|---|
| PDF → DOI | [`pdf2doi`](https://github.com/MicheleCotrufo/pdf2doi) (MIT) | everything downstream is DOI-keyed; GROBID only for stragglers |
| metadata + taxonomy | OpenAlex **snapshot** (CC0), [`pyalex`](https://github.com/J535D165/pyalex) (MIT) for small lookups | since 2026-02-13 the API needs a key and is metered — the snapshot is still free and unmetered, so pull it |
| embeddings | [`colonelwatch/abstracts-embeddings`](https://huggingface.co/datasets/colonelwatch/abstracts-embeddings) (CC0, 110M works) or Semantic Scholar `/paper/batch` `specter_v2` | skips the GPU entirely |
| clustering | [`evoc`](https://github.com/TutteInstitute/evoc) (BSD-2), or `hdbscan` (BSD-3) when you need `approximate_predict` | `evoc` is purpose-built to replace UMAP+HDBSCAN, is multi-granularity, and is numba+sklearn with no torch |
| cluster names | [`toponymy`](https://github.com/TutteInstitute/toponymy) (MIT) | hierarchical LLM naming with an Anthropic backend; the piece you'd otherwise hand-roll |
| the map | [`datamapplot`](https://github.com/TutteInstitute/datamapplot) (MIT), or sigma.js + graphology | see the caveat below |
| possibly all of 1–3 | [`latent-scope`](https://github.com/enjalot/latent-scope) (MIT) | end-to-end, already built on `datamapplot` + `evoc`. Evaluate before assembling your own |

Three traps found while checking these:

- **`datamapplot`'s `offline_mode=True` is not fully offline.** It inlines the JS
  and fonts, but still emits `maxcdn.bootstrapcdn.com` and Google Fonts CSS links
  unconditionally. It renders and interacts fine air-gapped — 3–5 cosmetic
  requests fail. Strip the tags, or use sigma.js + graphology for a genuinely
  zero-request page. It also pulls `dask[complete]`, which is a lot of install
  for one figure.
- **`@cosmograph/*` is CC-BY-NC-4.0**, where the MIT fork `@cosmos.gl/graph` sits
  at the same version number. Not a blocker for the academic collaborations this
  work sits in — but take the MIT package anyway, since it is the same code and
  costs nothing to prefer. Worth a check with tech transfer only if a map ever
  ships inside a deliverable to an industry partner.
- **`pyvis` is effectively dead** (0.3.2, Feb 2023; the fix for its broken offline
  mode has been an open PR since Dec 2022). Don't start there.

---

## Stability is the whole problem

Node ids are permanent and never renamed. A cluster whose identity changes when
the corpus grows would therefore be fatal — and locally-fit clustering is much
less stable than it looks:

- UMAP is non-deterministic unless `random_state` is set, and setting it disables
  multithreading, because the races are between threads.
- HDBSCAN is non-deterministic too. One reported case: BERTopic produced 4 topics
  on ten consecutive runs over 3,000+ abstracts, and 24 on the eleventh, same
  parameters.
- Leiden across seeds gives node-level ARI ~0.94 but Jaccard of retrieved sets
  only ~0.73 — boundaries move far more than the aggregate suggests.
- Even with a fixed seed, UMAP output changes with `numba`/`scipy` versions. A
  refit on a rebuilt venv is a different map wearing the same name.

### Two tiers, for two different jobs

**Tier A — anchored, permanently stable: group by OpenAlex `subfield`.** The
taxonomy (4 domains → 26 fields → 252 subfields → 4,516 topics, ASJC-derived) is
maintained outside this repo, so a node named for a subfield can never need
renaming. Use `subfield`, **not** `topic`: OpenAlex's own top-1 accuracy at the
topic level is 0.53 on average, so roughly half of those assignments are wrong.

The caveat, which refines this rather than killing it: OpenAlex *assignments*
churn deliberately. In 2026 alone they re-ran topic models on 1.27M works and
changed type classification on 49.6M (~10% of the catalogue), with the stated
philosophy that a reproducible default beats preserving labels of unknowable
provenance. **The id and the title stay valid; only membership drifts.** That is
strictly the better failure mode — with locally-fit HDBSCAN the identity itself
evaporates.

> **Requirement: any node recording a subfield count must pin the snapshot date
> in its body, or the number will not reproduce.**

**Tier B — project-specific, frozen then versioned.** Your corpus is a deliberate
selection, not a slice of all science, so the interesting structure is local. Fit
**once** at project founding, keep the model as an artifact, and thereafter
*assign* rather than refit:

```python
# ONCE, at founding — the pickle becomes the record of truth
reducer   = umap.UMAP(n_components=5, random_state=42, metric="cosine").fit(emb)
clusterer = hdbscan.HDBSCAN(min_cluster_size=40, prediction_data=True).fit(reducer.embedding_)
# min_cluster_size chosen so n_clusters lands in 10-30 — a readability limit, not a statistic
# → kestrel:/.../basemap-v1.pkl

# EVERY TIME AFTER — never creates a new cluster
labels, strengths = hdbscan.approximate_predict(clusterer, reducer.transform(new_emb))
```

`approximate_predict` answers "if we do not change the existing clusters, which
would HDBSCAN assign this to". Cluster ids (`mplastic-v1-c07`) are frozen the
moment the pickle is written. Note `sklearn.cluster.HDBSCAN` has no equivalent —
no `predict()`, no `prediction_data` — so use the `hdbscan` package.

**Refitting is a dated, deliberate event that renames nothing.** When drift
forces `basemap-v2`, match it against v1 by maximum-weight bipartite matching on
Jaccard overlap, then write *new* nodes using the relation vocabulary that already
exists:

| what happened | what to write |
|---|---|
| v2 cluster matches a v1 cluster (Jaccard > ~0.5) | new node, `supersedes: <v1-node>` |
| a v1 cluster split | two new nodes, each `supersedes:` the parent |
| a v1 cluster vanished | set its status (`closed` / `parked`) — never delete |
| a genuinely new region | new node, `parents: [<mapping-run node>]` |

This fits the existing grain exactly. `supersedes` already means "this replaces
that as the answer to use", relations may point backwards in time, and they are
backlinked so v1 stays findable from v2. Re-partitioning becomes ordinary graph
history rather than a schema problem.

### How many clusters

There is no correct value, and the scientometrics literature says so plainly:
two analysts can build meaningfully different maps from the same corpus depending
on threshold and resolution. What people actually do converges on **~30–80 papers
per cluster, capped by how many groups a person will read** — Open Knowledge Maps
hard-caps at 15, Clarivate fixes 10/326/2,444, Sjögårde & Ahlgren set a 50-article
minimum. For 500–2,000 PDFs that means **10–30 clusters**, and the readability cap
should bind before the statistics do.

Record the parameter *and the reason*, so a reader knows it was a choice.

### How a cluster gets a label you trust

LLM "descriptive" labels are already standard in bibliometrics and perform at or
near traditional characteristic labels. What matters is the input ranking:
**cluster key terms first, then representative titles**, and **centroid-nearest
exemplars beat most-cited ones** — highly-cited papers are often unrepresentative
of their cluster. Titles+keywords beat abstracts for fine-grained topics.

Reported as fragile: LLM labels are inconsistent run-to-run on identical
clusters, and can hallucinate a label disconnected from cluster content. So:
temperature 0, store the label, and on refresh diff against the stored one and
keep it unless the new one is clearly better. That is Clarivate's discipline —
for their 2026 micro-topic refresh they generated new labels, compared each
against the existing one topic-by-topic, and froze the macro/meso labels outright.

---

## What actually enters the graph

### One node for the mapping run

This is the node that makes the whole thing citable, and the `## What I did`
section is the part that carries the weight.

```yaml
type: experiment
title: "Can the mplastic PDF corpus be reduced to ~20 readable themes?"
project: mplastic
status: worked
repo: git@github.com:jlaw9/lit-atlas.git
commit: <SHA>
host: kestrel
artifacts:
  - kestrel:/projects/.../lit-atlas/mplastic/atlas.html
  - kestrel:/projects/.../lit-atlas/mplastic/clusters.json
  - kestrel:/projects/.../lit-atlas/mplastic/basemap-v1.pkl
```

`## What I did` is the corpus and the filter, and it must state the funnel:
1,840 PDFs → 1,712 resolved to DOIs → 1,588 found in the OpenAlex 2026-06
snapshot → 1,401 with abstracts; `min_cluster_size=40`, 22 clusters, 19% in
noise; `evoc==0.3.1`, `numba==0.61`; **snapshot pinned at 2026-06**. Every one of
those drops is invisible unless it is counted.

`## Result` is the interpretation and only you can write it. `## Next` is which
clusters look worth a node of their own.

### Cluster nodes, by hand, only where there is something to say

A `direction` (`status: open`) for a theme you are actively reading. An
`experiment` for a cluster that settles a claim — `status: dead` where the
literature refuted it. Children of the mapping-run node, so the lineage is the
argument.

```yaml
id: 2026-09-02-mplastic-lit-peptide-tethers
type: direction
title: Peptide-tethered filler interfaces — 47 papers, no mechanical data
project: mplastic
status: open
parents: [2026-09-01-mplastic-lit-atlas-v1]
```

The body carries the label and key terms verbatim, the 5 exemplar titles with
DOIs inline, `N=47`, cluster id `mplastic-v1-c07`, the `clusters.json` path and
content hash, and the snapshot date — then two or three sentences of *your*
reading: what the cluster is really about, and what is missing from it. That last
part is the only reason the node exists.

Clusters you haven't reviewed go to `inbox/` via `bin/cairn capture`, and
`/triage` promotes them. That satisfies "never commit a node Jeff hasn't seen"
with machinery that already exists.

### Should a cluster node carry DOIs?

Both, split by what each one audits:

- **A count + a `host:/path` + a content hash** audits *membership*. This has to
  be an artifact: membership changes with every snapshot pin, and 400 DOIs in
  `refs:` would break "nothing heavy enters this repo" and drown the validator's
  warnings in noise.
- **3–8 exemplar DOIs inline in the body prose**, not in `refs:`, audits *the
  label*. Zero DOIs makes the node unfalsifiable — you could not check
  "Peptide-tethered filler interfaces" against anything. Centroid-nearest, never
  most-cited. Titles and DOIs come from the pipeline's metadata, never from
  memory, which satisfies the DOI rule without minting pages.

### When does a paper get its own page?

Three tiers, and the promotion event between them is **reading**, not clustering.

| tier | where it lives | how many |
|---|---|---|
| corpus member | a row in `clusters.json` on kestrel. No page, no `refs:` entry | thousands |
| cited evidence | `papers/<doi-slug>.md` via `cairn add_paper`, plus `refs:` on the node whose claim depends on it | tens |
| a claim of its own | an `experiment` node — a literature finding *is* an experiment | a handful |

**The governing rule: `refs:` is a dependency claim, not a bibliography.** A DOI
belongs there when a node's argument would change if that paper were wrong.
Corpus membership is not dependency — being in the same embedding neighbourhood
is not evidence for anything.

That is also why a `papers/` page is expensive: it carries promises —
CrossRef-verified metadata, a `bibkey` matching Zotero's pattern, an `md:` path
to converted full text. You cannot keep those for 400 papers you haven't read,
and `add_paper` correctly refuses to write a page it could not verify. Minting
pages from cluster membership would turn the registry from a lookup table you
trust into one you don't.

**The graduation path is the graph doing its job.** You read an exemplar; it
changes what you believe; it gets a `papers/` page and a `refs:` entry on a
*child* node of the cluster — a literature finding with a real claim ("Can peptide
tethers survive melt processing?", `status: dead`). The lineage cluster → finding
→ paper is then visible, and the cluster node's value is retrospective: it is the
record of *how you found* the paper that mattered.

---

## Failure modes

Numbered because they are the checklist for whether a cluster node can be
trusted.

1. **The noise bucket silently breaks coverage.** HDBSCAN can dump 30–74% of a
   small corpus into `-1`. If cluster nodes cover 60% of the corpus, "did we
   already look at this?" returns a confident *no* for the missing 40% — and a
   graph at 60% coverage is worse than none. Report the noise fraction as a
   headline number; prefer `evoc` or k-means (no outliers) at this scale; if you
   keep HDBSCAN, create an explicit `<project>-unclustered` node so the gap is a
   node rather than an absence.
2. **The 12%-untopiced hole in Tier A.** ~12% of OpenAlex works have no topic at
   all. Same shape of problem, on the tier you were relying on for stability.
   Count them and say so.
3. **Snapshot non-reproducibility.** "47 papers in Polymer Science" will not
   reproduce next quarter. Pin the snapshot date in the body — the claim must be
   falsifiable against a stated snapshot, not against "OpenAlex".
4. **A node named for an unstable cluster.** Ids are permanent; partitions are
   not. Hence the two-tier scheme.
5. **Environment drift re-partitions silently.** Pin versions in the body; treat
   the pickled base map, not the code, as the artifact of record.
6. **Label churn without partition change.** A node whose title drifts each
   refresh reads as untrustworthy even when the grouping is solid. Temperature 0,
   store, diff, keep.
7. **A cluster node nobody wrote.** Clusters land in `inbox/`; humans promote.
8. **Artifact drift** — the node says `N=47`, `clusters.json` has been
   overwritten. Content hash and row count in the body.
9. **Coverage gaps compound invisibly.** Not every PDF yields a DOI, not every
   DOI is in the snapshot, only about half of OpenAlex works have usable
   abstracts. Keep `unresolved.txt`; state the funnel.
10. **Granularity is unfalsifiable.** No experiment shows 12 clusters right and
    30 wrong. Record the parameter and the reason.
11. **Embedding-model choice is as permanent as the node ids.** Swapping models
    re-partitions everything. Decide once; record it.
12. **Hard clustering mis-routes multi-topic papers.** One document, one path, so
    genuinely interdisciplinary papers get filed arbitrarily and become invisible
    from the cluster where they would matter — and those are exactly the
    cross-project papers. OpenAlex gives up to 3 topics per work; `refs:` can cite
    a paper regardless of which cluster owns it; and a `[[node-id]]` prose link is
    the right way to say "this also bears on the polycrystal thread".

---

## The clustered-graph project from the LinkedIn post

**Identified, and confirmed by Jeff: Jay Alammar's "Inside NeurIPS 2025: The
Year's AI Research, Mapped"** ([map](https://jalammar.github.io/assets/neurips_2025.html),
[write-up](https://newsletter.languagemodels.co/p/the-illustrated-neurips-2025-a-visual)).

The recipe: ~5,787 NeurIPS papers → Cohere Embed 4 → k-means, then hierarchical
clustering of the centroids → UMAP → cluster names *and* per-paper summaries from
an LLM → a customised `datamapplot`.

**There is no repo** — he published the map and the write-up, not the code. So the
reusable part is the recipe plus `datamapplot`, which is the one dependency the
pipeline above already names. Two things in his approach are worth copying
directly and one is worth not copying:

- **Copy: k-means, then cluster the centroids hierarchically.** k-means produces
  no noise bucket, which sidesteps failure mode 1 outright — and the hierarchy
  over centroids is what gives readable zoom levels without a second fit. At
  1,000–2,000 PDFs this is a better default than UMAP+HDBSCAN.
- **Copy: per-paper summaries, not just cluster labels.** He generated both. The
  per-paper line is what makes an exemplar checkable at a glance, which is
  exactly what a cluster node's body needs to be falsifiable.
- **Don't copy: a one-off map with no frozen model.** A conference proceedings is
  a closed corpus mapped once; your corpora grow. His pipeline has no reason to
  care about assigning new papers to existing clusters, and yours has to — see
  the two-tier scheme above.

The other candidates found while searching, kept because several are closer to
what a *reusable* pipeline looks like than Alammar's one-off is:

| project | repo | note |
|---|---|---|
| OpenAlex Mapper (Noichl, Utrecht) | [MNoichl/openalex_mapper](https://github.com/MNoichl/openalex_mapper) | discipline-tuned SPECTER2 + UMAP, pre-trained on 250k OpenAlex records; best-known in the niche |
| AI Safety Graph (Apart Research) | [ai-safety-graph/AISafetyGraph](https://github.com/ai-safety-graph/AISafetyGraph) | 5,000+ alignment papers clustered by an LLM; Apart posts heavily on LinkedIn |
| pubmed-landscape (Berens lab) | [berenslab/pubmed-landscape](https://github.com/berenslab/pubmed-landscape) | 21M abstracts, PubMedBERT + large-scale t-SNE, *Patterns* 2024 |
| paper_map | [huangyan28/paper_map](https://github.com/huangyan28/paper_map) | closest textual match — OpenAlex → SPECTER2 → UMAP → HDBSCAN → interactive map |
| embedding-atlas | [apple/embedding-atlas](https://github.com/apple/embedding-atlas) | heavily posted; plausible if the project was someone's atlas built *on* this |

**One question collapses the list:** was it a black-background point cloud with
floating text labels? That separates the Alammar family from the Noichl and
Berens-lab families outright.
