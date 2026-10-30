---
name: Overlap extraction candidates
description: durable constraints for the overlap-extraction stage and its bake-off
---
- REAL-TSE checkpoints exist only on Google Drive (HF has just a CoreML port); its requirements pin numpy 1.22 which setup must not install.
- Blind separators (MossFormer2, SepFormer, PixIT) are always labelled "blind separation then voiceprint selection", never voice-conditioned.
- Adapters have never run on real weights; any result must be labelled by data language and device. No default was chosen by measurement; gated baseline stays default.
**Why:** the fork has no GPU/torch/weights/Egyptian audio; user wants measured, honest claims.
**How to apply:** after a laptop bake-off, re-read report.json decision before changing defaults.
