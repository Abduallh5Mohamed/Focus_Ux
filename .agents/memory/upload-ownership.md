---
name: Upload ownership locks
description: Why upload protection uses OS-owned sidecar leases and a stable cleanup gate.
---

Keep upload ownership independent of modification time and hold it through validation and promotion, not just writing bytes. Use OS-owned leases rather than heartbeat freshness or PID checks.

**Why:** A live upload may stop writing for longer than the cleanup threshold. Process exit must make abandoned files recoverable without an expiry delay. Sidecars also avoid holding the media file open across moves/deletion on Windows.

**How to apply:** Serialize lease creation and removal with a stable gate that is never unlinked. Otherwise concurrent cleaners can lock different file identities and invalidate exclusion. Apply the same protocol to any future upload writer or cleanup entry point sharing this storage root; all instances need the updated protocol.
