---
name: Windows local handoff constraints
description: Safety boundary for testing a release on the user's existing Windows GPU installation.
---
Use a separate trial checkout and isolated API dependencies; reuse the original ML
Python only to execute the GPU worker. Do not install into the legacy environment,
move its weights, or repair its caches as part of a handoff.

**Why:** The handoff exists to enable user-run GPU/camera measurements without
changing the previously working installation. Synthetic regression success does
not establish Windows startup compatibility or pass the real-device gate.

**How to apply:** Keep local trial credentials and runtime data separate from the
Replit-connected worker. Keep live mode opt-in. Report the actual pushed revision
and any push/authentication blocker, and direct real-device results to the existing
measurement work rather than declaring acceptance.
