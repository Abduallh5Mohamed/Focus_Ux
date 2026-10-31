---
name: Overlap extraction candidates
description: durable constraints for the overlap-extraction stage and its bake-off
---
- REAL-TSE checkpoints exist only on Google Drive (HF has just a CoreML port); its requirements pin numpy 1.22 which setup must not install.
- Blind separators (MossFormer2, SepFormer, PixIT) are always labelled "blind separation then voiceprint selection", never voice-conditioned.
- The three voice-conditioned adapters have run on real weights (CPU, English LibriSpeech only); the blind ones have not. Label every result by data language and device. Gated baseline stays default.
- WeSep helps in 2-speaker overlap but has unclear weights licence; USEF is non-commercial; SpEx+ (Apache) did not help. No model is approved for deployment.
**Why:** user wants measured, honest claims; no Egyptian audio or GPU laptop reachable from the workspace.
**How to apply:** after a laptop bake-off, re-read report.json decision before changing defaults.
