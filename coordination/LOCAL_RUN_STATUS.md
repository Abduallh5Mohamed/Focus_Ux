# Local run — 2026-10-30

## Short-result investigation — uploaded file is 0.167 s

User reported a supposed 15 s clip yielding a tiny result (job `aee63138f1594517bdb99c983c91de9e`). Read-only inspection of that job and original upload confirmed: source MP4 is 551872 bytes, FFmpeg decodes **five video frames / 0.166667 s** at 30 fps; decoded source audio is about 0.149 s. Canonical video is four frames / 0.160 s at 25 fps; output WAV is **2560 samples / 16000 Hz = 0.160 s**. The original stored upload itself does not contain 15 seconds. No original, canonical media, job result, or database row was modified during investigation; the missing source content cannot be reconstructed from this upload.

UI formatting rounded positive subsecond durations to zero. Fixed `src/lib/format.ts` to retain fractional durations/clocks below one second; added a non-blocking warning in `features/input/IntakeFlow.tsx` when the selected local file is shorter than one second. Added two formatter regression cases. Web suite: **75 passed / 7 files**, typecheck passed. Actual Chrome local-file preview (without uploading again) reads 0.166667 s and shows **0.167 ث** with the short-file warning. Evidence: `runtime/local-session/short-upload-check.{json,png}`.

Also validated full-length extraction independently using a **15 s duration-test fixture assembled by looping the existing official 13.20 s demo**, not the user's media. Source fixture preserved; generated test file is `runtime/local-session/fixtures/dolphin-duration-test-15s.mp4`. Real API upload -> two faces -> last face selected -> extraction passed; input metadata **15000 ms**, WAV **15000 ms, mono 16 kHz**, protected media 401 without token. Report: `runtime/local-session/api-smoke-15s/report.json`, output `isolated.wav`. This verifies duration handling and does not claim subjective quality or reconstruct the user's missing seconds. Updated the ignored API smoke helper to accept video/output arguments and validate against uploaded duration.

User needs to select/export the complete intended video and upload that file. Existing services stay running, no new downloads and all runtime/test/cache data remain on D:.

## Face thumbnail fix — user-reported broken images

Reproduced with the real running API and Chrome: candidate thumbnails requested `/videos/.../thumbnail` from Vite without Authorization and returned HTTP 200 `text/html`, so image natural dimensions were 0x0. Earlier browser smoke checked candidate cards but did not assert image decoding; its "no API errors" result did not catch HTML returned with 200.

Fixed `product/apps/web/src/lib/api/client.ts` to resolve relative/empty API bases against the page origin, then fetch trusted media through the `/api` prefix with the Bearer header. Foreign-origin, data and blob media remain uncredentialed. Fixed `FaceSelect.tsx` to preserve face crops with contain sizing, apply frame-coordinate boxes only to frame-shaped thumbnails, and show a fallback on image decode errors.

Regression coverage added to existing client/intake test files for relative bases, foreign network-path token isolation, invalid image decoding and crop/full-frame display. `npm.cmd --prefix product/apps/web test`: **73 passed / 7 files**. `npm.cmd --prefix product/apps/web run typecheck`: exit 0. `git diff --check`: exit 0.

Real Chrome recheck using existing smoke media/session: both requests now `/api/videos/.../thumbnail`, authorized, HTTP 200 `image/jpeg`; decoded dimensions 70x92 and 82x118, no fallbacks. Before/after reports and screenshots: `runtime/local-session/thumbnail-before.{json,png}`, `thumbnail-after.{json,png}`. No re-upload, API restart, new GPU model load, dependency installation or C: downloads were needed. Vite serves the updated code; reload the existing select page. Frontend changes are limited to the user's explicitly requested repair; WorkBuddy handoffs preserved.

## Verified running state — final update

**Real GPU upload/extraction was validated on this machine.** UI http://127.0.0.1:5173; API http://127.0.0.1:8000. API `/healthz` through the UI proxy reports `dispatcher=true`, `inference.mode=local`. Mock and live modes are disabled. Latest user-requested restart: both ports were initially stopped; both launch commands succeeded, UI HTTP 200 and proxied API health verified. Services left running: API PID 16808, UI Node PID 22356. Models load lazily on first upload; the real GPU smoke documented below was not repeated for this restart.

All new assets, Python environments, dependency caches, CUDA libraries, temporary data, browser profile/cache and results are on D:. Final audit again found **zero session-created files** in the existing C: uv/npm caches. Existing Python/Node/uv executables on C: were not replaced. NVIDIA reports the pre-existing Store Python executable on C: as the process image; its virtual environment and downloaded torch/CUDA packages are under this checkout's `.venv-ml` on D:.

### Commands to run again

