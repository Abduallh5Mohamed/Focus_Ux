# WORKBUDDY handoff — audio isolation fixes (2026-10-31)

Trigger: user delivered a real job (`ssstik.io_1793296206879.mp4` → `focus-<id>-mix.mp4`) and reported the
voice was not isolated. Full measurement and before/after numbers:
`runtime/analysis/AUDIO_ISOLATION_DIAGNOSIS.md`, `runtime/analysis/rerender_metrics.json`.

## What the delivered file actually was

- Inside speech the export was the source mix × **1.397** (correlation 0.981, 96.3 % of the energy explained by
  one scalar). Nothing was separated; the background bed was **boosted** 2.8 dB.
- **41.7 %** of the timeline was exact digital silence (18 gaps, longest **8.04 s**) cut out of a continuous bed.
- No energy above 8 kHz; the picture was re-encoded 30 → 25 fps (293 → 816 kb/s).
- Corrections to my earlier read: the "clicks" I reported were **not** clicks (output slew ≤ source slew at every
  gate edge), and `mix.py` is **not** the source of the 1.39 gain (re-rendering the same gate through this
  checkout's `mix.align` gives 1.0009). The delivered file's 96 kb/s audio also disagrees with
  `mix_service.py`'s 160k, so it came from a different build. Both corrections are in the report.

## Changed files (mine only)

| File | Change |
|---|---|
| `product/packages/ml/focus_ml/voice/extractor.py` | new `DuckedBaseline` (floor −12 dB, 30 ms fades, **250 ms bridging**), `target_mask(floor=…, bridge_ms=…)`, `build_extractor()` + env knobs; `GatedBaseline` untouched |
| `product/packages/ml/focus_ml/voice/engine.py` | default extractor is `build_extractor()`; `details` now carries `extractor` + `extractor_params` |
| `product/services/api/focus_api/mix.py` | `_active_gain`: level fit on loud frames only; `Alignment.gain_clamped`; sanity bounds 0.05–20 |
| `product/packages/ml/focus_ml/normalize.py` | `normalize_input(..., fps=None)` → `-c:v copy`, with re-encode-at-source-fps fallback |
| `product/services/api/focus_api/inference.py` | `audio_only` passes `fps=None` (nothing in that path reads a frame) |
| `product/tests/voice/test_extractor_ducked.py` | new, 10 tests |
| `product/tests/api/test_mix_level_fit.py` | new, 4 tests |
| `product/tests/voice/test_audio_engine.py` | updated to the ducked contract + a gated variant that keeps the old contract tested |

Env knobs: `FOCUS_VOICE_EXTRACTOR=ducked|gated`, `FOCUS_VOICE_FLOOR_DB` (default −12), `FOCUS_VOICE_FADE_MS` (default 30),
`FOCUS_VOICE_BRIDGE_MS` (default 250).

### Why bridging was added after the first fix

Diarization splits one speaker's turn at every short pause: **128 of the 161** gaps between target spans on this job were
< 100 ms, so the bed was ducked and restored ~90 times. Ducking alone still pumped; bridging gaps < 250 ms drops the
number of ducking events from **90 to 25** (`rerender_metrics.json → masks`).

## Commands and observed results

Environment: `runtime/analysis-venv/env` (numpy 2.5.4, pytest 9.2.0, fastapi/httpx, imageio-ffmpeg 7.1).
There is no system ffmpeg/ffprobe on this machine; ffmpeg came from `runtime/analysis-venv/bin/ffmpeg.exe`.

```
product> pytest tests/voice -q                      -> 45 passed, 2 skipped
product> pytest tests/ml -q                         -> 115 passed, 1 skipped
product> pytest tests/api/test_mix_math.py tests/api/test_mix_level_fit.py -q -> 13 passed
product> pytest tests/voice tests/ml tests/api/test_mix_level_fit.py tests/api/test_mix_math.py -q
                                                    -> 175 passed, 3 skipped
product> pytest tests/api -q                        -> 229 passed, 3 failed, 12 errors
```

The 3 failures + 12 errors in the full API run are **environment**, not code:
`FileNotFoundError [WinError 2]` (no ffmpeg on PATH) and `test_export_is_in_sync_and_video_unchanged`
needs a real **ffprobe**, which this machine does not have. `test_upload_ownership` failures are the
kill-a-subprocess cases and reproduce without my changes' area. They must be re-run on the D: machine.

Before/after on the user's own audio (same TARGET regions, no diarization/model involved — extraction and
export fixes only), `runtime/analysis/rerender.py`:

