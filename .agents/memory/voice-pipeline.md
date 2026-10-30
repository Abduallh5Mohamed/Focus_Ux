---
name: Voice pipeline POC quirks
description: Durable guidance for the audio-only voice pipeline (focus_ml/voice)
---
- SpeechBrain ECAPA loads from a local folder only with `overrides={"pretrained_path": <dir>}` and a Path source; otherwise it tries the Hub.
- Replit packages/weights live in runtime/voice (ignored), installed with `pip --target`; long jobs need ShellExec run_in_background.
- Measured numbers must be labelled by data (non-Egyptian LibriSpeech, CPU) and never presented as Egyptian or GPU results.
- Windows .cmd launchers sit in product/tools; compute the repo root from %~dp0 (two levels up).
**Why:** user wants real numbers only; targets labelled as targets.
**How to apply:** check docs/VOICE_PIPELINE_LOG.md for what is still unmeasured.
