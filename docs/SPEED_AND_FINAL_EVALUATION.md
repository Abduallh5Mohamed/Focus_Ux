# Speed tuning and final evaluation (phase 4)

**Status: tooling complete and tested with tone fakes; NO measurement exists on the ASUS TUF RTX 3050 laptop yet.**
No speed or VRAM target counts as met until `profile.json` / `report.json` from that laptop say
`measured_on_target_laptop: true`. This workspace has no GPU, no model weights and no Egyptian recordings.

## 1. Profile (laptop command)
```
product\tools\Profile-Speed.cmd clip1min.wav clip3min.wav clip10min.wav
python product/tools/profile_pipeline.py --make-long clip3min.wav --seconds 600 --out clip10min.wav   # repeat-of-real-clip load test
```
`profile.json` has, per clip: seconds, CPU seconds, cores busy, peak RAM, GPU utilisation, peak VRAM per stage
(decode, diarize, speaker_embeddings, enroll, match, extract), the real-time factor, and an `idle` label per
stage (`gpu_idle_waiting_for_cpu`, `cpu_idle_waiting_for_gpu`, `both_busy`, ...). GPU utilisation needs `nvidia-smi`;
RAM needs `psutil` or `/proc` or Windows `GetProcessMemoryInfo`. A reading that cannot be taken is `null`, never 0.
`--warmup` runs the first clip once so model loading is not in the timing. A 10-minute clip made with `--make-long`
repeats real speech; say so when reporting.

## 2. Optimisations (each is gated before it is kept)
Measure one change at a time; the gate is `focus_eval.gate` (quality must hold on every target AND the per-clip
RTF must be <= 0.8 and faster than the baseline):
```
python product/tools/speed_tune.py --dataset product/datasets/egyptian_eval --out reports/tune_prefetch \
    --baseline "{\"prefetch\": false}" --candidate "{\"prefetch\": true}"
```
Run it a second time with baseline and candidate swapped to expose warm-up / thermal bias. Clips with overlapping
speech are dropped from tuning by default: the gated baseline mutes overlap on purpose and the strict adoption
policy (no silence where the target speaks) would reject every such clip, so they cannot judge a speed change.

