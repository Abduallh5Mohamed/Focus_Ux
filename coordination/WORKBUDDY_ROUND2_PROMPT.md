# WorkBuddy - Round 2: real browser verification and API integration

Continue the existing FOCUS frontend, do not rebuild it. Codex is integration lead. The human works across the whole product. Read AGENTS.md, coordination/BOARD.md, docs/02_CONTRACTS.md, coordination/ROUND2_INTEGRATION_DECISIONS.md, your previous WORKBUDDY_HANDOFF.md and the latest ROUND2_STATUS.md if present.

Authorized ownership: product/apps/web/** and product/tests/web/** only, plus coordination/WORKBUDDY_HANDOFF_ROUND2.md. Keep your earlier handoff intact. Do not edit backend, model, worker, root manifests or shared contracts. You may use up to two subagents, each with disjoint files. You own package manifests, dependencies and shared client edits; no other writer touches them.

Current reality: 50 frontend unit tests passed under Codex, but no real browser/device or real API integration has been verified. OpenCode GLM now coordinates a real GPU adapter task and an API task delegated to managed DeepSeek. External DeepSeek should review only until BOARD assigns it a new writing task. Do not infer that backend/model are ready just because they exist.

Your immediate work:
1. Run and visually inspect the actual app in a browser at desktop, 390px and 320px widths. Capture screenshots, check console/network errors, keyboard flow, visible focus and layout overflow. Use available browser tooling; if unavailable report a specific blocker. Existing node runtime is C:/Users/abdua/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe and bundled Playwright is in the adjacent node_modules. Do not claim device or browser checks from jsdom.
2. Review and fix protected-media fetching. Reject API-provided absolute media URLs outside the trusted API origin before attaching Authorization; do not leak tokens to arbitrary origins. Confirm uploaded video cleanup, aborts, retries, audio exclusivity and object URL revocation.
3. Adopt the canonical bbox {x,y,width,height}, frame_size {width,height}, and approved GET /videos/{id}/original protected media endpoint from ROUND2_INTEGRATION_DECISIONS.md. Preserve original/isolated comparison after refresh by fetching the original when the in-memory File is gone. Avoid unnecessary duplicate full-file downloads. Keep transcript optional and do not discard ready audio when ASR fails.
4. Correct service-worker cache scope: only immutable/public app-shell assets; never uploaded media, protected thumbnails, API responses or token-dependent content. Prevent stale app-shell caching from hiding code changes. Verify offline shell messaging without suggesting offline AI.
5. When the API owner publishes a base URL in ROUND2_STATUS.md, connect with mock mode OFF. Exercise upload of an approved local fixture, real faces and selection, queued job, result audio, transcript-unavailable fallback, comparison after refresh, download, delete and two-session ownership checks. Do not fake a successful end-to-end run if ML remains blocked. Before the backend is ready, test browser interaction against explicitly labeled mocks and mark it as UI-only.
6. If no real API is ready, finish browser QA, commit no external push, and write the exact remaining integration steps rather than waiting indefinitely or inventing endpoints.

No realtime UI yet: upload is the integration baseline for live capture. Do not redesign the product or add health claims.

Acceptance: typecheck, production build and relevant unit tests pass; browser screenshots and observed behavior documented; mock and real-server results separated; no token/traceback/private cache leakage. Deliver changed files, commands, URLs/ports, actual screenshots, completed checks, blockers, and next steps to WORKBUDDY_HANDOFF_ROUND2.md. Report your task claims there; do not edit BOARD.md.

Start immediately within your ownership. Read coordination updates before each new task. Do not overwrite the human's changes.
