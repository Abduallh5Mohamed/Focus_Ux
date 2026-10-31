---
name: Real-weights facts about the TSE checkpoints
description: durable constraints from running WeSep, USEF-TSE and SpEx+ for real
---
- All three checkpoints are SI-SDR trained: output level and polarity are arbitrary, so any use needs a mixture-based rescale first.
- 8 kHz outputs are often rejected by the ECAPA voiceprint check inside the hybrid, so hybrid scores understate their raw separation; report both.
- Pooled leakage ratio is dominated by low-retention mixes; leakage share is steadier.
- USEF checkpoint is an unsafe pickle: load only after a SHA-256 match against the reviewed file.
- Long runs: write outputs under the workspace; the sandbox can restart and lose /tmp.
**Why:** each changed how results must be read or run safely. **How to apply:** before touching adapters or interpreting experiment numbers.