| Optimisation | State | Evidence |
|---|---|---|
| No repeated audio decoding (`load_canonical` cache, content-signature key, read-only shared array) | **Implemented, on.** Quality-neutral by construction (identical samples). | Test: one decode serves analyze + both targets. CPU (Replit) micro-measurement, 3 reads of the same file: 60 s clip 0.61 s -> 0.20 s; 180 s 0.80 -> 0.27 s; 600 s 1.78 -> 0.58 s. Not a laptop number. |
| CPU work overlapped with GPU work (`prefetch_decoded`: next clip decoded on a CPU thread during the current clip's GPU stages) | **Implemented, setting `prefetch`.** Used by the evaluation runner and the profiler. | Ordering/equality tested. Gain on the laptop **not measured**. Face detection is not part of the audio-only path; VAD is part of the diarizer model, so there is no separate CPU stage to overlap. |
| Models resident vs unloaded by measured VRAM (`ResidencyPolicy`, `plan_residency`) | **Implemented, default = unload all (the validated behaviour).** `keep_resident` only changes from a plan built out of measured per-model peaks; a model without a measurement is never kept. | Policy logic tested. Peak VRAM per model **not measured**, so nothing is kept resident yet. |
| Batched overlap windows | **Already present in the overlap hybrid scheduler; not used by the default engine** (the gated baseline mutes overlap, no overlap extractor was adopted). | No change; nothing to measure until an overlap extractor is chosen. |
| Tuned chunk sizes (`match_max_chunk_s`, default 3.0 s) | **Setting exposed to the tuner; default unchanged.** | Changing it changes matching resolution, so it must pass the quality gate. **Not measured.** |

Nothing was switched on from a speed claim. Adoption decisions are produced by `speed_tune.py` on the laptop.

## 3. Longer videos
Rule: a length is supported only if a run of that length (on the laptop) finished with RTF <= target and VRAM within
90 % of the card; the first failing length ends the range, nothing is extrapolated (`supported_audio_seconds`). Every attempted clip counts, including failed ones (their length is recorded before the run), so a failed short clip blocks longer clips that happen to succeed. The RTF used is end-to-end wall time divided by audio length (`wall_seconds`); the sum of stage times is kept only as `stage_sum_seconds` for diagnosis because stages can overlap or leave gaps. A clip of unknown length, or no clips, gives `supported_audio_s: null` with `not_installable_reason`, which the API refuses to load (the 180 s default stays).
`profile_pipeline.py --limits-out speed_limits.json` writes the measured limit with device and date. A run that is not on the RTX 3050 or has no VRAM readings writes `supported_audio_s: null`, and the API refuses to load a file not marked `measured_on_target_laptop` (a missing VRAM reading also fails the VRAM budget). Point the API
at it with `FOCUS_API_SPEED_LIMITS=<file>`; a missing or unmeasured file stops startup (no silent fallback).
Uploads longer than the limit are refused with: `video exceeds the Ns limit (<source>)` where the source is either
the measured device/date, `a limit set by the operator` (`FOCUS_API_MAX_VIDEO_MS`), or
`the default limit; it has not been measured on the demo laptop` (today's state: 180 s).
A measured limit above 180 s also needs `FOCUS_API_MAX_UPLOAD_MB`, the worker's `FOCUS_WORKER_MAX_MEDIA_MB`
(250 MB) and `FOCUS_WORKER_MAX_OUTPUT_MB` (8 MB; a 10-minute WAV is about 19 MB) raised together.
**Whether a 10-minute clip completes is unknown until measured.**

## 4. Final evaluation (one command)
```
product\tools\Final-Evaluation.cmd              # or: python product/tools/final_eval.py --dataset ... --out reports/final
    [--settings settings.json] [--stress noise_10db,reverb_rt60_0.4s] [--skip-visibility] [--listening-seed 7]
```
Writes `reports/final/{report.json,report.md,run/,listening/}`. Contents:
- speaker verification: EER, false accept / false reject at the deployed thresholds (trials built inside each clip from
  the clean references, pooled; parameters recorded);
- full pipeline: wrong-person rate, target retention, wrong share of output, SI-SDRi, overall and **by overlap type**
  (none / two speakers / three or more, computed from the reference activity) and by tag;
- real "target leaves the frame" clips (tag `face_disappears`): per target result;
- visibility independence: for each clip with a video the output must be byte-identical for the video, a
  blacked-out copy and audio only; clips without a video are listed as skipped, never as passed;
- real-time factor, peak VRAM and RAM per clip; a banner when the run was not on the RTX 3050;
- limitation subsets by tag (`similar_voices`, `whisper`, `shout`, `noise`, `reverb`, `no_solo_enrollment`,
  3+ overlap) with `no_clips` when the dataset has none, plus optional synthetic noise/reverb conditions.
Enrollment mode is recorded: `ref` (clean reference as a separate recording) or `mix_span` (clean span found in the
mixture). The default is `ref`; report both when discussing enrollment without a clean solo span.
Dropout is reported (`dropout_fraction_mean`) but does not block scoring here (the gated baseline mutes overlap by design);
`evaluation_policy` ends in `+dropout-reported` so these reports are never compared with strict-policy ones.

**Reproducibility:** `reproducibility` stores the dataset fingerprint (manifest + every referenced file), manifest hash,
all settings, library versions, git revision and the command. `focus_eval.final_report.stable_metrics` is the exact
timing-free block that two runs with the same fingerprint and settings must reproduce (tested).
To rebuild the report from an existing run directory: `python -m focus_eval final-report --dataset D --run R --out O`.

## 5. Blind listening test
```
python -m focus_eval listening-kit --dataset D --run reports/final/run --out reports/listening --seed 7
python -m focus_eval listening-summary --key reports/listening/key.json --sheets rater1.csv rater2.csv --out summary.json
```
Give raters only `reports/listening/kit/` (anonymised `item_NN_ref.wav` = clean recording of the voice to follow, `item_NN_A/B.wav`, `scoring_sheet.csv`, `INSTRUCTIONS.txt`);
`key.json` stays with the organiser. A/B order is random per item and seeded; 2 control items (the same clip twice)
catch raters who always pick one side. The summary unblinds, reports the processed-clip preference, an exact sign
test (two-sided), mean 1-5 ratings per condition, the control result, and every malformed answer and every item absent from a sheet
(exit code 1 if any). Fine-tune nothing from a handful of raters: read the p-value with the sample size.

## 6. Tests run in this workspace
New: `tests/final` (26: profiler with injected readers, idle classification, residency, supported-length rule,
decode cache incl. changed-content safety, prefetch order, profile run, one-command report incl. visibility check,
reproducibility, failed targets recorded, tuner verdict, stress determinism, listening kit and summary) and
`tests/api/test_speed_limits.py` (8). Existing suites unchanged and passing (see the log).
