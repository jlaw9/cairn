---
id: 2026-08-05-photopoly-vitrification-ceiling
type: experiment
title: Can a reported "final Tg" be fitted as Tgp?
project: photopoly
status: dead
created: 2026-08-05
updated: 2026-08-05
parents: [2026-08-05-photopoly-predict-tg-meth-acrylate]
refs: [10.1021/ma101296j, 10.1021/ma010542g]
history:
  - {date: 2026-08-05, status: dead, note: "vitrification-limited, and the bias is formulation-dependent"}
---

## Claim

A literature "final Tg" for a cured network can be used as Tgp, the
full-conversion ceiling, in the Tgm/Tgp decomposition.

**What would prove this wrong:** evidence that reported final Tg tracks the cure
temperature rather than the chemistry.

## What I did

Read the Bowman-group work on cure temperature and Tg in crosslinked
photopolymers — 19 papers mentioning both Tg and conversion, of which two carry
the quantitative result. No calculation and no instrument: the corpus is the
instrument.

## Result

**Refuted, and it is the constraint that shapes the whole project.** Networks
vitrify before full cure: mobility collapses as the rising Tg approaches Tcure
and conversion stops short of x = 1. Ye, Cramer and Bowman quantified it across
Tg 35-205 °C — when Tcure < Tgmax − Tg½width, **Tg ≈ Tcure + Tg½width**. The 2001
precursor found Tg − Tcure as large as 100 °C for heterogeneous multi(EG)DMA.

So a reported final Tg is a property of the oven, not only of the resin. Fitting
one as Tgp biases the ceiling low and biases it *formulation-dependently*, which
is worse than a constant offset because no single correction term removes it.

## Next

`cure_temperature_C` becomes a mandatory extraction column, and the rule gets
tested on our own material and instrument before the physics layer is trusted.
