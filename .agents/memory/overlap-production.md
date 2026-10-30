---
name: Overlap production routing
description: state of the opt-in real overlap extractor in the audio_only engine
---
- Extractor env-gated (FOCUS_OVERLAP_EXTRACTOR), default off; strict/continuity via FOCUS_ISOLATION_MODE. Docs: docs/OVERLAP_PRODUCTION.md.
- Voiceprints from analyze have no clean_spans; reference audio is derived from the diarization.
**Why:** no GPU/torch/weights in the fork, so nothing was measured.
**How to apply:** after laptop results from overlap_minimal_infer/overlap_acceptance, record them in the doc before enabling.
