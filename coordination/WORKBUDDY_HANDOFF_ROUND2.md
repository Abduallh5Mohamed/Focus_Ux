# WORKBUDDY HANDOFF — ROUND 2 (real browser QA + real API integration)

Owner: WorkBuddy. Scope: `product/apps/web/**`, `product/tests/web/**`, this file only.
The earlier `WORKBUDDY_HANDOFF.md` is preserved untouched.
Codex owns `BOARD.md`; I did not edit it. I did not edit API, worker, model, contracts or root manifests.

---

## CLAIM — 2026-10-29 (GMT+3)

**Claimed:** `product/apps/web/**` (incl. local manifest/deps) and `product/tests/web/**`.
**Not touched:** `services/api/**`, `services/worker/**`, `packages/ml/**`, `docs/**`, `contracts/**`, `BOARD.md`, other handoffs.

**Environment:** Chrome `C:/Program Files/Google/Chrome/Application/chrome.exe`, driven by
`puppeteer-core@23` installed **with `--no-save`** (not added to `package.json`/lockfile).
Node `v22.22.2`. Dev server used `vite --port 5174` (mock) and `vite --port 5175`
(mock OFF → real API). API temp instance on `127.0.0.1:8011` (temp DB, dispatcher on).

> This is a **real browser**, not jsdom. All screenshots below are Chrome captures.

---

## Headline

1. Ran the app in headless Chrome at **1280 / 390 / 320** and walked the whole flow
   (home → upload → face select → processing → result → compare → transcript → refresh).
2. **Found and fixed a real bug** the jsdom tests could not catch: after a refresh the
   transcript panel got stuck "loading" **and** simultaneously showed the "no speech" empty
   state, because the `transcriptKey` guard + React StrictMode aborted the only fetch.
3. Adopted the Round-2 contract decisions in the client: canonical bbox/frame_size, the
   approved `GET /videos/{id}/original` for honest after-refresh comparison, and a
   **token-leak guard** so the session Bearer token is never attached to a foreign origin.
4. **Connected the UI to the real API with mock OFF** and proved: `POST /videos → 201`,
   navigated to `/select/{id}`, `GET /videos/{id}/faces → 200`, and the UI rendered the
   real `PROCESSING_FAILED` state. No console/page errors.
5. Full job → audio → transcript → download could **not** be run end-to-end because the API
   ships `UnavailableCandidateProvider` / `UnavailableExtractionRunner` (ML not configured).
   No `ROUND2_STATUS.md` was published during this work, and port 8000 was not serving.
   That remainder is written down explicitly at the end.

---

## 1. Browser QA — method and evidence

Harness: `product/apps/web/scripts/browser/run-qa.mjs` (reusable), fixtures under
`scripts/browser/fixtures/`. Artifacts (PNGs + `summary.json`) in
`product/tests/web/browser/artifacts/`.

It captures, per viewport: console messages, `pageerror`s, `requestfailed`s, the keyboard
focus sequence, and horizontal-overflow offenders (`scrollWidth > clientWidth`).

| Viewport | console errors | page errors | overflow | notes |
|---|---|---|---|---|
| 1280×900 | 0 | 0 | none | — |
| 390×844 | 0 | 0 | none | — |
| 320×720 | 0 | 0 | none | cards stack correctly |

**Final run flags (all three viewports identical):**

```
uploadReady=true facesReady=true reachedResult=true isolatedReady=true hasTranscript=true
originalBeforeRefresh=true reachedResult2=true isolatedReady2=true
transcriptAfterRefresh=true emptyWhileLoading=false originalAfterRefresh=true
consoleErrors=0 pageErrors=0 overflow=false
```

Screenshots (24 PNGs + `summary.json`): `desktop-01-home … 07-after-refresh` (7),
`mobile-390-*` (7), `mobile-320-*` (7), `real-api-01-faces-unavailable.png`,
`result-actions-01-transcript-failed.png`, `result-actions-02-after-delete.png`.

### Result actions in the browser (download / delete / transcript-missing)

`scripts/browser/run-result-actions.mjs` (mock with `focus-mock-transcript-fail=1`):

```
audioUsable=true  transcriptFailedShown=true
wavDownloadEnabled=true  transcriptDownloadDisabled=true
download: focus-job_…-isolated.wav, 288044 bytes   (real file written to disk)
delete: confirmVisible=true returnedHome=true finalUrl=/ jobCleared=true
consoleErrors=[] pageErrors=[]
```

So: the WAV actually downloads, the two-step delete returns home and clears the session job,
and when the transcript fails the audio stays usable, the panel shows "التفريغ النصي فشل",
and the transcript download is correctly disabled.

**The only "failed requests" are `blob:… net::ERR_ABORTED`.** These are the `<audio>`
element aborting a load when a blob URL is revoked/replaced (mode switch, reload,
StrictMode remount). They are not network failures and are expected; verified by reading
`requestFailureSamples` in `summary.json`.

