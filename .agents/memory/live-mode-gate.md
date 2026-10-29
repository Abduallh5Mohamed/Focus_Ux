---
name: Near-live mode gate and opt-in
description: Decision and constraints for the experimental near-live mode.
---
The near-live mode stays internal/experimental and off by default until real browser + GPU numbers exist in the gate report doc.

**Why:** Replit has no GPU/camera, so latency and quality were never measured; the gate must not pass on invented numbers.

**How to apply:** keep server (FOCUS_LIVE_ENABLED) and web (VITE_LIVE_ENABLED) opt-in; startup cleanup of live leftovers runs only in the process that owns the dispatcher lock and never deletes finished recordings; camera tracks must be released on stop, error, unmount, and when an async start resolves after unmount.

Synthetic browser/network regression results do not satisfy the real-device gate, even when they use native Web Audio and rendered samples.

**Why:** they establish scheduling behavior, not inference quality or capture-to-play latency on the user's GPU and camera.

**How to apply:** keep synthetic playback checks separate from GPU acceptance evidence; never enable live mode globally based on browser-test success alone.

Do not automatically retry a live finalization request after a timeout or cancellation.

**Why:** cancelling the browser's response does not undo server-side finalization; a lost reply leaves the outcome uncertain rather than proving the operation failed.

**How to apply:** bound the request, release capture resources, and explain the uncertain outcome. Any future recovery should first inspect session status instead of blindly sending another finalization request.
