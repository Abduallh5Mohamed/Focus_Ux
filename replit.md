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

The two suites pass 24 and 47 tests respectively. The web suite passes 53 tests.
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
The health response only confirms the API and dispatcher, not ML readiness.

## Important limitation

**Real face detection and speaker isolation are not operational.** The imported
API factory uses `UnavailableCandidateProvider` and `UnavailableExtractionRunner`.
Its real ML adapter, model weights, and GPU inference are not wired into this
server. Uploads can be accepted, but detection reports an explicit failure.
The original Windows GPU/assets paths are not available in this workspace.
Do not substitute fake audio or claim the ML tests verify real inference.
No public deployment was performed.

## Error-metric tool

`product/packages/eval/focus_eval` scores existing isolation outputs (wrong-person rate, CER/WER on normalised Arabic, SI-SDRi) and compares two runs for regressions. It needs only `numpy`, runs no engine/GPU/ASR, and the test set template lives in `product/datasets/egyptian_eval/` (see its README). Run its tests with `PYTHONPATH=product python -m pytest product/tests/eval -q`. Real measurements must be produced on the GPU machine.

Adaptive face tracking (`focus_ml/adaptive_tracking.py`) is opt-in and unvalidated; `python -m focus_eval gate` decides adoption from GPU-machine runs. See `docs/DEV1_ML.md`.
