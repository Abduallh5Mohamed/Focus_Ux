# Agent 3 — browser audio / product experience

You are developer 3 of a FOUR-developer 12-hour rescue sprint. Read `coordination/RESCUE_12H_PLAN.md`, AGENTS.md and BOARD.md; reconcile prior frontend ownership with developer 4. Work in separate `rescue/web` worktree from the agreed SHA.

Exclusive ownership: `product/apps/web/**`, `product/tests/web/**`; handoff `coordination/rescue/handoff-3.md`. Do not change backend/ML/root contracts. Preserve the working upload and authenticated thumbnail fixes. Use applicable frontend/React skill guidance. Focus on functioning audio, not visual redesign.

Within 30 minutes agree the transport/signaling contract with developers 2 and 4. Build AudioWorklet capture/playback for PCM separation mode: discover actual capture sample rate, stateful resampling to16k, PCM16 LE mono320-sample frames, source sample counters, seq/generation. Output buffer is bounded and observable. Playback begins with explicit user gesture. No MediaRecorder-file-upload-play-file loop presented as low-latency audio.

In the first three hours also build a minimal remote-microphone sender/listener journey using WebRTC and developer 2's signaling: create room, copy link/QR if readily available, join, explicit microphone permission, audio playback, mute/stop/leave. Use headphones for tests. Test on two real devices with developer 4; browser simulated audio is not acceptance. Show connection mode and failures honestly, including inability to establish connectivity without TURN.

For separation UI, render engine capabilities. Audio-only selection requires independent clean enrollment, not a face click masquerading as voice identity. AV selection must reference actual verified identity and tracking status. Show mode: separating / remote_mic / buffered_experimental / degraded. Do not hide buffering delay or silently play mixture as isolation. Stop stale generation playback on target switch. Enrollment recording never uses a test reference.

After H+3 integrate only the chosen engine/mode. H+6 goal: real complete journey; H+8 feature freeze. Handle denied mic, autoplay failure, tab background interruption, server busy, disconnect, expired room, lost target, and restart. Report buffer size and browser scheduling timings, but do not label server-ready timings capture-to-ear. Developer 4 owns physical latency measurement.

Keep network endpoints correct for another phone/computer; 127.0.0.1 is not the developer PC from a phone. HTTPS is required for the deployed microphone flow. No default recording; make stop/clear behavior explicit. Run relevant frontend tests, typecheck/build and actual mobile-browser smoke. Do not imply PWA install makes network/GPU features offline.

Hourly commit and handoff: SHA, files, test commands/results, real-device evidence and blockers. Dependencies in the web manifest/lockfile belong to you; no incompatible broad upgrades during rescue. No GPU benchmark contention or edits in other owners' modules. Do not claim messages were delivered without evidence.
