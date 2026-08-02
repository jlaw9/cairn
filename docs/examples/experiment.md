---
id: 2026-04-20-prekd-cosmo-baseline
type: experiment
title: COSMO-RS baseline on the 40-solvent set
project: prekd
status: dead
created: 2026-04-20
updated: 2026-05-11
repo: git@github.com:jlaw9/prekd.git
commit: a3f9c21
host: kestrel
artifacts:
  - kestrel:/scratch/jlaw/prekd/run-0142/summary.json
parents: [2026-04-06-prekd-scoping]
refs: [10.1021/acs.jced.3c00123]
history:
  - {date: 2026-04-20, status: running, note: kicked off on kestrel}
  - {date: 2026-05-11, status: dead, note: solvation model is wrong for ionics, MAE 1.4 log units}
---

## Claim

COSMO-RS free energies alone predict relative rate constants.

## Result

Fails on the ionic subset. **MAE 1.4 log units**, and the sign flips for
three of the quaternary ammonium cases. Not recoverable by refitting.
