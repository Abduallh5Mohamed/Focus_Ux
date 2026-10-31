# DeepSeek product/integration quality handoff — 2026-10-31

Scope: audited the path isolated WAV -> browser preview -> MP4 export inside the
assigned ownership only. Existing dirty/untracked work was preserved; no
reset/clean/stash/pull/checkout/commit/push, no dependency/weight install, no
service restart, no legacy/A:/focus modification.

## Audited conclusions

- Target-only default is real in the UI and renderer: `VoiceMixPanel` defaults
  `others_level: 0`, `MixSettings` defaults `others_level=0.0`, and
  `render_mix` with `others_level=0` uses only `alignment.voice` (the level
  matched isolated track). No original/residual is added in that mode.
- Preview/export semantics match: the browser sends the current settings
  verbatim (`JSON.stringify(settings)`), the server builds the same
  `MixSettings`, and the export muxes the identical `render_mix` output. Both
  paths use the same alignment/level match and the same noise-filter corners.
- Browser original audio is muted during isolated playback: `<video muted>` is
  true only when `listen === 'mix'`, and the Web Audio master gain is 1 in mix
  mode / 0 in original mode, so the two sources never play together.
- Unreliable residual stays blocked end-to-end: `mix_info` reports
  `others_available=false`, the slider is disabled, the browser forces
  `others_level: 0`, `render_mix` raises `MIX_UNRELIABLE` for a positive
  residual, and `mix_service.start_export` fails fast with 409.
- Level fitting is the loud-frame least-squares fit already added by Codex
  (`_active_gain`); it corrects the +2.8 dB background-bed boost without
  normalising the separated target away. I did not change that logic.
- `mix_service.py` was reviewed and left unchanged: export keeps video stream
  copy, maps the rendered float WAV to AAC at 48 kHz, and uses `-t` to keep the
  probed timeline.

## Files changed by this handoff

- `product/tests/api/test_export.py` (modified)
  - Added decoded-AAC helper and an exact-render comparison for the existing
    stream-copy/timeline test (voice 1.5, residual 0.2, light filter).
  - Added `test_target_only_export_excludes_the_original_residual`: decoded
    export must match the target-only render (NRMSE < 0.06) and must clearly
    differ from the residual-containing render (NRMSE > 0.3).
- `product/tests/api/test_mix_level_fit.py` (modified)
  - Added `test_target_only_render_adds_no_original_audio_where_the_target_is_silent`:
    in target gaps the target-only render is silent (max < 1e-6), while asking
    for `others_level=1` brings the other voice back.
- `product/apps/web/src/lib/env.test.ts` (modified)
  - DEV no-override -> `/api`; DEV explicit override preserved; production
    no-override -> same origin (`''`); production explicit override preserved.
- `product/apps/web/src/__tests__/voice-mix.test.tsx` (modified)
  - Fake AudioContext now tracks the master gain, asserting master=1 in mix
    playback and master=0 in original playback (video muted state asserted
    too).
  - Added a test that export sends `others_level: 0` when the server marks the
    residual unreliable.

