# Running FOCUS on Replit

This is the imported React/TypeScript web app and Python/FastAPI backend, kept in
their original `product/` layout. No model weights were downloaded.

## Start and stop

Use Run to start the **Start application** workflow, or run:

```bash
bash scripts/run-replit.sh
```

The script starts Vite on `0.0.0.0:5000` and Uvicorn on `127.0.0.1:8000`.
Vite forwards browser `/api/*` requests to the backend, removing `/api`.
The frontend uses the real API with mock mode explicitly disabled.
Stopping the workflow stops both processes. Do not run a second dispatcher.

SQLite, uploads, and job files live in `runtime/replit/api/`, excluded from Git
and publishing. This is development storage, not a production persistence setup.
The existing API generates its own session bearer tokens; no external API keys
are required for this limited configuration.

## Dependencies

- Replit provides Node 22 and Python 3.12.
- Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`.
- Web dependencies are in `product/apps/web/package.json` and its lockfile.
- Restore web dependencies with `cd product/apps/web && npm ci`.
- Vite, its React plugin, and Vitest were updated because the imported locked
  tooling was blocked by the package firewall for critical vulnerabilities.

## Verification

```bash
cd product/apps/web
npm run build
npm test
```

From the repository root, run Python suites separately:

```bash
PYTHONPATH=product python -m pytest product/tests/worker -q
PYTHONPATH=product python -m pytest product/tests/ml -q
PYTHONPATH=product python -m pytest product/tests/api -q
```

Current handoff verification is recorded in `docs/LOCAL_TRIAL_VERIFICATION.md`;
the separate Windows-local procedure is in `docs/LOCAL_WINDOWS_TRIAL.md`.
The API suite covers uploads, sessions, protected media, queued deletion, and
unavailable providers using test-only inference doubles. API helpers use relative
package imports to avoid the worker's top-level `fakes` module.

With the application workflow running, exercise the real `/api` proxy too:

```bash
FOCUS_TEST_PROXY_URL="https://$REPLIT_DEV_DOMAIN" PYTHONPATH=product \
  python -m pytest product/tests/api -q
```

Without `FOCUS_TEST_PROXY_URL`, only the live proxy smoke test is skipped. That
test creates and deletes its own metadata-only upload; it does not verify real
inference or require model weights.

Health check through the frontend: `GET /api/healthz`.
The inference field reports configured mode and, in remote mode, recent worker
contact. A connection alone is not proof of isolation quality.

## Important limitation

**Real inference is wired but has not been verified on the user's Windows GPU.**
The default `FOCUS_INFERENCE_MODE=unavailable` still fails explicitly. Set mode
to `remote` only after adding a private `FOCUS_WORKER_TOKEN` in Replit Secrets
and starting the Windows worker. Mode `local` uses the same real adapter on a
CUDA host with the original source/cache and ML dependencies.

After merging this task, use the main URL from Networking, not the task preview
URL. Download the allowlisted worker source kit at `/api/worker-kit.zip`. It uses the
original `A:\focus\.venv`, `A:\focus\Dolphin`, `A:\focus\cache\hf` and
`A:\focus\cache\torch`, without installing packages or downloading weights.
See `docs/WINDOWS_INFERENCE.md` for setup, revocation and remaining blockers.

Normalization uses real ffmpeg on the server before detection: 25 fps,
orientation-corrected, timeline-equivalent MP4. Both inference stages and browser
playback use these same canonical bytes and the persisted selected face ID.
Remote tasks use HTTPS outbound polling only; no Windows listening port is used.
Stopping the worker, missing assets or a timeout never produces simulated audio.
There is no ASR provider: usable isolated audio does not imply a transcript.

Protocol tests (including real ffmpeg normalization with synthetic worker
responses) run separately from ML and worker suites:

```bash
PYTHONPATH=product:product/packages/ml python -m pytest product/tests/inference -q
```

These tests are **not real GPU inference evidence**. No public deployment was
performed. No model weights were downloaded or copied into the project.
## Error-metric tool

`product/packages/eval/focus_eval` scores existing isolation outputs (wrong-person rate, CER/WER on normalised Arabic, SI-SDRi) and compares two runs for regressions. It needs only `numpy`, runs no engine/GPU/ASR, and the test set template lives in `product/datasets/egyptian_eval/` (see its README). Run its tests with `PYTHONPATH=product python -m pytest product/tests/eval -q`. Real measurements must be produced on the GPU machine.

Adaptive face tracking (`focus_ml/adaptive_tracking.py`) is opt-in and unvalidated; `python -m focus_eval gate` decides adoption from GPU-machine runs. See `docs/DEV1_ML.md`.

## Result downloads and voice mix
- Downloads: isolated WAV (`GET /jobs/{id}/audio`), transcript text, and an exported MP4 (original picture copied unchanged + the new mix).
- The result page has Selected voice / Other voices / Background noise reduction controls. "Other voices" is original minus the isolated voice after alignment and level matching; when that is unreliable the slider is disabled with an Arabic explanation. Noise reduction is a plain high/low-pass filter, not AI.
- Mix math lives in `product/services/api/focus_api/mix.py`; exports in `mix_service.py`. Export needs `ffmpeg` (set `FOCUS_FFMPEG` if not on PATH). Exports are stored under `jobs/<job>/exports` and removed with the video.
- Tests: `python -m pytest product/tests/api/test_mix_math.py product/tests/api/test_export.py`; web: `voice-mix.test.tsx`.
