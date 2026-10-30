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

Interrupted startup cleanup is best-effort in the browser, not a guarantee after a tab or process disappears.

**Why:** aborting a Create request cannot establish that the server did not create a session, and a closed page may never receive the response needed to identify its session. A keepalive cleanup request helps only once that identity is known.

**How to apply:** preserve the original owner for delayed cleanup, never let an abandoned startup alter its replacement, and treat server-side idle recovery as a separate protection rather than claiming browser teardown covers hard exits.

Failure to save playback measurements must not block access to a finished recording.

**Why:** measurement completeness and final-result availability are separate requirements; retrying failed telemetry forever strands an otherwise usable result.

**How to apply:** bound telemetry saving, show a clear warning if it fails, and omit unavailable metrics rather than fetching stale measurements or inventing successful playback.

Live idle recovery and delayed chunk cleanup must execute between tasks in the owning dispatcher, not on independent timers.

**Why:** a timer can delete media during inference or access a repository after shutdown; a shutdown timeout does not cancel inference or transfer ownership.

**How to apply:** keep recovery serialized with inference and scoped to the original live session. Retry failed cleanup while ownership is held, and preserve completed full recordings and their audio.