| metric | delivered | old gate re-render | new (ducked + bridge) |
|---|---|---|---|
| digital silence | 41.72 % | 46.39 % | **0.23 %** |
| gaps > 300 ms | 18 | 22 | **0** |
| longest gap | 8.04 s | 8.18 s | **0.03 s** |
| ducking events | — | 90 | **25** |
| level-fit gain | 1.39 | 1.0009 | **1.0009** |
| RMS | −11.49 dBFS | −14.63 | **−14.43** |
| picture | 25 fps / 816 kb/s | — | **30 fps / 293 kb/s (copy)** |

A DSP-only separator was tried and rejected on evidence: REPET (median filtering across time per bin, 1.0/1.9/3.2 s
windows) removed only **0.2–0.5 dB** of the bed, because the bed is not stationary on this material
(20 ms frame levels inside speech span −33 dBFS to −7 dBFS). Script: `runtime/analysis/repet.py`.

## Speech separation (ClearerVoice MossFormer2_SS_16K) — this is the path that works

Because the background is a voice, the right model class is a speech separator. Installed on **A:** (C: had
no space) and run for real on the user's file.

| File | Purpose |
|---|---|
| `product/packages/ml/focus_ml/voice/separation.py` | `ClearerVoiceSeparator` (subprocess into the CV env) + `SpeechSeparationBaseline` (pick the stem by TARGET contrast, then `gate*chosen + (1-gate)*floor*other`) + `build_separation_extractor` |
| `product/tools/clearervoice_separate.py` | runner: ClearVoice `speech_separation`, prints the stems as JSON |
| `product/tools/clearervoice_setup.py` | readiness check / `--download`, documents the exact install sequence (including `audioop-lts` for Python 3.13) |
| `product/packages/ml/focus_ml/voice/extractor.py` | `FOCUS_VOICE_EXTRACTOR=separation` wires it; still opt-in |
| `product/tests/voice/test_speech_separation.py` | 6 tests with a fake separator: selection rule, blend, no silent fallback, missing env/checkpoint |

Environment (on A:, nothing global touched): `A:/Focus_runtime/cv-venv` (torch 2.15.0+cpu, torchaudio 2.11.1+cpu,
clearvoice 0.1.2, numpy 2.5.4) and the checkpoint in
`A:/Focus_runtime/clearervoice/checkpoints/MossFormer2_SS_16K` (640 MB). Note `clearvoice` pins
`numpy<2.0`/`soundfile==0.12.1`, which cannot be satisfied on Python 3.13; it is installed with `--no-deps` plus a
curated dependency set, and the SS path runs fine on numpy 2.5.4.

Enable with `FOCUS_VOICE_EXTRACTOR=separation`, `FOCUS_CLEARERVOICE_PYTHON=<A:/Focus_runtime/cv-venv/env/Scripts/python.exe>`,
`FOCUS_CLEARERVOICE_HOME=<A:/Focus_runtime/clearervoice>`.

**Measured on the user's file (137 s, CPU):**

| check | value |
|---|---|
| stems produced | 2 (`s1`, `s2`) |
| `corr(s1+s2, mix)` | **0.9716** — the stems are complementary |
| `corr(s1, s2)` | **0.0493** — genuinely different content |
| target contrast, s1 / s2 | **+3.43 dB / -2.25 dB** → s1 chosen |
| s1 vs mix in the non-target regions | **18.7 dB lower** |
| final render, speech vs gap | **-13.22 / -25.19 dBFS = 11.98 dB** (source was 1.25 dB) |
| product class vs demo render | `corr = 1.0000` — the shipped code reproduces the demo exactly |

Output: `runtime/analysis/sep_final.mp4` (original 30 fps picture copied, audio 179 kb/s) and
`runtime/analysis/sep_final.wav`. Cost on this laptop: ~9 min one-time model fetch, ~18 min inference for 137 s.
That is a quality path, not a real-time one.

## Integration runs (2026-10-31, real stack, real file)

**A. Canonical step (the change in `normalize.py` / `inference.py`)** — `runtime/analysis/integration_canonical.py`:

| | audio_only (`fps=None`) | lip engine (`fps=25`) |
|---|---|---|
| output fps | **30.0 (source)** | 25.0 |
| duration delta vs source | 0 ms | 0 ms |
| file size | **6.21 MB** | 14.76 MB |
| audio | 16 kHz mono | 16 kHz mono |
| API duration check (≤80 ms) | passes | passes |

**B. API-level run** — `runtime/analysis/integration_api.py`, real `create_app()`, real dispatcher, storage on A::