From `D:\Focus\Focus_Ux`, in two PowerShell terminals after stopping the existing instances:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File product\tools\run_local.ps1 -Service api
powershell -NoProfile -ExecutionPolicy Bypass -File product\tools\run_local.ps1 -Service web
```

Each command runs in its own terminal. Wait for active processing to finish before stopping. In terminals started this way use Ctrl+C. For the current tool-started processes, verify port ownership first with `Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 8000,5173`; then `Stop-Process -Id 16808,22356` stops the currently recorded instances. Do not reuse stale PIDs after a restart.

### Executed real validation

- `.venv-ml`: torch `2.8.0+cu126`, torchvision `0.23.0+cu126`, torchaudio `2.8.0+cu126`. `uv pip check --python .venv-ml/Scripts/python.exe`: 82 compatible packages. RetinaFace `0.0.19` uses its supported PyTorch backend; TensorFlow was not installed. Hugging Face Hub pinned to `0.36.0` for the upstream loader's API.
- `run_local.ps1 -Service check`: `CUDA: True`, `Models loaded on cuda`.
- Real fixture: official Dolphin `real-world-demo/demo1/mix.mp4` at source revision recorded below, cropped into a separate six-second, 640 px-wide, 25 fps local test clip. Original downloaded fixture preserved. The separate `public/video/video.mp4` example turned out to be an illustration and was not used for the successful face/extraction test.
- `verify_gpu.py --video runtime/local-session/fixtures/dolphin-real-world-6s.mp4 --output runtime/local-session/gpu-smoke`: passed. Two stable repeated face candidates; both targets extracted to distinct, finite, nonzero, mono 16 kHz WAVs of exactly 6000 ms, offset 0. Load 19.42 s; extraction 39.69 s for first target and 18.36 s for second; CUDA forward totals about 1.60/1.42 s. This is a local smoke, not GT parity, a quality score, or a realtime gate pass.
- Upstream's newer source includes 98 training/reconstruction-only keys absent from the published checkpoint. Initial whole-model strict check failed on those keys. Source review identified the omitted heads; validation then rejected every other missing/unexpected key and installed execution guards on the omitted modules. Both real extractions passed without executing any omitted head. Initial failure report is preserved beside the passing GPU report.
- First actual extraction exposed an AAC decode tail: 256 extra samples after the video end created an audio window with zero mouth frames. Adapter now aligns codec/frame rounding within 80 ms to the canonical frame duration, records adjustment, and refuses larger mismatches. The failure report is preserved as `report-aac-tail-failure.json`.
- Regression command: `.venv-ml/Scripts/python.exe -m pytest product/tests/ml/test_audio_codec_alignment.py -q --basetemp runtime/local-session/pytest-codec`: **4 passed**. Test-only passthrough model/CUDA event fakes remain exclusively in tests. `.venv/Scripts/python.exe -m pytest product/tests/ml product/tests/worker -q --basetemp runtime/local-session/pytest-core-after-fix`: **95 passed, 1 skipped** (the new regression module requires torch/soundfile absent in this smaller environment; its four tests passed in .venv-ml).
- Real API smoke `runtime/local-session/api_smoke.py`: upload 201, two ready faces, selected last face, observed processing/tracking -> completed/ready. WAV 6000 ms/16 kHz/mono; authorized original media works; anonymous audio and original requests return 401. Missing ASR is reported as transcript failed/not_configured while audio stays ready. Report: `runtime/local-session/api-smoke/report.json`.
- Real Chrome smoke with mock off: upload -> two face cards -> last face selected -> result -> download **192044 bytes** -> page refresh preserved usable result. No page, console or API errors. Native playback advanced for isolated audio (duration 6 s) and original audio after refresh (duration 6.016 s), with no media errors. Reports/screenshots/profile under `runtime/local-session/browser-smoke`; token is not printed in reports.

### Changed tracked/new product files

`product/packages/ml/focus_ml/adapter.py` (AAC tail alignment); `product/tests/ml/test_audio_codec_alignment.py` (four regressions); `product/tools/local_paths.ps1`, `run_local.ps1`, `verify_gpu.py` (D: paths, launch, real verification). Coordination status/handoff updated. API and frontend source/manifests/lockfiles unchanged. No global packages/drivers changed, training, deployment or push.

ASR remains unconfigured, and the pre-existing Windows killed-upload cleanup test failure/timer warnings documented below remain unresolved. Human listening evaluation and GT reference scores were not performed.

## Current setup work / D: storage constraint

User authorized installing and running the model, then explicitly required all new downloads, CUDA libraries, code, caches and temp outputs on D:. Two pending uv installers using the default C: cache were stopped. Approximately 1.6 GiB of session-created uv/npm cache files were identified by creation time since 09:14:40. Automatic command review rejected recursive deletion on C:, so the files were instead preserved under `runtime/local-session/reclaimed-c-cache` on D: with native PowerShell Move-Item and checked source/destination paths. Older unrelated cache entries were preserved. A subsequent inventory found zero session-created files remaining in either C: uv or npm cache. Test data from this session was also moved to D:; empty directories/broken pytest convenience links may remain on C:.

`product/tools/local_paths.ps1` configures per-process uv/pip/npm/HF/torch/Keras/DeepFace/CUDA/Numba caches and TEMP/TMP/TMPDIR on D:. `run_local.ps1` sources it for API, frontend and GPU checks. No machine/user PATH changes or global CUDA/driver installs. Existing Python/uv/Node executables on C: are only used as pre-existing tools. CUDA runtime is part of the dedicated `.venv-ml` PyTorch installation on D:.

Official runtime source downloaded as individually Git-blob-verified files into ignored `model-assets/Dolphin-runtime`, revision `9ff6f79518f13296abe56bdcbf6297330a6a68a1`. Git clone was cancelled after stalling; its partial checkout under `model-assets/Dolphin` is unused. Supporting FAN/S3FD/RetinaFace assets are downloaded under D: model-assets/cache with recorded hashes. GPU inference remains pending until dependencies finish and real validation executes.

CPU baseline after enabling FFmpeg: 314 passed, 1 skipped, 1 existing failing API cleanup case (`owner-killed-read`), plus closed-database timer warnings. Before FFmpeg preparation there were five additional missing-ffmpeg fixture errors. These tests use fake-backed inference seams; no GPU success is inferred. API source and tests have not been edited.

## Weight download update — user authorized 2026-10-30

The user explicitly requested downloading the official weights, superseding the earlier no-download restriction for this download. Download completed from Hugging Face `JusperLee/Dolphin`, pinned revision `348a88fb05fc2953ee585d5ab7a7f27f1efb9c13`, using checkout-local Python and stdlib urllib. No packages installed for this step.

Cache root: `model-assets/cache/hf/hub/models--JusperLee--Dolphin`. Snapshot contains `model.safetensors` (28,391,276 bytes), `config.json` and `README.md`. The current repository does not contain the older model-card example's `best_model.pth` or `conf.yml`.

Verified model SHA256 against repository LFS metadata: `9be694e4150588ca0af8447fae184b6262a3cf43587928bd6001eee5b4eefb8a`. Small files verified against Git blob hashes and all sizes checked. Download command exited 0; manifest is `download-verification.json` inside cache root. Assets are Git-ignored. No checkpoint deserialization or inference was performed. Full Dolphin source/runtime, face-processing assets and ffmpeg still need preparation and validation; the API is not claimed inference-ready.

## Earlier service startup observations

Codex started the current checkout on the user's Windows machine.

- UI: http://127.0.0.1:5173 (loopback only, mock disabled, live disabled).
- API: http://127.0.0.1:8000 (single Uvicorn process).
- GPU: NVIDIA RTX 2050, 4096 MiB; driver reports 617.42. CUDA execution in PyTorch was not tested.
- Real inference BLOCKED: user confirmed the legacy Dolphin source/assets and weights are not available on this machine. No A: drive exists. No weights downloaded. ffmpeg/ffprobe are also absent from PATH.
- API explicitly runs with `FOCUS_INFERENCE_MODE=unavailable`. A healthy HTTP service does not mean working extraction.

Commands and observations:

1. `uv sync --locked --no-python-downloads`: succeeded, Python 3.12.10, 25 packages in checkout-local `.venv`. Global/legacy packages unchanged.
2. `npm.cmd --prefix product/apps/web ci`: failed because lockfile URLs use an unreachable internal Replit package server.
3. Copied web package/lock into ignored `runtime/local-session/web-deps`, replaced only the registry URL prefix there with `https://registry.npmjs.org/`, and ran `npm.cmd --prefix runtime/local-session/web-deps ci --registry=https://registry.npmjs.org --fetch-retries=0`: succeeded, 137 packages; npm reported two moderate vulnerabilities. Tracked web files unchanged. Partial original node_modules retained under `runtime/local-session/incomplete-node_modules`; web node_modules now junctions to the successful local installation.
4. API: `.\.venv\Scripts\python.exe -m uvicorn services.api.focus_api.main:app --host 127.0.0.1 --port 8000 --workers 1`, with `PYTHONPATH` pointing to product and product/packages/ml, storage `runtime/local-session/api`, inference unavailable, live disabled. Process 4240 started successfully.
5. UI: `npm.cmd --prefix product/apps/web run dev -- --host 127.0.0.1 --port 5173`, with `VITE_API_BASE_URL=/api`, `VITE_DEV_MOCK_API=0`, `VITE_LIVE_ENABLED=0`. Port 5000 failed with EACCES, so 5173 was used.

Verification: UI `/` and transformed `/src/main.tsx` returned HTTP 200. UI proxy `/api/healthz` returned `status=ok`, `dispatcher=true`, `inference.mode=unavailable`. Listeners were 127.0.0.1:8000 (PID 4240) and 127.0.0.1:5173 (PID 13784).

Both services were left running for the user. No real upload-to-extraction or browser audio test is claimed. Stop the respective server processes when finished; check port ownership before stopping any process. The standard Windows trial launcher still requires ffmpeg and real assets and was not used here.
