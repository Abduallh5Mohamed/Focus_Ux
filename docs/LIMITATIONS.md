# Limitations (for the defence chapter)

Every statement is marked **measured** (a real run, with its data and machine), **by construction** (follows from the
design, no number), or **not measured**. As of this writing nothing has been measured on Egyptian speech or on the
RTX 3050 laptop.

## What exists as measured evidence
Real models on CPU in Replit, **non-Egyptian** LibriSpeech synthetic mixes (`docs/voice_pipeline_results/`):
ECAPA speaker verification EER 0.0 on 8 English speakers (140 same / 980 different trials); noisy-mix pipeline run:
wrong-person rate 0.018, target retention 0.64, SI-SDRi 5.05 dB, RTF 0.29 (CPU, not the laptop), DER 0.55 on noisy mixes.
These numbers do not transfer to Egyptian Arabic or to the laptop GPU.

## Case by case
| Case | Status | Honest statement |
|---|---|---|
| **3+ speakers overlapping** | By construction + not measured | The default extractor mutes every overlap region, so target speech inside overlap is lost (retention in overlap is 0 by design) and SI-SDRi falls with the overlap share. The two-speaker overlap models evaluated in the bake-off cannot separate three voices in one window and none ran on real weights. The final report lists `three_plus` only if the dataset contains such a clip; otherwise it says `no_clips`. |
| **Similar voices** (same sex and pitch) | Not measured | Cosine matching with two thresholds; similar voices narrow the gap between same and different scores, so the uncertain band grows and speech is muted rather than guessed. Measured by the `similar_voices` tag once Egyptian clips exist. |
| **Whisper / shout** | Not measured | The embedder was calibrated on normal speech; whisper has no pitch and shout changes spectral tilt, so scores may fall below the target threshold (lost speech) or move toward "uncertain". Needs real recordings tagged `whisper` / `shout`; no synthetic stand-in is claimed. |
| **Noise and reverb** | Synthetic only, run on the laptop with `--stress` | `focus_eval.stress` adds pink-ish noise at 20/10/0 dB SNR and an exponential-decay room response (RT60 0.4/0.8 s). These show a trend, not real rooms. Real recordings go in under tags `noise` / `reverb`. |
| **Enrollment without a clean solo span** | Refusal by design; quality not measured | Under 4 s of clean speech is refused; 4-10 s warns. If the user can only supply overlapped speech the app asks for a separate recording or a manual range. Tag `no_solo_enrollment` and the `mix_span` setting measure the cost. |
| **Diarization errors** | Measured on non-Egyptian noisy mixes (DER 0.55) | Oracle-diarization runs hide this; the final run uses the real diarizer. |
| **Thresholds** | Provisional | ECAPA thresholds were calibrated on LibriSpeech. They must be recalibrated on Egyptian solo recordings before any claim about false accepts. |
| **Speed / VRAM on the laptop** | Not measured | See `docs/SPEED_AND_FINAL_EVALUATION.md`. 10-minute clips: refused above the current 180 s limit until a measured limit file is installed. |
| **Output is audio-only after enrollment** | By construction, tested | Nothing visual can reach the result; verified byte-identical in tests with fakes and re-checked on real clips by the final report. |