| step | result |
|---|---|
| app boot | ok — `/config` reports `engine=audio_only` |
| `POST /videos` (real 137 s file) | ok — 137167 ms, 576x1024 |
| canonical built by the real job | **ok — 6.51 MB (stream copy)** |
| analysis (diarization + embeddings) | **failed** — `PROCESSING_FAILED` |

The failure is environmental, not in the new code: the API was started with an interpreter that has no `torch`, so
`PyannoteDiarizer` cannot load. Even with torch, `pyannote/speaker-diarization-community-1` is a **gated** HF model,
so it needs the user's token plus accepted terms. Nothing downstream of analysis (enroll → job → isolate →
export) could therefore be exercised through HTTP on this machine.

To finish the HTTP end-to-end one of these is needed:
1. an HF token + accepted terms for `pyannote/speaker-diarization-community-1`, or
2. install `speechbrain` (public ECAPA weights) and inject a precomputed diarization into the job DB, so the
   enroll → job → isolate(separation) → export chain runs without pyannote.

### Update: the token arrived, the models are installed, and diarization dies on RAM

Done on 2026-10-31 after the user supplied an HF token (account `ax7shadow`, both gated repos reachable):

* `pyannote.audio` 4.0.7 + `speechbrain` 1.1.2 + `fastapi`/`uvicorn`/`httpx` installed into the A: venv
  (`A:/Focus_runtime/cv-venv`), which already had torch 2.15 CPU and clearvoice;
* weights downloaded with `runtime/analysis/download_voice_weights.py` to `A:/Focus_runtime/voice/weights/`
  (`pyannote__speaker-diarization-community-1`, `speechbrain__spkrec-ecapa-voxceleb`, both with the
  `.focus-complete` marker) — `focus_ml.voice.weights.weight_status()` now returns True for both.

The API run then fails inside diarization, on the machine, not in the code:

```
RuntimeError: [enforce fail at alloc_cpu.cpp:117] data. DefaultCPUAllocator:
not enough memory: you tried to allocate 327024640 bytes.
```

Measured, so it is not a guess:

| check | value |
|---|---|
| same error on a 20 s clip, 1 torch thread | yes |
| `batch_size=1` | ignored by pyannote 4.0.7 (`Ignoring unexpected keyword arguments: batch_size`) |
| fresh process can allocate 1 GB | yes — so it is cumulative process memory, not a hard cap |
| machine RAM | 39.7 GB total, **5.5 GB free** |
| commit | 57.6 GB limit, **2.1 GB free** |
| C: free space | **~37 MB** (deleting 2.7 GB of HF cache + 1.25 GB of venvs did not move it) |

The remaining end-to-end step (diarization → enroll → job → isolate → export) needs roughly 3 GB of free RAM.
Once the machine has it, re-running `runtime/analysis/integration_api.py` with the A: venv finishes the chain.

**Venvs moved to A:** `A:/Focus_runtime/venvs/{analysis-venv,demucs-venv}`; `runtime/analysis-venv` and
`runtime/demucs-venv` no longer exist on C:. The moved analysis venv still passes (175 passed, 1 skipped).

### The full HTTP chain now passes — 12/12 steps

After the user freed RAM, `runtime/analysis/integration_full.py` ran the whole product path with **no fakes**
(real app, real dispatcher, real diarization, real ECAPA, real separation, real export):

| step | result |
|---|---|
| app boot / `/config` | `engine=audio_only`, extractor `separation` |
| `POST /videos` (real 137 s file) | 137167 ms |
| analysis (pyannote + ECAPA) | **ready** — 2 voices: `voice-0` usable (86.9 s clean), `voice-1` unusable |
| enrollment | ready, warning: "30 % of this voice's speech overlaps with others and is not used" |
| job | completed, `engine=audio_only`, follow periods with `voice_match` / `uncertain_voice` |
| `GET /jobs/{id}/audio` | 4.39 MB WAV |
| export → file | **7.86 MB MP4, 137.17 s, 30 fps picture copied, audio 155 kb/s** |

Quality of the real export (`runtime/analysis/api_export.mp4`), same regions as before:

| | rms | speech | gap | **contrast** | corr with source |
|---|---|---|---|---|---|
| source | -12.4 | -12.2 | -12.7 | **0.5 dB** | 1.0000 |
| delivered (old ducked) | -11.5 | -9.1 | -240 | 230.9 dB (chopped) | 0.7655 |
| **API export (separation)** | -13.6 | -11.9 | -18.4 | **6.6 dB** | 0.8890 |
| demo (separation, demo regions) | -15.7 | -13.6 | -25.0 | 11.4 dB | 0.7653 |

