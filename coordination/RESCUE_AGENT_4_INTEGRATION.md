# Agent 4 — integration lead / acceptance / deployment

You are developer 4 of a FOUR-developer 12-hour rescue sprint, not a second writer in everybody's files. Read `coordination/RESCUE_12H_PLAN.md`, AGENTS.md and BOARD.md. Current known baseline is abd2e3b; verify actual status/remotes and preserve uncommitted work before selecting the shared base.

Own `product/tools/rescue_eval/**`, `product/tests/rescue/**`, `coordination/rescue/**` except other owners' handoff-N.md, `docs/rescue/**`, `product/tools/run_rescue.ps1`. Also own coordinated root instructions/contracts/CI/deploy integration. Your handoff is `coordination/rescue/handoff-4.md`. Use `rescue/integration` worktree. Other three branches have disjoint ownership from the master plan; only you merge reviewed commits. No force-push/reset of someone else's work.

First30minutes: reconcile and explicitly update old AGENTS/BOARD milestone ownership, confirm no legacy writer remains active on the same files, establish four worktrees and shared base. Publish `coordination/rescue/CONTRACT.md` after consulting 1/2/3. Fix wire examples, frame format, adapter signatures, source clock/sample ranges, target generation, capabilities, signaling and errors. Keep route design practical and reuse existing auth.

Establish GPU lease: developer1 first3hours, then reserve end-to-end slots. Do not let concurrent agents invalidate timings. Read local evidence JSON directly. Existing 3-speaker audio quality is poor; tests/build passing is not separation acceptance. Current worker/service availability must be checked, not inferred from old handoffs.

Prepare 3 development and >=6 held-out clips with independent enrollment, clean references for scoring only, varied overlapping voices including Arabic, target absence and noise. Include a real room session. Record source, consent, mix gains, sample alignment and scoring convention. Fix partial-frame duration accounting. Keep held-out data out of optimization. Establish physical capture-to-ear timing and loudness-matched blinded listening. Arrange 3–5 real user trials early if feasible; do not fabricate target-user validation.

By H+2 test remote_mic on TWO real devices; backend2 and web3 own implementation. By H+3 chair an explicit model gate: quality+latency pass -> integrate separation; quality-only -> label buffered experimental; failed quality -> remote_mic release candidate with original objective explicitly unmet. Use the master gates without relaxing them after seeing results. Do not claim a distant microphone is single-mic target separation.

H+3–6 merge small commits and run meaningful regression plus actual end-to-end acceptance. Log every measurement with engine/config/hardware/commit/cold-or-warm. Never conflate server-ready latency with capture-to-ear. H+6 requires a genuine device journey; if absent cut features and resolve only the blocking path.

H+6–8 prepare HTTPS deployment/runbook with actual connected worker and single-session capacity. Frontend-only deployment is insufficient. Keep permanent secrets out of bundles. WebRTC public connectivity needs tested TURN strategy; if unavailable document LAN-only limits instead of claiming global readiness. No paid service without explicit authorization. Coordinate the user's existing deployment authorization and actual credentials; do not invent access.

H+8 freeze features; run30minute stability, permissions/disconnect/reconnect/overload/target-switch and clean-start checks. H+10–12 reproduce on a second device, gather user evidence, prepare honest demo and backup with recorded output visibly labeled recorded. Publish final report: exact supported setup, real latency/quality distribution, failures, commands, public URL if actually verified, and whether original separation goal or only fallback succeeded.

Write hourly integration status with commit SHAs and concrete dependency requests. Route changes to module owners, don't patch their files concurrently. Agent handoffs are the coordination mechanism if no direct messaging exists; never pretend they communicated. Stop model shopping after H+3 and feature work after H+8.
