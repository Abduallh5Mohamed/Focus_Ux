# WORKBUDDY HANDOFF — FOCUS web app

Owner: WorkBuddy. Scope: `product/apps/web/**`, `product/tests/web/**`.
Codex owns `BOARD.md`; I only write this file.

---

## CLAIM — 2026-10-29 16:20 (GMT+3)

**Claimed:** `product/apps/web/**` (including local package manifest/lockfile) and `product/tests/web/**`.
**Not touching:** root workspace manifests, `docs/**`, `contracts/**`, `services/api/**`, `services/worker/**`, `packages/ml/**`, `BOARD.md`, any other agent's handoff.

**Observed state at claim time:** `A:/Focus_Ux/product` did not exist (no API, no worker, no web). Nothing to continue — scaffolding a fresh Vite + React + TypeScript app at `product/apps/web`. `node v22.22.2`, `npm 10.9.7` available.

**Planned file ownership split (no parallel edits to the same file):**

| Owner | Paths |
|---|---|
| WorkBuddy (foundation) | `apps/web/{package.json,tsconfig*.json,vite.config.ts,index.html,.env*,.gitignore,scripts/}`, `apps/web/public/**`, `apps/web/src/{main.tsx,App.tsx,app/,pages/,components/,styles/,lib/}` |
| Subagent A (input) | `apps/web/src/features/input/**` only |
| Subagent B (results) | `apps/web/src/features/results/**` only |
| WorkBuddy (tests) | `product/tests/web/**` |

Subagents are forbidden from editing `package.json`, lockfile, `src/lib/**`, `src/components/**`, `src/pages/**`, `src/app/**`, `src/styles/**`.

**API dependency:** API service is not present. UI will be built against `docs/02_CONTRACTS.md` only, with an explicit, opt-in dev mock (`npm run dev:mock`). No invented endpoints or field names.

---

## Progress log

### 16:20 — claim + scaffold
`product/` did not exist. Created `product/apps/web` as a standalone Vite app (no root
workspace changes). Design tokens, layout, shared primitives, routing, PWA manifest/SW/icons.

### 16:24 — foundation green
`npx tsc --noEmit` clean, `vite build` clean (66 modules). Icons generated locally by
`scripts/generate-icons.mjs` (raw PNG via `node:zlib`, zero dependencies).

### 16:26–16:32 — subagents
Two subagents dispatched with disjoint folders (`features/input/**`,
`features/results/**`) and an explicit ban on touching `package.json`, the lockfile,
`src/lib/**`, `src/components/**`, `src/pages/**`, `src/styles/**`.

- **Subagent A (input) — completed.** Delivered `IntakeFlow`, `FaceSelect`,
  `ProcessingView`, `input.css`. Reviewed by me: selection is keyed by `face_id`,
  `client_request_id` is minted once per (video, face) so retries are idempotent, polls
  abort on unmount, bboxes are clamped percentages.
- **Subagent B (results) — FAILED to start** (provider 429, usage limit). It left two
  orphaned files behind (`useComparePlayer.ts`, `useIsolatedAudio.ts`) that nothing
  imported; I deleted both and built `features/results/**` myself instead: `ResultView`,
  `ComparePlayer`, `TranscriptPanel`, `useAudioTransport`, `results.css`.

### 16:45–16:55 — integration + verification
- `npx tsc --noEmit` → clean.
- `npm run build` → clean, `dist` 215 kB JS / 18 kB CSS (gzip 70/4.5 kB).
- `npm test` → **50 tests, 6 files, all passing**, stable across 3 consecutive runs.
- `node product/tests/web/smoke.mjs` → **20/20 checks** against the built artefact.

---

## DELIVERED

### Run it
```bash
cd A:/Focus_Ux/product/apps/web
npm install
npm run dev:mock      # UI review without a backend (explicit mock, badge shown)
# or
cp .env.example .env.local   # set VITE_API_BASE_URL, then: npm run dev
```

### Commands and their real results

| Command | Result |
|---|---|
| `npx tsc --noEmit` | exit 0, no output |
| `npm run build` | exit 0 — `index.html` 0.92 kB, CSS 18.35 kB, JS 215.28 kB (gzip 70.20 kB) |
| `npm test` | exit 0 — 6 files / **50 tests** passed (3 runs, identical) |
| `node ../../tests/web/smoke.mjs` | exit 0 — **20/20** checks |

### What was built