### Bugs found and fixed (UI scope)

| # | Symptom (observed in Chrome) | Cause | Fix |
|---|---|---|---|
| 1 | After refresh, transcript panel showed **"في الانتظار" + "مفيش كلام اتعرف عليه"** at once and never loaded | `transcriptKey` ref guard + StrictMode double-invoke: effect #1 set the key and fetched, cleanup aborted it, effect #2 saw the key and skipped → `loading` stuck true | Removed the redundant key guard (deps are already primitives); loading now resolves. `ResultView.tsx` |
| 2 | Empty state rendered while a transcript fetch was still in flight | empty state only checked `status==='ready' && segments.length===0` | also require `!loading`. `TranscriptPanel.tsx` |
| 3 | Long face id wrapped to two lines in the "الملف" facts ("vid_1c…" / "ce_1") | grid item lacked `min-width:0`; mono value wrapped | `min-width:0` on `.facts__item`; nowrap+ellipsis on `.facts__val.mono`. `components.css` |

> The teal "تخطَّ إلى المحتوى" skip-link that appeared in early screenshots was a **harness
> artifact**: the 6-Tab focus test left focus on the skip link and SPA navigation never
> blurred it, so `:focus-visible` kept it on. Harness now blurs after the focus test; the
> app's skip-link behaviour is correct (hidden until focused).

Keyboard: tab order observed = skip-link → brand → primary action → inline link → body.
Visible focus ring present on every stop.

---

## 2. Round-2 integration decisions — applied

| Decision | Status | Where |
|---|---|---|
| Canonical wire `bbox {x,y,width,height}`, `frame_size {width,height}` | already normalised; verified | `client.ts::normalizeBBox` |
| `GET /videos/{id}/original` for after-refresh original comparison | **added** `fetchOriginal()` + wired into results | `client.ts`, `mock.ts`, `ResultView.tsx`, `ComparePlayer.tsx` |
| Protected media: token only for the trusted API origin | **added guard** — foreign-origin / `data:` / `blob:` fetched anonymously | `client.ts::fetchMedia` |
| Thumbnail relative or trusted-API-origin only | enforced by the same guard | `client.ts` |
| ASR missing → transcript unavailable, audio still usable | already implemented; verified | `ResultView`, `TranscriptPanel` |
| Service worker = app-shell only, never API/auth/media | verified (SW already excludes auth/`/api/`/audio/video/range); smoke asserts it | `public/sw.js` |

**After-refresh original is honest:** the preferred source is the in-memory `File`
(no extra download); only when it is gone (after refresh) does the app call
`GET /videos/{id}/original`. The player labels the source ("من نفس الفيديو اللي رفعته"
vs "اتجاب من الخادم"). A failed fetch shows a warn notice and a retry, and never blocks
the isolated track.

**Dev mock persistence (QA-only):** the mock now persists its video/job state to
`sessionStorage` so the after-refresh flow is exercisable in a real browser. Per-tab, cleared
on tab close, dev-only. Without it the mock loses the job on reload and the result page
cannot re-open — that was why the first QA pass reported `originalAfterRefresh=false`.

New unit tests: 3 for the token guard (same-origin tokened, foreign-origin anonymous,
`data:` anonymous). Updated 1 results test for the now-available original.
**53 tests / 6 files pass** (was 50).

---

## 3. Real-API results (kept separate from mock)

### 3a. Contract smoke — actual API, temp instance, `127.0.0.1:8011`

```
POST /videos (multipart t8_1280x720.mp4)   -> 201
   {video_id, metadata:{duration_ms:10000,width:1280,height:720,size_bytes:124394},
    faces_status:"pending", session_token:"…"}
GET  /videos/{id}/faces  (Bearer)          -> 200
   {status:"failed", faces:[],
    error:{code:"PROCESSING_FAILED", message:"face candidate provider is not configured", retryable:true}}
GET  /videos/{id}/original (Bearer)        -> 200  content-type: video/mp4
   content-length: 124394 (= exact source bytes)  accept-ranges: bytes
   cache-control: private, no-store
GET  /videos/{id}/original (no token)      -> 401
GET  /videos/{id}/original (Range 0-99)    -> 206
DELETE /videos/{id} (Bearer)               -> 202
OPTIONS /videos/{id}/faces (Origin :5175)  -> 200  allow-origin echoes origin,
   allow-headers include Authorization, methods GET,POST,DELETE,OPTIONS
```

This proves the client's paths, Bearer auth, the `/original` endpoint and its exact-byte
delivery, Range support, 401 ownership enforcement, delete and CORS all match the real API.

### 3b. UI against the real API (mock OFF)

`scripts/browser/run-real-api.mjs`, UI on `:5175` with `VITE_API_BASE_URL=http://127.0.0.1:8011`:

