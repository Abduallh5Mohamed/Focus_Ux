# FOCUS coordination - active implementation milestone

## Local session 2026-10-30 (Codex)
- Short-result report investigated: user's stored upload decodes to 5 frames/0.167 s; result 0.160 s. Fixed UI zero-rounding and added short-upload warning. Independent real 15 s duration smoke returned full 15 s WAV. Web tests 75 passed. User must supply intended full-length source; no media/database edits made. See LOCAL_RUN_STATUS.md.
- User-requested thumbnail repair: relative `/api` media URL/auth resolution fixed; real Chrome now decodes both JPEG faces. Crop display/decode fallback corrected. Web tests 73 passed and typecheck passed; existing services remain running. Details in LOCAL_RUN_STATUS.md.
- Final update: real GPU inference and browser upload -> last face selection -> WAV download -> refresh/playback passed on RTX 2050. UI http://127.0.0.1:5173, API http://127.0.0.1:8000 (`inference.mode=local`), left running. All new environments/caches/assets/temp on D:. AAC tail alignment regression fixed and tested. ASR unavailable; no GT/realtime/subjective-quality claims. Current evidence and commands in LOCAL_RUN_STATUS.md; earlier bullets below are historical.
- Update: user authorized official weight download; verified `model.safetensors` and config now cached in `model-assets/cache/hf/hub/models--JusperLee--Dolphin`. See LOCAL_RUN_STATUS.md. Inference remains unvalidated; full source/runtime and supporting assets are still missing.
- Current machine checkout D:/Focus/Focus_Ux: UI verified at http://127.0.0.1:5173, API at http://127.0.0.1:8000, left running.
- Inference unavailable: user confirmed original Dolphin/assets/weights are absent on this machine. No weight downloads or inference success claimed. See LOCAL_RUN_STATUS.md for installation workaround, checks and processes.

Codex: integration lead, shared contracts, task arbitration and validation. Human owner can work anywhere; coordinate with their active changes.

## Assigned ownership
- OpenCode primary GLM-5.3 Flash: product/services/worker/**, product/tests/worker/** and OPENCODE_HANDOFF.md.
- OpenCode focus-ml subagent GLM-5.3 Flash: product/packages/ml/** and product/tests/ml/**.
- OpenCode focus-review subagent DeepSeek V4.1 Flash: read-only review; no files owned.
- External DeepSeek: product/services/api/** and product/tests/api/**, pending actual connection and claim acknowledgement. Do not assume it is running.
- WorkBuddy: product/apps/web/** (including its local package manifest/lockfile) and product/tests/web/**. Frontend task authorized; external connection not yet confirmed. Up to two subagents with disjoint feature ownership. Own handoff: WORKBUDDY_HANDOFF.md.
- Shared root dependencies, schemas and integration: Codex. WorkBuddy may scaffold apps/web independently; no root workspace changes.

## Current milestone
Build the smallest import-safe ML adapter and single-concurrency worker foundation compatible with docs/02_CONTRACTS.md. Preserve legacy baseline; no GPU inference claims without execution. Keep an explicit blocker if real face targeting still needs validated model integration.

## Paths
Root: A:/Focus_Ux. Product: A:/Focus_Ux/product. Originals: A:/focus (read-only). Snapshot: legacy_snapshot (read-only).
Each writer edits only assigned paths. Shared-file changes require review. At most two OpenCode subagents and bounded delegated tasks.

## Communication
Each tool writes only its own handoff. Codex reads handoffs and routes dependencies. A chat-only DeepSeek cannot automatically read local files or send messages; the human must relay its output.


## Verified milestone status (Codex review, 2026-10-29)
- OpenCode bounded task finished and session exited successfully. ML adapter and worker delivered; Codex reran combined CPU tests: 71 passed. Real GPU inference remains unvalidated; input normalization currently requires 25 fps. No realtime implementation.
- WorkBuddy handoff received. Frontend delivered; Codex reran Vitest: 50 passed. Real API/browser integration and PWA device installation remain unverified.
- No services/api implementation or DEEPSEEK_HANDOFF.md observed during this review. API connection is the current end-to-end blocker.
- Integration decisions pending: atomic job-claim ownership, canonical bbox shape and authorized original-audio access after refresh.


## Round 2 - active assignments (supersedes earlier ownership where conflicting)
- OpenCode primary GLM: worker/integration and run_local.ps1; real GPU validation authorized through ML subagent.
- focus-ml GLM: packages/ml, tests/ml, tools/verify_gpu.py. Existing assets read-only; outputs runtime/round2.
- focus-api managed DeepSeek: services/api and tests/api incl local requirements. External DeepSeek is read-only reviewer until its prior work, if any, is reconciled. No API handoff/implementation existed when assigned.
- WorkBuddy: existing web app/browser QA and real API integration, tasks in WORKBUDDY_ROUND2_PROMPT.md. Awaiting human relay; do not claim message delivery.
- Contract decisions fixed in ROUND2_INTEGRATION_DECISIONS.md. Primary publishes ROUND2_STATUS.md with actual readiness and URLs.
- New handoffs: OPENCODE_HANDOFF_ROUND2.md, WORKBUDDY_HANDOFF_ROUND2.md, DEEPSEEK_HANDOFF_ROUND2.md. Preserve older handoffs.
