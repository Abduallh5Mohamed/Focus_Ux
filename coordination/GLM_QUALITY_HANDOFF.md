# GLM quality task handoff — enrollment-embedding separation selection

Date: 2026-10-31. Executor: GLM ML agent (opencode/glm-5.3-flash-free), supervised per
`A:/FocusLocalTrialReports/OPENCODE_GLM_QUALITY_TASK.md` and
`coordination/CODEX_QUALITY_AUDIT_2026-10-31.md`.

Scope respected: only `product/packages/ml/focus_ml/voice/separation.py`,
`product/packages/ml/focus_ml/voice/engine.py`,
`product/tests/voice/test_speech_separation.py` (NOT modified), a new narrowly
scoped identity test file, and this handoff. All pre-existing dirty/untracked
work left untouched; no git operations, no installs, no downloads, no runs
inside `A:/focus` or its venv/cache/weights.

## What was implemented

### 1. Extraction hook and enrollment-embedding selection (`voice/separation.py`)

- `SpeechSeparationBaseline.set_context(voiceprint, embedder, match)` — the
  hook called by `AudioOnlyEngine.isolate` after the match stage. `match`
  defaults to the thresholds registered for the embedder's name. Without
  context the extractor keeps the previous timing-contrast behaviour exactly.
- `extract(samples, regions)` keeps the `Extractor` protocol signature. With
  context it now:
  - chunks the TARGET (voice_match) regions at `MatchConfig.max_chunk_s` and
    embeds each stem over the windows that are long enough
    (`min_region_s`), finite and non-silent (`_reliable_windows`);
  - computes cosine similarity of each stem embedding against the enrollment
    voiceprint using `focus_ml.voice.match.cosine`;
  - selects a stem only if it clears `target_threshold` AND beats the second
    best similarity by a margin (default: `target_threshold -
    other_threshold` from the existing match policy; configurable via
    `identity_margin`). No new calibration was invented;
  - refuses (non-retryable `ProcessingError`) with distinct reasons:
    `embedder_mismatch`, `no_target_region`, `no_usable_windows` (too
    short/silent/non-finite), `no_match` (best <= `other_threshold`),
    `uncertain_identity` (best between the thresholds), `ambiguous`
    (margin not met). A refusal never falls back to the masked mixture or to
    another stem chosen by order;
  - keeps the source order unpermuted (whole-file model, no streaming claim);
  - overlap handling is evidence-gated per chunk: an overlap chunk of the
    CHOSEN stem is kept only when that chunk still matches the enrollment
    (`>= target_threshold`); chunks that are too short, silent/non-finite, or
    uncertain/mismatched are muted. Uncertain identity is never given to the
    target. Kept spans are merged into the gate via the existing
    `target_mask` (bridge 250 ms, fade inside edges).
- Explicit stem-count and stem-length guards (`fewer than two sources`,
  `wrong length`); separator failures still propagate and never degrade to a
  mask.
- Metadata: `SpeechSeparationBaseline.last_identity` records `selection`
  (`enrollment_embedding` / `timing_contrast`), `embedder`, per-stem
  `similarities`, `stem_windows`, `required_margin`, `target_index`,
  `refusal`, `warnings` (per chunk-mute reason) and `overlap` stats
  (`kept` spans, `kept_s`, `muted_s`, `unmeasured_s`). `params()` reports the
  active selection mode (`enrollment_embedding` when context is set,
  `timing_contrast` fallback otherwise, `overlap_policy` `evidence_gated` /
  `muted`) and keeps `other_source_added: false`.
- The legacy timing path keeps its existing refusal semantics (no TARGET
  regions or < 1 dB contrast spread) and is now reported as
  `selection: timing_contrast` with scores.

### 2. Engine wiring and embedder release (`voice/engine.py`, `isolate` only)

- `isolate` detects `hasattr(self.extractor, "set_context")`; if present it
  defers `self._release("embedder")` until AFTER extraction so the identity
  use inside `extract` is the final one, then releases. Mask extractors keep
  the earlier release exactly as before.