Preserved without edits: `product/apps/web/src/lib/env.ts`,
`product/apps/web/src/features/results/VoiceMixPanel.tsx`,
`product/services/api/focus_api/mix.py` (Codex's `_active_gain`),
`product/services/api/focus_api/mix_service.py`.

## Commands and observed results

Interpreter/PATH/PYTHONPATH as instructed (process only):
`A:/Focus_runtime/venvs/analysis-venv/env/Scripts/python.exe`,
`PATH=A:/Focus_Ux/runtime/audit_20261030/bin`,
`PYTHONPATH=product;product/packages/ml`.

- `pytest product/tests/api/test_mix_level_fit.py product/tests/api/test_export.py product/tests/api/test_mix_math.py -q`
  -> **21 passed**, 1 warning (Starlette `httpx` deprecation).
- `pytest product/tests/api -q` -> **247 passed, 1 skipped**, 1 warning, 159.55 s.
- `npx vitest run src/lib/env.test.ts src/__tests__/voice-mix.test.tsx`
  -> **11 passed**.
- `npx vitest run` (full web suite) -> **11 files, 105 passed**, 19.95 s.
- `npm run typecheck` (`tsc --noEmit`) -> exit 0.

AAC tolerance basis (clean synthetic 2 s speech-band source, testsrc video,
AAC 160k): decoded-vs-source best lag 0 samples, correlation 0.99959, NRMSE
0.0289 at lag 0 and ~0.017 after skipping 50 ms. The test therefore uses
NRMSE < 0.06.

## Read-only GPU diagnosis (nothing installed)

- `A:/Focus_runtime/cv-venv/env`: Python 3.13.14, `torch 2.15.0+cpu`,
  `torch.version.cuda=None`, `torch.cuda.is_available()=False`,
  `device_count=0`. Confirms the known CPU-only state.
- `A:/Focus_runtime/venvs/analysis-venv/env`: no `torch` installed.
- `A:/Focus_runtime/venvs/cv-gpu312`: Python 3.12 uv venv, no `torch` installed.
- `A:/Focus_runtime/venvs/demucs-venv/env`: `torch 2.15.0+cpu`, CUDA unavailable.
- GPU present: NVIDIA GeForce RTX 3060 Laptop, driver 617.42, 6144 MiB.
- Read-only observation: legacy `A:/focus/.venv` (Python 3.12.15) has
  `torch 2.8.0+cu126`, `torch.version.cuda=12.6`, `cuda.is_available()=True`.
  It was not used or modified; it only shows the driver/CUDA runtime is viable.

### Proposed GPU environment plan (NOT executed)

1. Get explicit approval to create a separate product-local GPU venv, e.g.
   `D:/Focus_runtime/venvs/cv-cu126` (never inside `A:/focus` and never the
   existing `cv-venv`).
2. Base it on Python 3.12 to match the verified legacy CUDA wheel
   (`torch 2.8.0+cu126`) and reuse the existing wheel/pip cache; no new weight
   downloads.
3. Verify in isolation, before any real run:
   `torch.__version__`, `torch.version.cuda`, `torch.cuda.is_available()`,
   `torch.cuda.get_device_name(0)`.
4. Reuse the existing ClearerVoice checkpoints/cache under
   `A:/Focus_runtime/clearervoice` read-only, then run one short (about 6 s)
   real inference and record wall time separately from model progress time.
5. Keep `cv-venv`, the legacy venv and global packages untouched; remove the
   new venv if the compatibility check fails.

## Remaining blockers / truth limits

1. **Server API default still adds residual when the body omits the field**
   (`product/services/api/focus_api/service.py:441`,
   `payload.get("others_level", 0.25)`). This file is outside my exclusive
   ownership. The web client always sends an explicit `others_level`, so the
   product UI is target-only, but a direct `POST /exports` with `{}` still gets
   0.25. Recommend the owned services/api writer change the default to `0.0`
   and add a regression test.
2. `gain_clamped` is computed in `mix.py` but not exposed in `mix_info` because
   `service.py` is outside ownership; a clamped level fit is currently invisible
   to the UI/API.
3. No browser end-to-end journey and no service restart were performed (per
   instructions). Tests and typecheck only.
4. No real GPU inference was run in this session. No quality, SI-SDR,
   real-time or Egyptian-Arabic claim is made.
5. Existing evidence stands as previously documented: speech-vs-gap dB is not
   SI-SDR, and removing the 25 % residual did not improve SI-SDR on the strong
   target (19.44 dB -> 19.18 dB). Target-only default is a semantic correction,
   not a universal numerical improvement.
6. Pre-existing, not modified: `MixService.start_export` publishes the export
   record before assigning its future; a cancel/delete arriving in that tiny
   window would not wait on the render. Not reproduced, flagged only.

## Codex review follow-up — read-only ML voice review (2026-10-31)

Scope: read-only review of GLM's `voice/separation.py`, `voice/engine.py` and
`tests/voice/test_separation_identity.py`. I edited no ML or test file, ran no
installs/downloads, read no secrets, and did not touch the GPU environment.
GLM was writing concurrently, so this is a snapshot at approximately 04:57-04:58.

Transient defects actually observed during the review (now fixed by GLM):
- `_chunks()` used `r.duration` on `LabelledRegion` (no such attribute), which
  raised `AttributeError` on the engine path; it now uses `r.end - r.start`
  (`separation.py:248`).
- The test helper called `separator_cls(*stems)` while `FakeSeparator.__init__`
  expects one list, so every helper-based test failed with `TypeError`; it now
  calls `separator_cls(list(stems))` (`test_separation_identity.py:139`).
- `test_no_target_region_refuses` originally passed `FUSED_REGIONS` (which has a
  TARGET span) and therefore could not raise; it now uses only an UNCERTAIN
  overlap plus an OTHER span.

`separation.py` was edited again at 04:59:08 (maps an
`embed_segments` `None` result to a `None` similarity; no other change to the
points below). Final observed run after that edit:
`pytest product/tests/voice/test_separation_identity.py -q` -> **19 passed**,
0.67 s. This is a fake-backed semantics suite, not model-quality evidence, and
line numbers below refer to the 04:59:08 revision. GLM was still writing when I
stopped, so re-check before acting on any item.

### High

1. **Full overlap is still marked TARGET in the test (real pipeline would
   refuse).** `test_fully_overlapping_timing_chooses_the_embedded_source`
   (`test_separation_identity.py:178-188`) feeds a synthetic
   `LabelledRegion(0, 4, TARGET, ...)` for a fully overlapping scene. Real
   `classify_regions` emits diarization overlaps as `UNCERTAIN` with
   `reason="overlap"` and only labels non-overlap solo spans
   (`match.py:78-86`). A wholly overlapping clip therefore has **no TARGET
   region**, and `_identity_choice` refuses at `separation.py:273`
   ("no confirmed target speech"). The test proves identity selection when a
   TARGET region is supplied; it does **not** prove full-overlap isolation.
   Rename/label it as synthetic and add a `classify_regions -> extract`
   regression asserting refusal when the only regions are overlap.
   The same caveat applies to the wrong/uncertain/too-short/embedder-mismatch
   tests: they use `overlap_scene()` audio with hand-written TARGET regions.
   They are valid selector unit tests, but must not be read as pipeline
   acceptance.

2. **No finite/nonzero *similarity* guard.** `_reliable_windows` filters
   non-finite audio, but `_unit` only rejects norm == 0
   (`embedder.py:32-37`). A NaN/Inf embedding propagates into `cosine`, and
   every refusal comparison (`best < other`, `best < target`,
   `best - second < margin`) is False for NaN (`separation.py:300-318`). That
   can select a NaN-scored stem instead of refusing. Zero-norm embeddings raise
   a raw `ValueError` rather than `ProcessingError`. No test injects
   NaN/Inf/zero embeddings.

3. **Embedder is not released on refusal.** In `AudioOnlyEngine.isolate`, the
   `self._release("embedder")` after `extract` is only reached on success
   (`engine.py:206-217`). An identity refusal or separator failure raises past
   it, leaving the model loaded (VRAM leak across repeated failures). The test
   suite asserts unload only on the success path (`test:390`).

### Medium

4. **Embedder exceptions are unwrapped.** `embed_segments` calls at
   `separation.py:293` and `:363` (and `set_context` / `Voiceprint.from_dict` at
   `:206`) are not wrapped in `ProcessingError`. A real embedder
   `ValueError`/`RuntimeError` escapes as a generic exception; only separator
   failures are tested (`test:269-281`).
5. **Mutable context persists across jobs.** `_context` and `last_identity`
   (`separation.py:184-185, 199-207`) are per-instance and never cleared.
   `extract` without a fresh `set_context` reuses the previous voiceprint/config
   (and `params()` still reports `enrollment_embedding`) after the engine may
   have unloaded that embedder. Concurrent jobs sharing an extractor race. No
   sequential/different-voiceprint or no-context test.
6. **Window cost is unbounded and untested.** One embedding per target chunk per
   stem (`:275-276, 293`) plus one per overlap chunk (`:363`); no batching, cap
   or dedupe, and `_chunks` plus `embed_segments` both slice/re-chunk. Long,
   overlap-heavy clips can make many model calls; no cost/timing test.
7. **Overlap gating ignores the competitor margin.** `_overlap_spans` keeps a
   chunk when `score >= cfg.target_threshold` (`:363-366`) without checking it
   against the other stem. "Discard uncertainty" does not cover "ambiguous vs
   the other source". Combined with `target_mask` bridging (`bridge_ms=250`), a
   muted overlap chunk next to a kept one may be partly bridged back; untested.

### Low

8. `best_idx = sims.index(best) if best in sims else -1` (`:302`) would silently
   select `stems[-1]` at `:325` if `best` is ever absent from `sims`; it should
   refuse.
9. `details["target_index"]` is set before the threshold/margin checks (`:303`),
   so `last_identity` on a refusal still reports a candidate index.
10. `identity_margin` is unvalidated and unreported (`:183, 297-299`): a
    negative or over-large override silently changes policy, and `params()`
    omits it.
11. When only one stem has usable windows, the margin check is skipped
    (`second is None`, `:301/318`). Intentional, but a lone surviving source is
    never cross-checked.
12. The module docstring (`:33-38`) implies overlap regions are kept in
    enrollment mode without stating that at least one TARGET solo region is
    required first; only timing mode is called out as unable to recover full
    overlap.
13. `test_overlap_muted_when_the_stem_does_not_continue_there`
    (`test:306-321`) uses non-overlapping A(0-2)/B(2-4) audio but labels 2-3 s
    as `reason="overlap"`; it exercises the mute path, not overlap
    classification.

### Suggested GLM fixes (not applied by me)

- Add a `classify_regions -> extract` full-overlap test that asserts the
  "no confirmed target speech" refusal, and rename/label the synthetic
  all-span-TARGET test.
- Treat non-finite similarities as `None`/refusal and test NaN/Inf/zero
  embeddings; map zero vectors to `ProcessingError`.
- Wrap embedder calls and test that an embedder failure never falls back.
- Clear per-job context (or pass it into `extract`) and test two sequential
  jobs with different voiceprints plus `params()`.
- Use `try/finally` around `extract` to release the embedder on refusals; test
  unload on failure.
- Cap/batch embeddings (or add a cost guard) and either apply the competitor
  check to overlap chunks or document single-threshold gating.
- Guard `best_idx < 0`, set `target_index` only on acceptance, and
  validate/report `identity_margin`.

No quality, SI-SDR, full-overlap-recovery, or real-model validation claim is
made from these fake-backed tests.
