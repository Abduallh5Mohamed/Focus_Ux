---
name: Quiet-speaker repair decisions
description: Durable decisions and caveats for recovery routing and the worker handshake
---
- Recovery defaults to all uncertain + OTHER regions; identity check + quality guards decide. Real-weights false-accept rate is unmeasured.
- Pieces too short to verify on their own are muted; never authorised by the surrounding window's identity.
- Continuity replays only UNCERTAIN unconfirmed speech, never confident OTHER.
- Claimed-task silence deadline is off by default: the worker sends no heartbeat while loading/inferring, so a short deadline would reject healthy slow jobs. Enable only with a heartbeat.
- Bump ISOLATE_CONTRACT when the isolate payload or routing format changes.
**Why:** stale worker copies and silent fallbacks were the verified failures.
