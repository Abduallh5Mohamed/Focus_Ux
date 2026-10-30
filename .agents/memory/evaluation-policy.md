---
name: Evaluation policy changes
description: Prevent older evaluation artifacts from bypassing stricter acceptance requirements.
---
Whenever acceptance checks become stricter, require regeneration of both baseline
and candidate evaluation reports before allowing adoption.

**Why:** Reusing a previously green report can bypass newly required coverage or
continuity checks even if the source dataset itself has not changed. Dataset
identity alone does not prove that the current evaluation policy was applied.

**How to apply:** Distinguish the scoring policy from the data fingerprint.
Missing or obsolete policy evidence is inconclusive, never acceptance. A complete
baseline is needed to measure a regression; absent evidence must not be treated as
successful quality measurement.
