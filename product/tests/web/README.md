# Web tests

Owned by WorkBuddy.

## Layout

Unit and component tests are **colocated with the source** in
`product/apps/web/src/**/*.test.{ts,tsx}` and run with `npm test` inside `apps/web`.

They live there because Vitest resolves bare package imports relative to the importing
file; test files outside `apps/web` cannot resolve `react`/`vitest` without brittle alias
hacks. They are still inside WorkBuddy's granted scope (`product/apps/web/**`).

This folder holds the checks that operate on the **built artefact** instead of the source.

## smoke.mjs

```bash
cd product/apps/web && npm run build
node ../../tests/web/smoke.mjs
```

Boots `vite preview` on port 4188 and asserts, against the real HTTP responses:

- the shell returns 200 and mounts `#root`
- `index.html` has no third-party asset URLs (the app must work from local files)
- the manifest is valid, `standalone`, `lang=ar`/`dir=rtl`, `start_url=/`
- every manifest icon is a real PNG at the declared size, served from `/icons/`
- a maskable icon exists
- `sw.js` is served and refuses to cache authorized requests, `/api/`, and audio/video
- a deep link (`/job/abc/result`) still serves the shell

Exit code 0 means all checks passed. 20 checks at the time of writing.

## browser/ — real Chrome QA (Round 2)

`apps/web/scripts/browser/run-qa.mjs` drives the **real** system Chrome via
`puppeteer-core` (installed `--no-save`) against a running dev server. It is not part of
the bundle and is not run by `npm test`.

```bash
cd product/apps/web
npx vite --mode mock --port 5174 --strictPort      # terminal 1 (mock)
node scripts/browser/run-qa.mjs http://localhost:5174   # terminal 2
```

It walks home → upload → face select → processing → result → refresh at 1280/390/320,
writes screenshots to `tests/web/browser/artifacts/`, and records console/page/request
failures, the keyboard focus sequence, and horizontal-overflow offenders in `summary.json`.
`blob:… ERR_ABORTED` entries are expected (audio element aborting a revoked blob URL).

`apps/web/scripts/browser/run-real-api.mjs` does the same upload path with **mock OFF**
against a real API (`VITE_API_BASE_URL=…`), to confirm the UI actually talks to the server.

## Unit tests (in apps/web)

| File | Covers |
|---|---|
| `src/lib/api/__tests__/client.test.ts` | URL joining, bbox normalisation, error mapping (401/413/429/409/network/204), token in header not URL, blob fetch |
| `src/lib/__tests__/session.test.ts` | patch-merge, clearJob vs clearSession, corrupted storage |
| `src/lib/__tests__/format.test.ts` | clocks, durations, byte sizes, clamping |
| `src/__tests__/app.test.tsx` | routing, step rail, skip link, not-found |
| `src/__tests__/intake-flow.test.tsx` | size/MIME rejection before upload, face selection by `face_id` (not index), disabled confirm |
| `src/__tests__/results-flow.test.tsx` | single audio element, isolated track availability, download gating, transcript segments, two-step delete |