```
mockPillVisible=false  uploadEnabled=true  navigatedToSelect=true
url=/select/8c1b599e…   facesFailedShown=true   consoleErrors=[]  pageErrors=[]
apiCalls: OPTIONS /videos 200 · POST /videos 201 · OPTIONS /videos/{id}/faces 200
          · GET /videos/{id}/faces 200
```

Screenshot `real-api-01-faces-unavailable.png`: no demo pill, and the UI shows
"معرفناش نكشف الوجوه في الفيديو" with code `PROCESSING_FAILED`.

**This is real, not simulated.** It stops at face detection because the API's provider is
`Unavailable` — that is the honest state, not a mocked success.

---

## 4. Commands and results

| Command (from `product/apps/web`) | Result |
|---|---|
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0 — 76 modules, CSS 18.44 kB, JS 216.92 kB (gzip 70.59 kB) |
| `npx vitest run` | exit 0 — **53 tests / 6 files** |
| `node ../../tests/web/smoke.mjs` | exit 0 — **20/20** |
| `node scripts/browser/run-qa.mjs http://localhost:5174` | 3 viewports, 0 errors, 0 overflow, all flags true |
| `node scripts/browser/run-result-actions.mjs http://localhost:5174` | download 288044 B, delete→home+cleared, transcript-failed + audio usable, 0 errors |
| `node scripts/browser/run-real-api.mjs http://localhost:5175` | upload 201, real failed-faces state, 0 errors |

**Ports used and then stopped:** 5174 (mock UI), 5175 (mock-off UI), 8011 (temp API).
No long-running process left behind.

---

## 5. Changed files

- `src/lib/api/client.ts` — `fetchOriginal`; absolute-URL-safe `requestBlob`; origin-guarded `fetchMedia`.
- `src/lib/api/mock.ts` — `fetchOriginal`; `buildMockWav(baseHz)`; sessionStorage persistence; token-free `fetchMedia`; dev-only `focus-mock-transcript-fail` switch.
- `src/features/results/ResultView.tsx` — original fetch/loading/error/retry; removed transcript key guard.
- `src/features/results/ComparePlayer.tsx` — original source/loading/error UI.
- `src/features/results/TranscriptPanel.tsx` — empty state gated on `!loading`.
- `src/styles/components.css` — facts `min-width:0`, mono ellipsis.
- `src/lib/api/__tests__/client.test.ts` — 3 token-guard tests.
- `src/__tests__/results-flow.test.tsx` — original now available.
- `scripts/browser/run-qa.mjs`, `run-real-api.mjs`, `run-result-actions.mjs`, `scripts/browser/fixtures/sample.mp4` — QA harness (not in bundle).
- `product/tests/web/browser/artifacts/**` — screenshots + `summary.json`.

No `package.json`/lockfile change (`puppeteer-core` is `--no-save`).

---

## 6. NOT verified / blockers (honest)

- **Full job E2E (audio + transcript + download) is blocked by ML.** The API's
  `UnavailableCandidateProvider` returns `PROCESSING_FAILED`; no real face is produced, so no
  job can be created against the real server. Everything after face selection is exercised
  **only against the mock**, and is labelled as such.
- **No `ROUND2_STATUS.md`** was published while I worked, and `127.0.0.1:8000` was not serving.
  I did not assume readiness; I ran my own temp instance on 8011 for read-only contract tests.
- **PWA install / real device** not done (manifest + SW verified at the artefact level only).
- **Original-after-refresh against the real API** was proven at the contract level (3a) and the
  UI path was proven against the mock (2). A combined real-API after-refresh run needs a
  completed job, which needs ML.
- Minor: when ML is unconfigured the UI surfaces the server's English message
  "face candidate provider is not configured". It is not a traceback or a secret, but it is
  internal wording; it disappears once the provider is configured. Left as-is (API-owned text).

---

## 7. Next steps (exact) — when API + ML are ready

1. Publish `ROUND2_STATUS.md` with the base URL and confirm ML providers are wired
   (replace `Unavailable*`), and that `FOCUS_API_UI_ORIGINS` includes the UI origin.
2. Point the UI at it with mock OFF:
   ```bash
   cd product/apps/web
   echo "VITE_API_BASE_URL=http://127.0.0.1:8000" > .env.local   # mock stays OFF
   npm run dev            # http://localhost:5173 (matches API default CORS)
   ```
3. Re-run the full browser harness against it with a real approved fixture and confirm:
   faces `ready`, choose a face, job `queued→processing→completed`, `GET /jobs/{id}/audio`
   plays, transcript present-or-unavailable, after-refresh `/original` compare, download, delete.
   (The harness needs the fixture path swapped from the placeholder to the real clip.)
4. Two-session ownership: open a second browser profile, confirm the first session's job id
   returns 401 (the API already enforces this — verified for `/original`).

Everything above is in my scope and requires no further frontend changes; the only open
dependency is the ML provider behind the API.
