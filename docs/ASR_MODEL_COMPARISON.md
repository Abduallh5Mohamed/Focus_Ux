# ASR model comparison (Egyptian Arabic)

## Status: NOT YET MEASURED — default stays `small`

This environment has no GPU, no ASR weights and no human-verified Egyptian references
(`product/datasets/egyptian_eval` clips are all `template`). No CER/WER/time/memory
numbers are claimed here. The previous product's `small` result (36–65% error) came from
the legacy scripts and used provisional (ASR-made) references, so it is a baseline hint only.

`small` is kept as the default (`FOCUS_ASR_MODEL`, in `product/tools/asr_engine.py`) only
because it is the previously deployed model; change it after the table below is filled.

## Candidates (approximate sizes, confirm before downloading) — NEEDS TEAM APPROVAL

| Model (faster-whisper / CTranslate2) | Approx. download | License | Note |
|---|---|---|---|
| `small` (current) | ~0.5 GB | MIT | baseline |
| `medium` | ~1.5 GB | MIT | fits 6 GB next to isolation? unmeasured |
| `large-v3-turbo` | ~1.6 GB | MIT | faster than large-v3 |
| `large-v3` | ~3 GB | MIT | most likely to hit 6 GB limit with Dolphin loaded |

No weights were downloaded. The worker forces offline mode; a model that is not already
local is reported as "model unavailable" in the UI.

## How to measure (on the Windows GPU computer, after approval)

1. Put human-written references in a folder: `<clip>.wav` (isolated output) + `<clip>.txt`.
   Only human-verified text counts; clips without `.txt` are skipped.
2. `python product/tools/compare_asr.py --data DIR --models small,medium,large-v3-turbo --out asr_results.json`
3. Record below: CER, WER (normalisation in `focus_eval.textnorm`), real-time factor,
   per-clip seconds and peak GPU MB (measured with Dolphin loaded, i.e. run while the worker is up).
4. Pick the default: lowest CER/WER that completes without OUT_OF_MEMORY and with
   acceptable time for a 15 s clip.

| Model | CER | WER | RTF | Peak GPU MB | Result |
|---|---|---|---|---|---|
| small | – | – | – | – | pending |
| medium | – | – | – | – | pending |
