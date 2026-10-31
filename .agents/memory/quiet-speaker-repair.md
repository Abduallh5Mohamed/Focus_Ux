---
name: Quiet-speaker repair decisions
description: Recovery/strict/continuity routing and worker handshake decisions; what is still unmeasured
---
- Hybrid recovery default "all": uncertain + OTHER regions are given to the extractor; identity check + quality guards decide. Real-weights false-accept rate is unmeasured.
- Continuity replays only UNCERTAIN unconfirmed speech, never confident OTHER.
- Worker handshake: `/worker/check` returns code_version + isolate_contract; the worker refuses on mismatch. Bump ISOLATE_CONTRACT on payload/routing format changes.
- inference tests need PYTHONPATH=product:product/packages/ml; test_profiling in tests/final fails on main already.
**Why:** stale worker ZIPs and silent fallbacks were the verified failure modes.
