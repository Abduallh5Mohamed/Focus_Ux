# FOCUS web app

Upload a short video, pick which detected face to isolate, watch the job, compare the
original with the isolated track, read the transcript when it arrives, then download or
delete. Arabic RTL UI, dark theme, installable app shell.

React 18 + Vite 5 + TypeScript. No UI framework, no icon package, no state library.

## Requirements

- Node 20+ (verified on Node 22.22.2, npm 10.9.7)
- The FOCUS API (`product/services/api`) for real use — this app does not run inference

## Run

```bash
cd product/apps/web
npm install

# real API: point it at the backend first
cp .env.example .env.local     # then set VITE_API_BASE_URL
npm run dev                    # http://localhost:5173

# UI work without a backend (explicit mock, never on by default)
npm run dev:mock               # loads .env.mock -> VITE_DEV_MOCK_API=1
```

| Command | What it does |
|---|---|
| `npm run dev` | Dev server, real API client |
| `npm run dev:mock` | Dev server with the in-memory mock adapter + a permanent "وضع تجريبي" badge |
| `npm run build` | `tsc --noEmit` then a production build into `dist/` |
| `npm run typecheck` | Types only |
| `npm test` | Vitest (jsdom) — 50 tests |
| `npm run icons` | Regenerates `public/icons/*.png` (no network, no deps) |

Smoke test the built artefact (starts `vite preview` itself):

```bash
cd product/apps/web && npm run build
node ../../tests/web/smoke.mjs
```

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | empty (same origin) | Base URL of the API. Empty means relative requests. |
| `VITE_DEV_MOCK_API` | `0` | Dev-only. Ignored in a production build (`import.meta.env.DEV` guard). |

No secrets belong in these files. The session token is issued by the server on the first
upload and kept in `localStorage` under `focus.session.v1`; it is sent as
`Authorization: Bearer …` and never placed in a URL or a log.

## Flow and routes

| Route | Screen | Source |
|---|---|---|
| `/` | Landing + resume an open job | `pages/HomePage.tsx` |
| `/upload` | Pick, preview, validate, upload | `features/input/IntakeFlow.tsx` |
| `/select/:videoId` | Poll faces, choose one, start the job | `features/input/FaceSelect.tsx` |
| `/job/:jobId` | Live status, stage rail | `features/input/ProcessingView.tsx` |
| `/job/:jobId/result` | Compare player, transcript, download, delete | `features/results/ResultView.tsx` |

## Layout

```
src/
  lib/
    api/          contract types, typed client, error mapping, mock adapter, React context
    session.ts    token + active video/job ids (localStorage, never in the URL)
    localMedia.ts the uploaded File, kept in memory for the original-vs-isolated compare
    useJob.ts     polling with backoff, stops when the job and transcript settle
    env.ts        build-time flags and upload limits
  components/     Button, Card, Notice, Pill, ProgressBar, Steps, Icon, AppShell…
  features/
    input/        upload, face selection, processing view
    results/      compare player, transcript, download/delete
  pages/          route shells that compose the features
  styles/         tokens, base, layout, components
```

## API contract used

Only the endpoints in `docs/02_CONTRACTS.md`:

```
POST   /videos                    upload (multipart)
GET    /videos/{id}/faces         candidates: face_id, bbox, timestamp_ms, frame_size
POST   /jobs                      { video_id, face_id, client_request_id }
GET    /jobs/{id}                 status, stage, audio_status, transcript_status
GET    /jobs/{id}/audio           WAV blob
GET    /jobs/{id}/transcript      segments
DELETE /videos/{id}
```

The client normalises `bbox` from `{x,y,w,h}`, `{x,y,width,height}` or `[x1,y1,x2,y2]` into
`{x,y,width,height}` in original-frame pixels so the UI never has to guess. That tolerance
is the only place the wire shape is interpreted.

## Behaviour worth knowing

- **No invented progress.** Server processing shows an indeterminate bar. A determinate
  bar is used only for real upload byte progress. No ETA anywhere.
- **One audio element.** The compare player switches `src` and restores `currentTime`, so
  "the same moment" means the same moment. The original track comes from the file held in
  memory; after a refresh it is reported unavailable rather than faked.
- **Audio never waits on the transcript.** The job page redirects to results as soon as
  `audio_status === 'ready'`; transcript status is shown separately.
- **Offline is honest.** The service worker caches the app shell only. It skips
  cross-origin, `/api/`, authorized, ranged, audio and video requests.
- **Deletion is two-step** and cannot fire twice.

## Known gaps

- No real API was available while building this, so every network path is exercised only
  against the mock adapter and unit tests. Nothing here proves server behaviour.
- The original/isolated comparison needs the uploaded file in the same tab. The contract
  has no endpoint for the original track.
- `VITE_DEV_MOCK_API` is dev-only by design; a production build cannot show mock audio.
- Camera/realtime capture is out of scope for this milestone.
