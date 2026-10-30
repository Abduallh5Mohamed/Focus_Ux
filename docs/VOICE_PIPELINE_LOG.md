# Voice pipeline implementation log

Status: audio-only proof of concept. Component documentation: `docs/VOICE_PIPELINE.md`.
Raw result files: `docs/voice_pipeline_results/`.

## Implemented
Audio-only package `focus_ml/voice/` (preprocess, diarizer+VAD, embedder x2, enroller with 3 sources, matcher,
gated-baseline extractor, GPU stage log, weights/readiness, CLI), Windows readiness + approval-first setup,
Egyptian recording kit (consent form, guide, manifest + validator), ground-truth mix generator from solo
recordings, evaluation metrics (EER/FAR/FRR, DER, wrong-person rate, retention, SI-SDRi, RTF, VRAM) and eval CLI
commands `voice-eval`, `voice-calibrate`. No video argument, no speech recognition, no worker/app change.

## Files
- New: `product/packages/ml/focus_ml/voice/*`, `product/packages/eval/focus_eval/voice_{metrics,mix,dataset,eval}.py`,
  `product/tools/{setup_voice,voice_eval_run,validate_voice_recordings}.py`, `Setup-Voice.cmd`, `Voice-Readiness.cmd`,
  `product/datasets/egyptian_voice/*`, `product/tests/voice/*`, `docs/VOICE_PIPELINE*.md`, `docs/voice_pipeline_results/`.
- Changed: `product/tools/three_speaker_set.py` (`--solo-dir` audio mode), `focus_eval/cli.py` (2 commands), `.gitignore`.

## Models and libraries (versions actually run)
| Item | Version | Licence |
|---|---|---|
| pyannote `speaker-diarization-community-1` (diarization, VAD, overlap; bundled WeSpeaker embedding "pyannote") | pipeline config for pyannote.audio 4.0.0 | CC-BY-4.0 (gated on Hugging Face) |
| SpeechBrain `spkrec-ecapa-voxceleb` (ECAPA-TDNN) | speechbrain 1.1.2 | Apache-2.0 |
| pyannote.audio | 4.0.7 | MIT |
| PyTorch (CPU build in Replit) | 2.8.0+cpu | BSD-3 |
| soundfile / huggingface_hub | 0.14.0 / 2.4.0 | BSD / Apache-2.0 |
| Test audio: LibriSpeech dev-clean, 8 speakers | – | CC-BY-4.0 (**English, not Egyptian**) |

Packages and weights live in `runtime/voice/` (git- and publish-ignored), not in the project dependencies.

## Tests run
- New `product/tests/voice`: 28 passed (enrollment rules, thresholds, muting/fades/length, audio-only invariance
  with original/blacked-out/no video, missing weights, setup safety, metrics, mix generator, manifest validation).
- Existing suites after the change: ml 105, worker 30, api 196 (+1 skipped), eval 46, inference 40 (needs
  `PYTHONPATH=product:product/packages/ml`, as the workflow sets) all passed.

## Results (REAL runs, CPU in Replit, NON-EGYPTIAN LibriSpeech synthetic data)
Setup: 8 speakers, 110 s solo each. Verification: 4 s utterances, enrol on first 3, 140 target / 980 other trials.
Mixes: 3 speakers, turn-taking with 1.5 s overlap, ~21 s each, random gains (±4 dB); enrollment is a separate 12 s recording of the
target that is not in any mix. Thresholds calibrated on clean mixes 01–05; reported numbers are on held-out clean
mixes 06–10 (5 mixes × 3 targets = 15) and 10 noisy mixes (white noise 20 dB SNR; 30 targets, not used for calibration).

| Measure | ECAPA | pyannote built-in |
|---|---|---|
| Verification EER (clean read speech) | 0.0% | 0.0% (**too easy to separate the two**) |
| Calibrated thresholds target / other | 0.408 / 0.358 | 0.439 / 0.389 |
| Held-out clean: wrong-person rate (others' solo speech passed) | 1.1% | 2.1% |
| Held-out clean: target solo-speech retention | 76.7% | 79.6% |
| Held-out clean: SI-SDRi of gated baseline | +3.95 dB | +4.86 dB |
| Noisy 20 dB: wrong-person / retention / SI-SDRi | 1.8% / 63.8% / +5.05 dB | 1.8% / 60.4% / +5.81 dB |
| Diarization error rate (both runs share the diarizer) | 55.3% clean, 55.2% noisy | same |
| Real-time factor on CPU (mean per target; diarization cached for later targets) | 0.15 clean, 0.29 noisy | 0.12 / 0.07 |
| Peak VRAM | not measured: no GPU here | not measured |

Other findings:
- Heavy noise matters: with white noise at 15 dB SNR a 2.2 s solo region scored 0.27 against a voiceprint where the clean reference scored 0.73; matching
  degrades before the diarizer does (exploratory single-mix check, not a calibrated number).
- DER is high because the synthetic 3-speaker scenes have 4 s turns and 1.5 s overlaps and the diarizer merged speakers; DER counts overlap per speaker, so
  the gated baseline's muting of all overlap shows as miss/confusion. Some true overlap still passes (19–23% of overlap frames) when the diarizer labels it solo.
- ~20% of speech time is `uncertain` (mostly overlap) and is muted by design.
- CLI smoke run (`runtime/voice/public/results/smoke_cli`): a 14 s clip, real weights, CPU, RTF 0.89 including model load; output length equals input length.

**Embedder choice:** the task asks to keep the better one on the Egyptian set. On this non-Egyptian set they do not differ on verification; ECAPA had half the wrong-person rate
on held-out clean mixes, pyannote slightly higher retention. `ecapa` stays the CLI default **provisionally** (wrong-person leakage is the costlier error). Decide on Egyptian recordings.

## Limitations
- All numbers are English read speech, synthetic mixes, CPU. Nothing here says how it performs on Egyptian Arabic, real rooms or phones.
- Calibration used 17 target / 34 other solo regions (5 mixes): thresholds are provisional and statistically thin.
- Peak VRAM, fp16 behaviour and GPU timing are unmeasured (code path exists: `torch.autocast`, per-stage `peak_vram_mib`).
- Overlap speech is muted (baseline); target speech inside overlap is lost until the overlap-extraction task.
- The pipeline is batch (whole file), not live.
- In this workspace the community-1 weights downloaded without a token; Hugging Face may still require accepting terms on the user's account, so the setup script explains that step and also accepts an empty token.

## Remaining work / needs from the team
1. Windows laptop (ASUS TUF RTX 3050): run `Setup-Voice.cmd`, `Voice-Readiness.cmd --url ...`, then the CLI and `voice_eval_run.py` to get real peak VRAM, fp16 and GPU RTF. **Not done.**
2. Egyptian recordings per `product/datasets/egyptian_voice/RECORDING_GUIDE.md` with signed consents (≥5 speakers, solo in several volumes/distances/noise/rooms, 2- and 3+-person overlap with annotations, leave-frame clips).
   Then: EER/FAR/FRR, calibration, DER, wrong-person, retention on Egyptian data; choose the embedder.
3. Next task (overlap extraction) can start: the `Extractor` interface, labelled timeline and ground-truth mixes are ready.
