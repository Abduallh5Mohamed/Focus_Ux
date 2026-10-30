---
name: Audio-only engine in the app
description: Durable decisions for the enrollment-based default engine
---
- Audio-only worker tasks transfer audio only; video goes to the worker only for detection and enrollment-time visibility.
- Face visibility is a sparse detector-continuity sampler with an honest talk-time fallback; the speaking-face score was never measured and is not used.
- Default engine is audio_only; lip engines keep the 15 s limit.
**Why:** "no frames, face tracks or lip data after enrollment" plus the Dolphin tracker's 15 s / all-frames-in-memory limit.
**How to apply:** validators on the worker JSON protocol must be tested against output of the real engine, not hand-made fakes (nested voiceprint source data was once rejected).
