# Audio-only voice pipeline (proof of concept)

Code: `product/packages/ml/focus_ml/voice/`. CLI: `python -m focus_ml.voice.cli`.
Works only on voice characteristics: **no speech recognition, no language processing, no video.**
A video is reduced to its audio track (`preprocess.load_canonical`) before anything else runs; no function
in the pipeline has a video parameter (a test checks this, and checks identical output for the original
video, a blacked-out video and no video).

## Components

| Component | Responsibility | Model / method | Input → output | Needs | Parallel? | Cost / bottleneck |
|---|---|---|---|---|---|---|
| `preprocess` | canonical audio | ffmpeg | any WAV/video → 16 kHz mono float32 | CPU | yes | negligible |
| `diarizer` (VAD + who spoke when + overlap) | speech regions, speaker turns, overlapping speech | pyannote `speaker-diarization-community-1` (CC-BY-4.0, gated) | samples → `Diarization` (turns, overlaps, speech) | GPU fp16 or CPU; ~1–2 GB VRAM class | no: one model on the GPU at a time | the slowest stage on CPU; result cached per audio file |
| `embedder` | voice → vector | `ecapa`: SpeechBrain ECAPA-TDNN (Apache-2.0); `pyannote`: the embedding bundled in community-1 | samples → unit vector | GPU fp16 or CPU; small | no (sequential) | short regions (<0.5 s) cannot be measured |
| `enroll` | voiceprint from a diarized label, a time range, or a separate recording | embedder + quality rules | audio + diarization → `Voiceprint` | CPU + embedder | – | needs ≥4 s clean speech (configurable) |
| `match` | target / other / uncertain per region | cosine + two thresholds | regions + voiceprint → `LabelledRegion[]` | embedder | – | one embedding per ≤3 s region |
| `extractor` | audio from labels | `GatedBaseline`: keep target solo speech, mute rest, 10 ms fades inside regions, exact input length | samples + regions → samples | CPU | yes | overlap speech is muted (next task replaces it) |

## Rules
- **Enrollment** (all three sources produce one `focus-voiceprint/1` JSON): clean = this speaker only,
  no overlap. Refused below `min_clean_s` (4 s), below −45 dBFS, or above 1% clipped samples; warns when quiet
  (< −35 dBFS), slightly clipped, thin (< 8 s), mostly overlapped, or (range/file) other voices exceed 10%.
- **Matching:** `score ≥ target_threshold` → target; `score ≤ other_threshold` → other; otherwise uncertain.
  Overlap regions and fragments < 0.5 s are uncertain. Uncertain is never passed to the target output.
  A voiceprint made with one embedder is refused by the other.
- **GPU discipline:** models load lazily, run one at a time, use fp16 autocast on CUDA, and are unloaded
  between stages (`unload()` + `empty_cache`). `report.json` logs per-stage seconds and peak VRAM (MiB).
- **No silent downloads:** weights live in `FOCUS_VOICE_HOME` (`%LOCALAPPDATA%\FocusVoice`, else `runtime/voice`);
  only `product/tools/setup_voice.py` downloads, after an explicit "yes". A missing weight is an error with the setup hint.
  The packages go to `<home>/site`, appended LAST on `sys.path`; the original Dolphin environment is untouched.

## Commands
    # Windows: readiness (GPU, VRAM, CUDA, worker connection, weights)
    product\tools\Voice-Readiness.cmd --url https://<site>
    # Windows: one-time setup (approval first)
    product\tools\Setup-Voice.cmd
    # run on a video or WAV; enroll from a diarized label, range, file, or saved voiceprint
    python -m focus_ml.voice.cli run clip.mp4 --enroll-speaker SPEAKER_00 --out out/
    python -m focus_ml.voice.cli run clip.wav --enroll-file my_voice.wav --embedder ecapa --out out/
    python -m focus_ml.voice.cli run clip.wav --enroll-range 3.0 9.5 --out out/

Outputs in `--out`: `diarization.json` (who spoke when + overlaps), `voiceprint_<SPEAKER>.json` (one per speaker),
`best_clean_spans.json`, `timeline.json` (target/other/uncertain), `voiceprint_target.json`, `gated_baseline.wav`
(canonical length), `report.json` (models, thresholds, timing, peak VRAM).
