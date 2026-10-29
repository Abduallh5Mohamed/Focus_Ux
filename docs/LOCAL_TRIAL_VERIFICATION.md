# Local trial snapshot verification — 2026-10-29

## Integrated prerequisite snapshot

The release checkout starts from
`dd035ba926c3c6413783674378b9538fb7073fe5` on `main`.
The required live changes are present in its actual history and working tree:

- `dd035ba`: wait for late audio / explicit playback measurement outcomes;
- `2616dd1`, `391f82e`, `6cdd895`: bounded finalization, response-body deadlines,
  immediate rejection and capture teardown;
- `c506ed3`, `bd68131`: owner-scoped interrupted startup cleanup and native
  browser lifecycle regressions;
- `c2fe579`, `fa4c542`: bounded chunk upload and native ordered playback.

This handoff does not wait for unrelated proposed follow-ups or claim that
changes completed in another task environment are part of this snapshot.
The main-workspace SSH fetch could not authenticate non-interactively; no
password was supplied. The prerequisite changes above were verified locally
as ancestors, not inferred from task status.

## Executed in the Linux/Replit environment

| Check | Result |
|---|---|
| `npm --prefix product/apps/web run build` | passed (TypeScript + production bundle) |
| `npm --prefix product/apps/web test` | 67 passed, 7 files |
| Chromium `npm --prefix product/apps/web run test:browser` | 25 passed |
| API suite | 185 passed, 1 skipped |
| Inference protocol/runtime suite | 35 passed |
| ML suite | 71 passed |
| Worker suite | 24 passed |
| Evaluation suite | 35 passed |
| Live frontend proxy test, with `FOCUS_TEST_PROXY_URL` | 1 passed |
| Local trial runtime tests after final CLI wording change | 21 passed |
| Application workflow restart and homepage screenshot | serving successfully |
| `git diff --check` | passed |

Python suites were run separately using:

```sh
PYTHONPATH=product:product/packages/ml python -m pytest product/tests/<suite> -q
```

The API suite skips the proxy check when no proxy URL is provided. It was then
run explicitly against the running frontend with:

```sh
FOCUS_TEST_PROXY_URL="https://$REPLIT_DEV_DOMAIN" PYTHONPATH=product:product/packages/ml \
  python -m pytest product/tests/api/test_proxy.py -q
```

Browser tests used the preinstalled Chromium through
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/repl/tools/bin/chromium`. They exercise real
browser media/lifecycle/playback code with synthetic API responses and test
devices. Inference/API tests use inference doubles; normalization tests do run
real ffmpeg. **None of these results establish GPU inference quality or real
camera capture-to-play latency.** Existing warnings are FastAPI's test-client
deprecation and React Router future flags; no failing checks were hidden.

## Local support and release safety

- The new PowerShell entry point starts only the API using the trial checkout's
  isolated `.venv`. It does not install dependencies or change the original ML
  environment. Instructions use the locked API dependency set.
- The explicit worker `--local-api` mode permits only
  `http://127.0.0.1:5000` (optionally `/api`), disables inherited HTTP proxies,
  uses a separate trial credential, and refuses preview credentials and redirects.
  Default remote operation still requires HTTPS.
- Trial media, database and credentials are outside the checkout under the
  Windows account's LOCALAPPDATA. Ignore rules also cover local environments,
  runtime folders, upload/model folders and weight file extensions.
- Reviewed tracked filenames/sizes and credential-shaped literals: no matching
  private-key, GitHub-token or Hugging Face-token literals. This is a focused
  release-safety check, not a full security audit. No environment secret values
  were read or printed.
- No new media, weights, caches, database or runtime files are included.
  The existing tiny browser fixture and historical reference screenshots remain
  unchanged; there was no unrelated repository cleanup.

## Explicitly not verified

PowerShell is unavailable here, so the script has **not been executed on Windows**.
No original model weights, CUDA device, physical camera or headphones are
available in this workspace. The native Windows launcher, original dependencies,
upload listening test and ≥60-second live measurements must be checked on the
user's computer using [LOCAL_WINDOWS_TRIAL.md](LOCAL_WINDOWS_TRIAL.md).
The existing real-device measurement work owns acceptance; the gate stays
`internal_only`, off by default. No production deployment was performed.

The exact pushed handoff commit is supplied in the delivery message; this file
records its prerequisite base rather than a self-referential commit hash.
