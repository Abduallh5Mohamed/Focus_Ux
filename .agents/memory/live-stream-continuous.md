---
name: Continuous live stream decisions
description: transport choice and single-worker release rule for the sliding-window live path
---
Transport is HTTP batch POSTs plus long-polls, not WebSocket.
**Why:** no websocket library installed; the Windows worker is outbound-only with isolated deps.
**How to apply:** keep the wire format stdlib-only so it ships in the worker kit.

A stream session occupies the single worker; an abandoned browser must never strand it.
**Why:** hard tab closes skip the stop request, so idle expiry has to run on worker polls too.
**How to apply:** any new worker-facing route must go through expiry.

The gate never passes without browser playback latency and an SI-SDRi delta; unmeasured stays unmeasured.
