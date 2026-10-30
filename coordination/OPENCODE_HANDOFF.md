# OPENCODE handoff — bounded ML-adapter + worker milestone

Date: 2026-10-29. Author: OpenCode primary (GLM-5.3 Flash). Reviewed by focus-review (DeepSeek V4.1 Flash, read-only session).

## What exists now (files changed/created, ownership respected)

- `product/packages/ml/focus_ml/` — `__init__.py`, `types.py`, `identity.py`, `timing.py`, `tracking.py`, `errors.py`, `config.py`, `adapter.py`. Written by focus-ml subagent (GLM, task session `ses_e7830df72ffeceu1mv4zft7Koo`), then same session applied the review fixes.
- `product/tests/ml/` — `conftest.py`, `test_import_safety.py`, `test_identity.py`, `test_timing.py`, `test_tracking.py`, `test_adapter_honest.py`, `test_types_contract.py` (focus-ml).
- `product/services/worker/` — `__init__.py`, `models.py`, `errors.py`, `interfaces.py`, `worker.py`. Written by OpenCode primary.
- `product/tests/worker/` — `conftest.py`, `fakes.py`, `test_worker_states.py` (OpenCode primary; fakes are explicit test doubles only).
- `coordination/OPENCODE_HANDOFF.md` (this file).
- Untouched: `product/apps/web/**`, `product/tests/web/**` (pre-existing from parallel work), all `services/api`/`tests/api` (DeepSeek external, no assumed connection), `legacy *`, shared manifests, git (no repo at this root — nothing was committed).

## Commands and observed results

Test interpreter used: `C:\Users\abdua\AppData\Local\Programs\Python\Python313\python.exe -m pytest ...` (pytest 9.0.1 present; repo has no shared test manifest to edit). The legacy `A:\focus\.venv` (Python 3.12.15) lacks pytest and was not used for tests; no packages were installed.

- `python -m pytest product/tests/ml -q` → **47 passed**, exit 0.
- `python -m pytest product/tests/worker -q` → **24 passed**, exit 0.
- Combined run after all fixes → **71 passed**, exit 0 (last run after final test-file edit).

## What the code delivers

ML adapter (`focus_ml`, contract shim per docs/02 "Python adapter"):
- Import-safe package: importing it does not import torch/cv2, does not chdir, does not edit sys.path (verified in subprocess tests).
- Contract functions `load_models / detect_candidates / extract_target` behind `LegacyDolphinAdapter`; `extract_target` refuses without a loaded backend and never writes any wav on failure paths (zero-files guarantee is tested).
- Selection identity: `make_face_id` is deterministic sha256 over video_id + timestamp + bbox + frame_size; target is matched by identity, not by legacy `db[:n_spk]` order (`resolve_target_speaker`, `match_detections` port of legacy IoU tracking incl. veto/hold-last).
- fps/audio alignment: `audio_window_to_roi` reproduces legacy `_separate` index math `int(start/sr*25)` / `min(int(end/sr*25), len(roi))`; duration from actual read sample rate; `normalize_timestamps_ms` monotonic.
- Honesty features from review fixes: user-safe messages only (raw paths/stderr live in `MlError.detail`, excluded from `as_dict()` payload); `downscale` rejected rather than silently mis-mapping boxes; `_load_backend` restores cwd and sys.path on every exit; ffmpeg missing/corrupt-media mapped to contract codes; config `detect_every`/`landmark_every` wired into detection cadence; cached detections fed to the tracker each frame (legacy else-branch parity); bbox clipping warnings.

Worker (`services/worker.SingleWorker`, stdlib only, no torch/focus_ml/sqlite imports):
- Single-concurrency job engine: validating → preparing → tracking (+ adapter-emitted to separating) → transcribing → ready; persistence via injected `JobRepository.save` after each transition (stage+status history verified by test).
- Claim ownership documented: worker performs queued→processing itself; dispatchers hand over QUEUED job ids only (interfaces.py module docstring).
- Independent audio/transcript state: audio ready survives transcript failure; no provider → transcript failed with user-visible message while job completes (contract rule); final `status=completed` gated on COMPLETED in `snapshot()`; server paths never exposed in snapshots.
- Failure transitions: adapter contract codes propagate (`TARGET_LOST`, `FACE_NOT_FOUND`, `INVALID_MEDIA`, `LIMIT_EXCEEDED`, …); unexpected exceptions become `PROCESSING_FAILED retryable=false` with generic message (no internal paths leaked, tested).
- No fake success: after extraction the worker verifies the wav artifact exists, is non-empty and inside the job directory, else FAILED (tested incl. outside-job_dir case).
- Cancellation between stages (cancel flag checked per stage boundary; `request_cancel` effective for QUEUED only); cancellation after audio-ready → CANCELLED with audio READY preserved; a failing stage listener never corrupts the job (isolated, counted).
- Restart recovery: `recover_interrupted()` marks abandoned PROCESSING jobs FAILED, retryable, without discarding READY audio.
- Requeue/retry: `_claim` resets run state (error, statuses, wav, segments, warnings), so a FAILED→QUEUED retry cannot end COMPLETED with stale error (tested).
- Transcript segment validation: coercing dicts, `0 <= start <= end`, invalid → transcript failed, audio unaffected.

