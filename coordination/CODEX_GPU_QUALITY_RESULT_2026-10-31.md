# FOCUS GPU quality verification — 2026-10-31

Implementation supervised across OpenCode GLM and DeepSeek; changes remain local and uncommitted. Existing work preserved. No push/deployment, no new model weights, no writes/installations in A:\focus.

## Runtime
- Worktree: C:\Users\abdua\WorkBuddy\Worktrees\Focus_Ux\main-0aec6d07
- Base HEAD: 183c7d42a7e52e006d258501df38d8955db0f2e9 (dirty worktree; HEAD does not contain these changes).
- RTX 3060 Laptop 6GB, driver 617.42; torch 2.8.0+cu126, CUDA runtime 12.6.
- Isolated separator env: A:\Focus_runtime\venvs\cv-gpu312-reuse. GPU package files copied read-only from existing install; ClearVoice dependencies installed only in this separate environment. No system CUDA changes.
- Resident separator process keeps loaded model, serializes requests and refuses GPU failure instead of CPU fallback. Offline inference.
- Local launcher: A:\FocusLocalTrialReports\Start-GpuLocalApi.ps1

## Measured results
Controlled six-second mixture of two concurrent public-source recordings; independent enrollment snippet. Clean reference used only for evaluation, not supplied to extraction. These results do not establish performance on three speakers or natural long conversations.
- CPU separator inference: 51.16 seconds.
- GPU resident warm separation: 1.663 seconds (RTF 0.277), excludes diarization, enrollment and export.
- Latest complete API trial after model warmup: analysis 2.128 seconds; isolation requests 2.556 and 2.748 seconds. Earlier cold analysis 11.977 seconds and cold isolation 11.278 seconds. Not a live-streaming implementation or measured p95 latency.
- Target mixture SI-SDR: -13.8616 dB; API isolated WAV: 10.1975 dB; improvement 24.0591 dB.
- Export decoded SI-SDR: 10.1932 dB, preserving WAV result approximately. No default residual mixture added.
- Evidence: A:\FocusLocalTrialReports\quality_audit\api_gpu_trial.json and api_final_quality.json.

## Honest limitations / failure corrected
Earlier conservative per-window verification returned all-zero WAV while API marked success. Invalid silent quality scores were corrected to null; evidence retained in api_silent_failure_quality.json. Verified mode now refuses silent output. Explicit local runtime FOCUS_SEPARATION_OUTPUT=stem retains the full globally enrollment-matched separated source, avoiding destructive timing gates. Global identity confidence is checked, but local source switches are NOT verified; this warning reaches the API job result. Default library mode stays verified. Two-source MossFormer2 can leak/switch speakers; no promise of three-source separation. No subjective listening claim.

Face selection still uses audio-only placeholder when face detector absent. Live transport, device/cloud latency and p95 <150ms are not validated. Short enrollment reports 4 seconds clean and recommends at least 8 seconds. Pyannote torchcodec warning remains; in-memory audio path executed successfully.

## Validation
- Latest voice + ML: 203 passed, 3 skipped.
- API suite rerun with ffmpeg/ffprobe directory prepended to process PATH (final count recorded separately after completion).
- First combined attempt omitted ffmpeg from test process PATH and had FileNotFoundError: [WinError 2] The system cannot find the file specified in test_export.py fixture. This is not silently counted as passing.
- DeepSeek web run: 105 passed, 11 files; typecheck passed.
- git diff --check passed (existing CRLF warning only).

## Listen / inspect
- Input: A:\FocusLocalTrialReports\quality_audit\two_overlap_6s.mp4
- Output WAV: A:\FocusLocalTrialReports\quality_audit\api_warm_isolated.wav
- Export: A:\FocusLocalTrialReports\quality_audit\api_warm_export.mp4

Next validation: blind listening, target preservation/leakage on balanced Egyptian Arabic speakers, independent enrollment, longer clips and three-speaker stress test. Benchmark streaming-capable target extraction separately before making real-time claims.

Additional validation: inference + worker suites: 96 passed (9.87 seconds). Local health through web proxy: status=ok, dispatcher=true, inference.mode=local. This runtime uses local inference rather than a remote worker connection.

Final API rerun with correct process PATH: 248 passed, 1 skipped in 139.45 seconds. Aggregate current Python checks: 547 passed, 4 skipped (voice+ML 203/3, API 248/1, inference+worker 96/0). Latest warm API isolation 2.748 seconds; globally matched-source/local-unverified warning confirmed in result payload. No failures remain in these rerun suites.
