---
name: Near-live mode gate and opt-in
description: Decision and constraints for the experimental near-live mode.
---
The near-live mode stays internal/experimental and off by default until real browser + GPU numbers exist in the gate report doc.

**Why:** Replit has no GPU/camera, so latency and quality were never measured; the gate must not pass on invented numbers.

**How to apply:** keep server (FOCUS_LIVE_ENABLED) and web (VITE_LIVE_ENABLED) opt-in; startup cleanup of live leftovers runs only in the process that owns the dispatcher lock and never deletes finished recordings; camera tracks must be released on stop, error, unmount, and when an async start resolves after unmount.