## Review process

focus-review (DeepSeek) produced B1, M1–M9, m1–m17. Required findings were all fixed (B1 honesty claims, M1 messages, M2 video_id identity, M3 downscale rejection, M4 cwd restore, M5 artifact verification, M6 retry-state reset, M8/M9 ML test correctness). m1, m2, m4–m6, m8 (retryable vocabulary aligned: `PROCESSING_FAILED` retryable=True in both packages), m9–m17 were fixed as listed. Judgment calls: m7 duplicate-`tracking` emission is now asserted exactly rather than deduped; `queue_position` is not assigned beyond claim (0) — queueing/front-of-line is API territory.

## Blockers / open items (explicit, nothing hidden)

1. **Real engine never executed — no GPU validation happened in this milestone** (no GPU run, no downloads, per brief). The whole extraction pipeline path in `adapter.py` is documented as UNVALIDATED CPU-side pseudocode of the CUDA legacy pipeline; docstrings no longer overclaim. Before any real use: run on GPU and diff numerically against the GT baseline (legacy `focus_runner` behavior), including detection/landmarks/Dolphin separation and the legacy channel order (RGB crop → landmarks, BGR stored crops, `get_preprocessing_pipelines()["val"]` before windowing). Note: the environment now has torch/cv2 importable, but `face_alignment`/`soundfile` were absent at review time; `available()` probes the full stack.
2. **`_load_backend` still chdirs during the call body** (legacy behavior, restored after); unknown behavior across concurrent threads — keep single-writer usage until reworked.
3. **fps resampling not implemented** (docs/01 #3): uploads must already be 25fps like GT fixtures; every extraction carries this warning.
4. **`face_id` basename fallback is not contract-conformant**: the plumbing accepts a `video_id` parameter; the API must pass the real UUID video_id when integrating, otherwise a warning is emitted (flagged per review M2).
5. **Downscale detection deferred** (would need validated geometry change, docs/01 #5): rejected at runtime.
6. **No transcript provider exists yet** — jobs complete with transcript_status failed until an ASR boundary is integrated (must be provided by whoever owns it; interface is `TranscriptProvider`).
7. **No sqlite repository / API yet** — `JobRepository`, `WorkerLayout` are injection points; API must hand QUEUED ids (claim contract above). `GPU_BUSY` exists in the vocabulary but nothing raises it (single-writer assumption).
8. **Integration risk flagged by review (M7)**: if the future API layer claims jobs atomically (docs/02 says Dev 2 owns atomic claim), it must coordinate with the worker's own claim; as built, `process()` no-ops on non-QUEUED jobs. Needs one sentence of decision from Codex/DeepSeek before API integration.

## Not done / out of scope

No git operations, no scripts run inside `product/services/api` or `tests/api` (external DeepSeek owns these), no edits outside my owned paths except `coordination/OPENCODE_HANDOFF.md`. No deployment, push, GPU benchmarks, or model training.

## Replit inference integration handoff

This later section describes the imported Replit integration; the historical
milestone above is preserved, not a statement of current API availability.

- Added offline-only `focus_ml.runtime.LocalEngine`, canonical media/provider
  integration in `services/api/focus_api/inference.py`, and outbound single-task
  worker bridge in `remote_inference.py`. Factory selects unavailable/local/remote
  mode; all existing browser ownership/session checks remain in place.
- Added allowlisted `/worker-kit.zip`, Windows startup/key/connection-check
  scripts under `product/tools`, and `docs/WINDOWS_INFERENCE.md`. No weights,
  fake inference providers, external services, packages, training or publishing.
- Worker credentials are supplied through Replit Secrets and hidden/local setup;
  no credential values are in this handoff, source bundle or URLs.
- Canonical ffmpeg output is 25 fps; persisted geometry and actual API video ID
  tie selection to extraction. Remote WAVs are bounded, PCM16/16k/mono, with
  actual sample duration checked against canonical media and zero offset.
- Executed after syncing the parallel changes: inference protocol suite
  (25 passed), ML suite (65 passed), worker suite (24 passed), API suite
  (160 passed, one skipped). Suites were run in separate Python processes.
  Protocol tests include real ffmpeg normalization but synthetic model responses.
  These are NOT proof of real GPU isolation. Workflow, ZIP download and landing
  page were verified in the task environment.
- Operator screenshot confirms real model initialization on Windows. Actual
  remote polling and upload-to-isolated-audio execution are still unverified.
  The main Networking URL differs from the isolated task preview; main health
  succeeded but worker handshake returned 404 because the changes were not merged.
  The operator then explicitly disabled Private preview for a temporary test;
  a subsequent Windows check to the task host still redirected. Do not assume
  that changing main preview settings can expose this isolated task environment.
- After merge: restart main workflow, check remote mode and worker-secret
  presence without reading its value, then run Check-Connection.cmd against the
  main Networking URL. Reuse the saved Windows key. Only then run the GPU worker
  and validate a real multi-speaker clip, non-first selected face, alignment,
  playable WAV and cross-session media denial. No production publication needed.
- Operator allowed only a temporary public-preview test. Do not treat that as
  permission for ongoing public access; restore private preview when testing
  ends if it was temporarily changed. Private main previews need separately
  authorized platform access; do not publish this task fork as a workaround.

## Local acceptance preparation

- Added `product/tools/trial_readiness.py` and focused CPU tests in
  `product/tests/worker/test_trial_readiness.py`. It checks native Windows,
  isolated trial Python, tool versions, existing assets and a CUDA probe using
  the original Python without installing anything. Optional upload tests use
  only the trial interpreter. Raw subprocess errors and environment contents
  are not included in the JSON report.
- Tightened evaluation coverage in `product/packages/eval/focus_eval/`:
  all READY manifest targets are retained, an incomplete baseline blocks
  adoption, and missing/truncated candidate audio rejects with a complete
  baseline. Continuity checks use 20 ms frames, including partial final frames,
  and allow no detected reference-active silent frames.
- Older evaluation reports must be regenerated under the current policy.
  Added regressions for jointly missing targets, missing rows, short silent
  gaps, trailing partial frames and obsolete reports.
- Updated `docs/LOCAL_WINDOWS_TRIAL.md` with the readiness command and the
  distinction between the current 3-second gate and the planned 1.5-second goal.
- Observed: evaluation suite 46 passed; worker suite 30 passed in separate
  processes. Executing the readiness CLI here exits 2 as intended: Windows,
  original weights, CUDA and continuous-stream source are unavailable.
- No native Windows test, real inference benchmark, camera acceptance, weight
  download, original-environment modification, push or public deployment.
  Continuous-stream source remains absent from this integrated checkout;
  completed work in a separate task environment must be merged before testing it.
## Codex local-machine update — 2026-10-30

User authorized downloading the official model and preparing/running this checkout, then required all new downloads/caches/runtime files on D:. Real local inference and frontend integration now passed on RTX 2050. Detailed changed files, commands, source/weight hashes, results, earlier failures, remaining blockers and stop/restart instructions are in [LOCAL_RUN_STATUS.md](LOCAL_RUN_STATUS.md).

Changes: ML adapter AAC end-padding alignment; four regression tests; D:-local path configuration, launcher and real GPU verification tools. New code is in `product/packages/ml/focus_ml/adapter.py`, `product/tests/ml/test_audio_codec_alignment.py`, `product/tools/local_paths.ps1`, `product/tools/run_local.ps1`, `product/tools/verify_gpu.py`. API/frontend source unchanged. CPU core tests: 95 passed/1 dependency-skipped module; four new regressions separately passed. Real GPU: two targets, different valid 6000 ms WAVs. Real API and Chrome: upload, last face selection, protected audio/original, actual WAV download, refresh and native playback passed. ASR unavailable; no GT quality/realtime acceptance claimed. Earlier API killed-upload cleanup failure remains documented, not fixed here.

Services left running on loopback: UI :5173, API :8000 in local inference mode. All new assets/environments/CUDA libraries/cache/temp are on D:. Session-created C: uv/npm cache files were moved to D: after deletion commands were automatically rejected; final audit found zero session-created files remaining in those C: caches. Original shared caches/global packages were preserved. No training, deployment or push, and no external-agent message delivery claimed.
