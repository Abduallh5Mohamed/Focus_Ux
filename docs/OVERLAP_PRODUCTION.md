# Real overlap extraction in the production audio-only path

**Status: routing, continuity fallback, preflight and Windows scripts are delivered and unit-tested with tone
fakes. No real model has been run. Nothing was measured on a GPU. The extractor is OFF by default and must stay
off until the steps below pass on the RTX 3050.**

## What was found (this Replit workspace)
No NVIDIA GPU (`nvidia-smi` absent), no PyTorch, no model checkpoints anywhere on disk, and no route to the
laptop. The preflight run here reports exactly that (`NOT ready: pytorch, gpu_model, free_vram, pytorch_gpu_compat,
dependencies, checkpoint`). The Windows worker may or may not be able to run the model; that is unknown until
`Overlap-Preflight.cmd` is run on it.

## Real GPU validation status (WeSep BSRNN, RTX 3050)
| Part | Status |
|---|---|
| A. Preparation (run kit) | **Done: preparation only, not a validation result** |
| B. Real one-mixture GPU run | **Not run** |
| C. End-to-end FOCUS run (pyannote + enrollment + WeSep) | **Not run** (requires B to succeed first) |

### Part A, preparation (what exists now)
Reviewed and reused unchanged: the WeSep adapter and checkpoint config (`overlap/candidates.py`, `overlap/weights.py`),
`overlap/preflight.py`, `tools/overlap_minimal_infer.py`, `HybridExtractor` and the routing. No blocker to real
execution was found in them by reading and by the tone-fake tests (they cannot show real-weights behaviour).
Added: `product\tools\Overlap-Validate.cmd` (preflight, then one-mixture GPU test, then the end-to-end test, stopping at the first
failure) and `product\tools\overlap_e2e.py` (real pyannote diarization, `enroll_file` on the separate enrollment clip, and
`AudioOnlyEngine.isolate` with the extractor enabled by an explicit constructor argument, in strict and continuity modes;
the global default and environment are untouched). Added one test: a blocked extractor in continuity mode uses the
reduced-volume fallback and reports `fallback_used=true`, `isolation_claim="not_isolation"` and the notice (the existing
strict test already covers the muted fallback). Verified by the unit suite (56 overlap tests pass), not on real models.

### Part B, real GPU run: NOT RUN
This Replit workspace has no NVIDIA GPU, no PyTorch, no checkpoints and no route to the laptop, so nothing was
measured. No GPU time, peak VRAM or SI-SDRi exists. No CPU experiment was repeated.
On the laptop (after `Setup-Overlap.cmd`, approving the download):

    product\tools\Overlap-Validate.cmd target_enroll.wav two_speakers_5to10s.wav meeting_with_overlap.wav

