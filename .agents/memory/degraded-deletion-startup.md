---
name: Degraded deletion startup
description: Availability and privacy tradeoff when persisted deletions cannot complete.
---

Allow degraded startup for individual filesystem deletion failures, while keeping the normal exclusive dispatcher lock. Keep failed deletion records and paths private and available for retry; continue unrelated deletions and queued work. Unexpected repository or programming failures still abort startup.

**Why:** A persistent permission or disk error affecting one deleted upload must not disable processing for every other user. Degraded availability is safe only if deletion immediately revokes access and failure remains observable rather than being treated as completed removal.

**How to apply:** Preserve per-video failure isolation and error logs when changing startup recovery. Retry retained deletions on later startup or repeated deletion requests; do not introduce a tight automatic retry loop or weaken lock ownership.
