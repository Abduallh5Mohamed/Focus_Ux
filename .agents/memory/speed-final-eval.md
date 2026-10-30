---
name: Speed tuning and final evaluation policy
description: Measurement policy for speed/VRAM claims and the final evaluation
---
No speed, VRAM or supported-length claim without a run on the RTX 3050 demo laptop with real VRAM readings; the default 180 s limit stays otherwise.

**Why:** the dev workspace has no GPU/weights/Egyptian data; unmeasured claims were rejected in review.
**How to apply:** report "not measured" unless the report says measured_on_target_laptop. A measured limit file must also be laptop-verified. Raising the length also needs upload, worker media and worker output size limits raised together. Speed gating uses the strict dropout policy (overlap-free clips); the final report only reports dropout. Listening raters must get a target reference per item.
- Do not run scripts with cwd inside `focus_ml/voice` (its `types.py` shadows stdlib).
- Supported length: count every attempted clip (failed ones too) and use end-to-end wall time, never summed stage times.
