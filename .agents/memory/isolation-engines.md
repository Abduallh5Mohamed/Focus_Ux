---
name: Isolation engines
description: Design constraints for selectable Dolphin / AV-MossFormer2 / separate-select engines
---
- ClearerVoice code paths were never run on real weights/GPU in the workspace; calls follow its README. Verify with the compare tool on the user's machine.
- Extra packages go to a separate folder appended LAST to sys.path, installing only what a pip dry-run says is missing; setup aborts if torch/numpy would change.
- ExtractionResult fields are pinned by a contract test; engine info lives in the EngineResult subclass.
**Why:** the user's original Dolphin environment/caches must stay untouched.
**How to apply:** any new engine goes through isolation_engines.build_engine and reports its name via the audio upload header.
