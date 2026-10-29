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