The job's own `isolated.wav` scores **9.9 dB** contrast (speech -28.9 / gap -38.8); the export lands at 6.6 dB
because the export step adds the mix settings on top. The export and the demo correlate at 0.95.

Two environment notes that are NOT code defects:
* ffmpeg must be on PATH for the engine (`focus_ml.voice.preprocess._decode`); a shim now lives at
  `runtime/bin/ffmpeg.exe`. Without it analysis fails with "audio tool unavailable".
* the audio-only flow still refuses an enrollment until a face row exists, and face detection needs the lip
  models (not on this machine). The integration run inserted a synthetic face row for that reason; this is the
  one stubbed piece and it is called out in the script docstring.

## Blockers / not done

- **The bed under speech is still there with the DEFAULT extractor.** Ducking stops the chopping; the actual
  removal needs `FOCUS_VOICE_EXTRACTOR=separation` (proven above) or `music` (proven not to help on this file).
  Both are opt-in because each needs its own environment and weights.
- 8 kHz ceiling is a 16 kHz model constraint, not something a resampler can fix.
- No LUFS normalisation; no Egyptian recalibration of `match.py` thresholds (LibriSpeech values still in place).
- API/full-suite verification on the D: machine (real ffprobe + GPU) is still required before any readiness claim.
- **C: is still ~100 % full (1.3 G free).** The ClearerVoice work was put on A: (24 G free) for that reason.
  The Demucs environment (769 MB) and the analysis venv (478 MB) are still on C:; they can be moved or deleted
  once the choice of separator is settled.
- Speech separation is **slow on CPU**: ~18 min for 137 s (≈8× realtime). On the GPU laptop this must be
  re-measured before any real-time claim.

## Music separation (Demucs) — implemented, and what the real run showed

Opt-in only; the default extractor is still `ducked`, because the Demucs path needs its own environment.

| File | Purpose |
|---|---|
| `product/packages/ml/focus_ml/voice/music.py` | `DemucsSeparator` (subprocess into the Demucs env, no torch in the product env) + `MusicSuppressedBaseline` (`gate*vocals + (1-gate)*floor*accompaniment`) + `build_music_extractor` |
| `product/tools/demucs_separate.py` | the runner: loads htdemucs, keeps the `vocals` stem; pure `wave`+numpy I/O because torchaudio 2.11 routes load/save through TorchCodec |
| `product/tools/demucs_setup.py` | readiness check, `--download` to fetch weights once, real forward-pass probe |
| `product/packages/ml/focus_ml/voice/extractor.py` | `FOCUS_VOICE_EXTRACTOR=music` wires the above; `AudioOnlyEngine.isolate` calls `check_ready()` before diarization |
| `product/tests/voice/test_music_extractor.py` | 5 tests with a fake separator: blend maths, no silent fallback, missing-environment error |

Enable with `FOCUS_VOICE_EXTRACTOR=music` + `FOCUS_DEMUCS_PYTHON=<runtime/demucs-venv/env/Scripts/python.exe>`.

Environment built here (project-local, nothing global touched): `runtime/demucs-venv` (torch 2.15.0+cpu,
torchaudio 2.11.1+cpu, demucs 4.1.0) and weights in `model-assets/demucs` (81 MB). `demucs_setup.py --download`
reports `ready: true`, `sources: [drums, bass, other, vocals]`.

**Result on the user's file: Demucs does not help, because the background is a voice, not music.**

- `vocals` stem = the whole mix: correlation 0.9969, **99.4 %** of the mix energy explained by it
- `accompaniment` (everything else) sits at **-43 dBFS** over the file, -45.2 dBFS in the gaps
- on a gap-only clip the stems are `vocals -13.0`, `drums -67.8`, `bass -68.9`, `other -56.7` dBFS
- the gap content is speech-like: envelope modulation 2-8 Hz share 0.50 (gaps) vs 0.61 (speech regions)

So the thing that has to go is **another human voice** (or a sung vocal). The correct model class is speech
separation / target-speaker extraction on the enrolled voiceprint: `MossFormer2_SS_16K` (blind, then pick by
voiceprint), `WeSep REAL-TSE` (conditioned on the embedding) or `AV-MossFormer2_TSE` (needs a face). All of them
need weights and an environment, i.e. 2-4 GB of disk and an explicit go-ahead. Evidence:
`runtime/analysis/demucs_findings.json`.