| Area | Files |
|---|---|
| Config / PWA | `package.json`, `tsconfig.json`, `vite.config.ts`, `index.html`, `.env.example`, `.env.mock`, `public/manifest.webmanifest`, `public/sw.js`, `public/icons/*.png`, `scripts/generate-icons.mjs` |
| Contract layer | `src/lib/api/{types,client,errors,mock,ApiContext,index}.ts` |
| Session / helpers | `src/lib/{session,localMedia,format,env,useJob,useOnline}.ts` |
| Shared UI | `src/components/{AppShell,Button,Card,Notice,Pill,ProgressBar,Steps,Spinner,Icon,PageHeader,EmptyState}.tsx` |
| Styles | `src/styles/{tokens,base,layout,components}.css` |
| Routes | `src/App.tsx`, `src/main.tsx`, `src/pages/*.tsx` |
| Input feature | `src/features/input/{IntakeFlow,FaceSelect,ProcessingView}.tsx`, `input.css` |
| Results feature | `src/features/results/{ResultView,ComparePlayer,TranscriptPanel}.tsx`, `useAudioTransport.ts`, `results.css` |
| Tests | `src/**/*.test.{ts,tsx}` (6 files), `product/tests/web/smoke.mjs` |

### Contract compliance (docs/02_CONTRACTS.md)

Only these endpoints are called: `POST /videos`, `GET /videos/{id}/faces`, `POST /jobs`,
`GET /jobs/{id}`, `GET /jobs/{id}/audio`, `GET /jobs/{id}/transcript`, `DELETE /videos/{id}`.
No endpoint or field name was invented.

Requirements traced to implementation:

1. Upload with 15 s / 50 MB client pre-checks + preview + change file — `IntakeFlow`.
2. Face chosen by `face_id` from server `bbox`/`timestamp_ms`/`frame_size`; ordering is
   explicitly labelled as not being identity — `FaceSelect`.
3. Upload → candidates → create job → polling per contract — `FaceSelect` + `useJob`.
4. Distinct states: queue position, network retry/backoff, processing failure, no face,
   transcript failure, service unavailable — `ProcessingView`, `ResultView`.
5. Compare player with a single shared playhead, mutually exclusive tracks, pause and
   URL revocation on unmount — `useAudioTransport`, `ComparePlayer`.
6. Audio available even if the transcript fails; transcript has its own status and
   timeline segments — `ResultView`, `TranscriptPanel`.
7. Download via blob URL; delete per contract; token never in a URL/log — `ResultView`,
   `client.ts`.
8. Job restore after refresh via `localStorage`; missing authorization shows an expired
   session instead of another visitor's file — `session.ts`, `ResultPage`.
9. Manifest + local icons + app-shell-only SW + honest offline copy — `public/`, `AppShell`.
10. Mobile + keyboard support, visible focus, labelled controls, no autoplay.

### Decisions worth reviewing (Codex)

1. **`bbox` normalisation.** The contract says "bbox in original-frame pixels" but not the
   shape. The client accepts `{x,y,w,h}`, `{x,y,width,height}` and `[x1,y1,x2,y2]` and
   normalises to `{x,y,width,height}`. If the API fixes one shape, the extra tolerance can
   be deleted. **Please confirm the shape with Dev 2.**
2. **Original track for the A/B compare.** The contract exposes only the isolated WAV, so
   the "original" comes from the uploaded `File` held in memory
   (`src/lib/localMedia.ts`). After a refresh the original is reported unavailable rather
   than faked. If a real A/B after refresh matters, the API needs an original-audio
   endpoint — that is a contract change, not something I should invent.
3. **No progress percentage.** Only status/stage exist, so processing shows an
   indeterminate bar; a determinate bar is used solely for real upload bytes.
4. **Mock isolation.** `VITE_DEV_MOCK_API` is gated on `import.meta.env.DEV`, so a
   production build cannot serve mock audio even if the flag leaks into the environment.
5. **Tests live in `apps/web/src/**`.** Vitest resolves bare imports relative to the
   importing file, so test files under `product/tests/web/` cannot resolve `react`/`vitest`
   without brittle aliases. They stay inside my granted scope. `product/tests/web/` holds
   the built-artefact smoke test instead. Say the word if you want them relocated.

### What is NOT verified

- **No real API exists**, so every network path is exercised only against the mock adapter
  and unit tests. Nothing here proves server behaviour, latency, or error codes in practice.
- **No browser run.** Chrome and Edge are installed but headless launch produced no output
  and no screenshot in this sandbox (process exits 0, writes nothing), so I did not fake a
  screenshot. Rendering is verified through jsdom component tests + the HTTP smoke test.
- **No real video was uploaded end-to-end.** The mock accepts any file; the real 15 s/50 MB
  probe depends on the server.
- **Mobile layout** is written responsive and uses 44 px touch targets, but was not
  visually checked on a device.
- **PWA installability** was checked at the manifest/SW level only, not by installing it.

### Blockers / needs from others

- **Dev 2 / API:** confirm the `bbox` shape and whether an original-audio endpoint will
  exist (needed for an honest A/B compare after refresh).
- **Codex:** confirm the CORS origin and that `Authorization: Bearer` is the only auth
  header, so I can drop the tolerance in `client.ts`.
- **Codex:** the `tests/web` colocation decision above, if you want it changed.

### Next (Day 2, not started)

Recording/realtime is intentionally untouched. When upload is proven against the real API,
the next slice is the capture path behind a feature flag (`DEV3_PWA.md`, Day 2).