- `EngineResult.details` gains `"identity"`: the extractor's `last_identity`,
  or exactly `None` for extractors that make no identity claim (masks).
- Overlap warnings are surfaced in `EngineResult.warnings`, and when overlap
  was kept a warning states clearly that the overlap handling is provisional
  and has NOT been validated on real recordings.

### 3. `voice/extractor.py`, music/mask extractors, web/API/tools

Untouched (not in my ownership); `build_extractor` wiring for `ducked`,
`gated`, `music`, `separation` is unchanged.

## Tests (new file `product/tests/voice/test_separation_identity.py`, 19 tests)

Deterministic fakes only, clearly marked as test doubles: `FakeSeparator`
returns fixed stems; `FakeEmbedder` maps a window to the one-hot vector of its
dominant FFT bin (separable by construction); `FixedEmbedder` is
identity-blind for tie/ambiguity cases; `ShortSeparator` breaks stem length.
Nothing in these tests is real-model quality evidence.

Coverage:
- reversed source order (B first) selects stem A by embedding; other stem
  never re-added in gaps;
- fully overlapping timing (one all-span TARGET region, zero timing
  contrast) chooses the correct source by enrollment embedding in both
  orders;
- refusals: ambiguity (identical similarities, margin not met, order-faithful
  first-stem refusal prevented), wrong identity (`no_match`), uncertain band
  identity, too-short target speech, silent/non-finite stems (all-dead
  refuses; exactly-one-alive selects it and reports `None` similarity for the
  dead stem), embedder/voiceprint mismatch, wrong-length stems, separator
  failure (no mask fallback), no-TARGET-region refusal;
- overlap: kept only where the chosen stem still matches the enrollment;
  muted (with warning + `unmeasured_s`) when the stem is silent there;
  muted when the chunk reads as the other speaker;
- engine integration via `AudioOnlyEngine.isolate` with fake diarizer:
  identity metadata in details, target-only output check, embedder released
  exactly once AFTER the final identity use (asserted by counting embeds
  after unload = 0); engine-level ambiguous refusal keeps
  `last_identity.refusal`; mask extractor reports `identity: None`;
- params reports the active selection mode.

Untouched `product/tests/voice/test_speech_separation.py` (7 tests) still
passes unchanged (legacy timing path preserved).

## Commands and observed results (exact)

Interpreter: `A:/Focus_runtime/venvs/analysis-venv/env/Scripts/python.exe`,
`PYTHONPATH=product;product/packages/ml`, PowerShell from the worktree root.

- `python -m pytest product/tests/voice/test_separation_identity.py
  product/tests/voice/test_speech_separation.py -q` → **26 passed**, exit 0.
- `python -m pytest product/tests/voice -q` (full voice suite, engine and
  other extractors included) → **78 passed, 2 skipped**, exit 0. The 2 skips
  are pre-existing environment skips (`test_audio_engine.py:160`,
  `test_voice.py:170`, both "ffmpeg required"), not related to this change.
- No model executions were run in this session (task instruction: no model
  executions needed while implementation/tests are under review). The real
  MossFormer2_SS_16K + ECAPA/pyannote path therefore has NOT been exercised
  through the new identity selection; this is explicitly NOT validated
  against real weights, real speaking styles of the enrolled speaker, or any
  quality metric. No quality / realtime / manufacturing claims.

## Design notes and limits

- Threshold policy reuses `MatchConfig` thresholds in force at match time;
  `required_margin` defaults to the target/other threshold gap, override
  available via constructor. No recomputed or invented calibration.
- Selection windows come from the match's TARGET regions, i.e. solo,
  voice-print-confirmed speech. If a job has no such region, separation now
  fails fast with explicit wording instead of guessing.
- Overlap feasibility depends on the real separator's stem containing the
  target's voice during turns-with-overlap; provisional by design and marked
  as such in metadata and warnings.
- Known open item for review: on real audio with the real embedder the whole
  selection needs re-verification (margin behaviour with real-garbage stem
  embeddings can differ from the semantically clean fakes). Integrated GT
  tests (balanced two-source, and multi-side three-source) remain owner
  acceptance gates from the audit; the model is still a TWO-source separator.
