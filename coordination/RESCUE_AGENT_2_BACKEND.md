# Agent 2 — live backend / worker / signaling

You are developer 2 of a FOUR-developer 12-hour rescue sprint. Read `coordination/RESCUE_12H_PLAN.md`, AGENTS.md and BOARD.md. Reconcile old ownership through developer 4 before writing. Work only in your separate `rescue/backend` worktree from the agreed SHA.

Exclusive ownership: `product/services/api/**`, `product/services/worker/**`, `product/tests/api/**`, `product/tests/worker/**`, `product/tools/windows_worker.py`. Own handoff: `coordination/rescue/handoff-2.md`. Local manifests belong to their module owner. No frontend/ML/root/shared-schema edits; request them through owners. Preserve working upload/auth behavior. No legacy environment changes or paid services.

Within 30 minutes agree the versioned session/audio/adapter contract with developers 1, 3 and 4. Developer 4 writes it. Build transport independently of the winning engine. PCM16 LE mono16k frames, actual source sample ranges, seq and generation; validate and limit message sizes/rates. Use authenticated/scoped sessions, one concurrent GPU session, bounded queues measured in milliseconds, explicit overload and disconnect/reset behavior. Never accumulate seconds of hidden backlog or emit stale-target audio. Do not drop arbitrary stateful-model PCM and continue silently.

First deliver a minimal real WebRTC signaling flow for the close-microphone backup in parallel with the PCM transport skeleton: expiring room, sender/listener roles, join/leave and cleanup. WebRTC carries media, backend handles signaling. Agree browser messages with developer 3. TURN availability must be explicit; LAN success does not prove connectivity across networks. Do not build a full conferencing service.

By H+3 deliver signaling, session lifecycle and adapter integration point. Test doubles may exist in tests, never as production success. For separation, keep model loaded in a persistent worker and maintain per-session state. Remove per-chunk container/FFmpeg round trips from the new audio critical path; preserve upload paths. Video path only if the chosen engine needs it, timestamped against the audio clock. Do not redesign tracking/model internals owned by developer 1.

H+3–6 wire the selected real engine. If model gate fails, support remote_mic as an explicitly different mode. Audio failure must be visible; never return the original mixture under a separated label. ASR must not block live audio. By H+6 support real device end-to-end tests with developer 4.

H+6–8 support HTTPS/reverse proxy configuration, health showing actual worker connection and graceful busy/errors. Coordinate deploy with developer 4; do not make independent infrastructure/push changes. Test token isolation, stale generations, malformed data, overload, disconnect and cleanup. Report cold/warm server timing separately from capture-to-ear latency. Freeze features at H+8, fix blockers only.

Hourly commit/handoff: SHA, changed files, protocol examples, executed tests, actual outputs and blockers. Reserve GPU through developer 1/4; do not launch concurrent benchmarks. Never claim another agent received a message without delivery evidence.