Expected files in `validation-out\`: `preflight\preflight.json`; `minimal\mixture.wav`, `enrollment.wav`,
`extracted_target.wav`, `gpu_log.txt`, `report.json` (inference seconds, peak VRAM MiB, silent %, cosine to enrollment).
SI-SDRi needs clean ground truth: build the mixture from two clean recordings, or run `overlap_acceptance.py` (it sums
clean files and reports SI-SDRi). Listen to `extracted_target.wav` before continuing.

### Part C, end-to-end run: NOT RUN
Same script, third step. Expected: `e2e\diarization.json`, `enrollment.json`, `strict\isolated.wav`,
`continuity\isolated.wav`, `e2e_report.json`. Pass criteria in the report: `overlap_extraction == "ran"` with
`windows > 0` and overlap seconds > 0 in `routing.hybrid` (proof that overlap went to WeSep rather than being muted),
pieces with `status: extracted`; any piece muted shows its reason. If extraction fails the report shows
`overlap_extraction: "failed"` plus the error, and in continuity mode `fallback_used: true`, `isolation_claim: "not_isolation"`.

### Verdict
`FOCUS_OVERLAP_EXTRACTOR` **must NOT be enabled**: no real run has happened. Enable only after B and C are Done
and the output was listened to. It stays unset (disabled) as the global default.
Unresolved regardless of results: the WeSep checkpoint has no explicit licence (commercial use), one mixture is not
an acceptance test, and the extractor stays resident in VRAM after first use.

### Next steps
1. Run `Overlap-Validate.cmd` on the RTX 3050 and return `validation-out\`.
2. Record GPU seconds, peak VRAM and SI-SDRi here; mark B and C Done or Failed.
3. Run `overlap_acceptance.py` cases A-D, then decide on enabling; resolve the checkpoint licence.

## Routing (`focus_ml/voice/routing.py`, wired in `voice/engine.py`)
| Region | Strict (default) | Continuity (opt-in) |
|---|---|---|
| target alone | original audio | original audio |
| other alone | muted | original mix at reduced volume |
| overlap | real extractor if enabled, verified; else muted | extractor if enabled; unverified parts at reduced volume |
| uncertain / unmatched | muted | reduced volume |

* The extractor is the existing `overlap.HybridExtractor` (reused, not rewritten): short overlaps get one full
  window centred on the region with real neighbouring audio as context; long ones get overlapping windows with
  sin² crossfades; every extracted piece is checked by voiceprint similarity and non-silence (failures stay
  muted); output is fitted to the exact input length (sample-aligned). The model loads once per engine
  (`OverlapExtractor.load` is idempotent) and each window is run once per `isolate` call.
* The clean enrollment audio is the reference: an explicit `enrollment_audio_path`, else the clean spans the
  voiceprint was made from. A voiceprint from a separate recording without that audio cannot feed a
  target-conditioned model; overlap extraction is then `skipped` and reported, never silent.
* If the extractor is blocked (missing weights, out of memory) the result falls back to the gate and says so in
  `details["routing"]["overlap_extraction"] == "failed"` with the blocker.
* Continuity: gain `FOCUS_CONTINUITY_GAIN_DB` (default -18, must be negative), 30 ms raised-cosine transitions,
  output scaled so it never exceeds 0.98. `details["routing"]` carries `fallback_used`, `fallback_seconds` and
  `isolation_claim` (`"not_isolation"` when the fallback was used). The warning text is
  "…this is not speaker isolation." Continuity is never described as isolation.
* Models that are blind separators are labelled `blind_separation_then_voiceprint_selection`
  ("separation-then-selection"), never voice-conditioned.

## How to enable (only after validation)
    FOCUS_OVERLAP_EXTRACTOR=wesep_bsrnn      # unset = disabled (default)
    FOCUS_ISOLATION_MODE=strict|continuity   # default strict
    FOCUS_CONTINUITY_GAIN_DB=-18
Weights: `product\tools\Setup-Overlap.cmd` (asks for approval first; the original environment is untouched).

## Validation procedure on the Windows RTX 3050
1. `product\tools\Overlap-Preflight.cmd` → CUDA, GPU model, free VRAM (needs ≥ 2500 MiB), PyTorch CUDA build and
   GPU compatibility, packages, checkpoint. Saves `preflight-out\preflight.json`.
2. Minimal real inference (one model, one enrollment, one 5–10 s two-speaker mixture):
   `product\tools\Overlap-Preflight.cmd --enrollment target_enroll.wav --mixture two_speakers.wav --out minimal-out`
   Saves `mixture.wav`, `enrollment.wav`, `extracted_target.wav`, `gpu_log.txt` (nvidia-smi before/after),
   `report.json` (load/inference seconds, peak VRAM, silent %, cosine to enrollment). Listen to it.
3. Only if step 2 is good: `python product\tools\overlap_acceptance.py --candidate wesep_bsrnn --enrollment
   target_enroll.wav --target target_clean.wav --other o1.wav --other o2.wav --out acceptance-out`
   Cases A target alone, B other alone, C target + one, D target + two (only when the model declares 3+ speakers).
   Per case: target retention, leakage, SI-SDRi, silent %, time, peak VRAM, sync lag; WAVs for mixture, strict
   final, continuity. Regions are oracle, isolating the extractor; end-to-end diarization is separate.

## Model candidate for the first run
WeSep BSRNN (REAL-TSE fork @ 2a54097) — the only genuinely target-conditioned candidate whose code is pinned.
Code licence stated as Apache-2.0 (no LICENSE file found at the repo root); **checkpoint has no explicit licence**
and is only on Google Drive, so commercial use is unresolved. Not measured. Blind alternatives exist
(separation-then-selection) and are in `overlap/candidates.py`.

## Measured results
Cases A–D: **not run.** GPU logs, peak VRAM, SI-SDRi, retention, leakage, silent %, sync: **not run.**
Input mixture / enrollment / extracted target / final mixed WAV: **not produced** (no model was run).
The only measured number in the task, ~41.7% digital silence of the gated output, is from the earlier diagnosis.

## Regression tests (tone fakes, no weights)
`tests/overlap/test_overlap_routing.py` (default-disabled equals gated baseline, strict routing, continuity
volume/smoothness/no clipping/fallback flag, blocked-extractor reporting, engine wiring, single inference,
preflight, metric definitions and sync). Existing overlap/voice/worker suites still pass (43/38/38).

## Files changed
New: `voice/routing.py`, `overlap/preflight.py`, `overlap/acceptance.py`, `tools/overlap_minimal_infer.py`,
`tools/overlap_acceptance.py`, `tools/Overlap-Preflight.cmd`, `tests/overlap/test_overlap_routing.py`,
this document. Edited: `voice/engine.py` (routing hook, optional `enrollment_audio_path`, `details["routing"]`).
Not touched: Task #83 code, checkpoints, results.

## Known limitations
No real inference yet; checkpoint licence unclear; continuity mode lets other voices be heard; hybrid verification
uses the same embedder as matching; the extractor stays resident after first use (free VRAM before diarizing
another file); acceptance regions are oracle; audio/video sync is checked as sample alignment only.

## Is production integration safe?
Yes to merge as dormant code: with nothing set, output is identical to the previous gate (tested). **No** to
enabling the extractor: it is unvalidated. Continuity mode can be used now if the product wording says it plays the
original mix quietly and is not isolation.
