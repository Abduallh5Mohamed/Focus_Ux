# Overlap extraction: candidates, how to compare, decision

Scope: audio only. A hybrid stage that extracts the target voice **only inside overlap regions**; the app and
worker protocol are not touched. Code: `product/packages/ml/focus_ml/overlap/`.

## Decision (current status)

**Update:** the three voice-conditioned candidates have now run on real weights on CPU with English data (see "Measured results" below); the other three have not. The statements in this paragraph about the workspace describe the original situation.

**No default extractor has been chosen by measurement yet.** The Replit workspace has no GPU, no PyTorch, no
extractor weights and no Egyptian recordings, so none of the six candidates could run here; each reports a
`missing_weights` blocker (see `python -m focus_ml.voice.cli readiness`, key `overlap_extractors`). Until the
bake-off runs on the team's laptop, the **gated baseline (mute overlap) stays the default**.

Decision rule (in `overlap/metrics.py`, applied automatically by the bake-off): a candidate is eligible only if
its overlap SI-SDRi beats the gated baseline by at least 1 dB, wrong-person rate is at most 10 % and mean target
retention is at least 0.30. Default = best eligible candidate, fallback = second (or the gated baseline). A
candidate that handles only 3+ overlap can never be the general default; it is reported as the 3+ option.
Results from non-Egyptian data or a non-GPU device are labelled provisional.

**If no candidate improves on the gated baseline in overlap** (the report states this plainly), the plan is
fine-tuning: (1) simulate Egyptian Arabic mixtures from the team's solo recordings with
`product/tools/overlap_set.py` (2 and 3+ speakers, target -6/0/+6 dB, MUSAN noise at several SNRs; enrollment
audio kept out of the mixes); (2) fine-tune the best-measured target-conditioned base model, REAL-TSE WeSep BSRNN
(open training code), on them plus public data; (3) roughly 20-40 GPU hours on one 24 GB cloud GPU for a first
round (an estimate, not a measurement), then repeat this bake-off on held-out Egyptian speakers.

## Candidates

Blind separators are **blind separation followed by voiceprint selection**, never voice-conditioned.

| Candidate | Mechanism | Rate | Code licence | Weights licence | Categories |
|---|---|---|---|---|---|
| `wesep_bsrnn` REAL-TSE WeSep BSRNN `spk_emb_100` | voice-conditioned (WeSpeaker embedding of the enrollment) | 16 kHz | Apache-2.0 (no LICENSE file at repo root when checked) | none stated | 2, 3+ |
| `usef_tse` USEF-SepFormer wsj0-2mix | voice-conditioned (enrollment fused by cross attention) | 8 kHz | CC-BY-NC-4.0 | CC-BY-NC-4.0 | 2, 3+ |
| `spexplus` ClearerVoice SpEx+ wsj0-2mix | voice-conditioned | 8 kHz | MIT | Apache-2.0 | 2, 3+ |
| `mossformer2_ss_voiceprint` MossFormer2_SS_16K | blind separation, then voiceprint selection | 16 kHz | Apache-2.0 | Apache-2.0 | 2, 3+ |
| `sepformer_libri3mix` SpeechBrain | blind separation, then voiceprint selection | 8 kHz | Apache-2.0 | Apache-2.0 | 3+ only |
| `pyannote_ami_pixit` speech-separation-ami-1.0 | blind separation (PixIT), then voiceprint selection | 16 kHz | MIT | MIT, gated | 3+ only |

Pinned sources: wesep-real-tse `2a54097`, wespeaker `8f53b64`, USEF-TSE `bdaeb36`, ClearerVoice-Studio `6b3774d`.
Non-commercial weights are acceptable for this academic project; the licences are repeated in the report.

Known setup facts: REAL-TSE checkpoints are only on Google Drive (`gdown`; the setup falls back to manual
placement instructions); its `requirements.txt` pins `numpy==1.22.4`, which the setup refuses to install
(numpy/torch are protected), so only unpinned minimal dependencies are installed and WeSep may report
`broken_code` on first run. 8 kHz models receive audio resampled 16 -> 8 -> 16 kHz (band-limited to 4 kHz).

## Hybrid behaviour (`overlap/hybrid.py`)

Target alone: passed through. Others alone / unknown: muted. Overlap regions (uncertain regions with reason
`overlap`, minus target-labelled spans): cut into 4 s windows (a short region gets one window centred on it with
real neighbouring audio; a long one overlapping windows, merged with the existing sin² crossfade), batched,
extracted. Each extracted piece (at most 3 s, none under 0.5 s) must reach the embedder's target threshold
against the voiceprint, otherwise it is marked uncertain and muted. Seams between pass-through and extracted
audio cross-fade (20 ms); fades toward muted audio sit inside the kept audio. Output length equals input.

GPU: one extractor resident at a time (`unload()` between candidates); fp16 autocast on CUDA with an fp32 retry on
NaN/Inf; batch size from a rough per-candidate VRAM estimate (initial estimates, not measurements) against a
3500 MiB budget; on out-of-memory the batch halves and, at one window, the candidate is reported blocked
(`out_of_memory`). Peak VRAM, seconds per window and overlap RTF are logged per run (`last_report`).

## Measured results: real weights on CPU (English LibriSpeech, NOT Egyptian Arabic)

Experiment folder: `product/experiments/real_tse/` (`results/report.html`, `report.json`, `listen/<mix>/` FLAC players,
`COMPARISON_RULE.md` written before reading results, `conclusion.md`, `RTX3050_COMMANDS.md`). 12 mixes of ~10 s from
LibriSpeech dev-clean (CC-BY-4.0; seed 83; 6 two-speaker and 6 three-speaker, target -6/0/+6 dB, full and partial overlap),
separate enrollment clip per target, oracle regions. Device: CPU only, 8 cores. **Not measured on the RTX 3050**
(the laptop was not reachable from the workspace); peak VRAM not measured.

All three adapters loaded the real checkpoints and ran on all 12 mixes. Pooled over overlap regions, hybrid output
(SI-SDRi dB / target retention / interferer leakage share):

| | 2-speaker mixes | 3-speaker mixes (overlap = target + 1 or 2 others; only full-overlap mixes are pure target + 2) |
|---|---|---|
| gated baseline (mute) | -30.6 / 0 / 0 | -26.9 / 0 / 0 |
| WeSep BSRNN | +16.1 / 0.94 / ~0 | +4.6 / 0.71 / 0.07 |
| USEF-TSE | +1.8 / 0.59 / ~0 (29 % muted by voiceprint check) | -11.9 / 0.20 / 0.01 |
| SpEx+ | -19.8 / 0.15 / 0 (80 % muted) | -9.5 / 0.22 / 0.02 |

Raw whole-mixture extraction (no region knowledge): WeSep +18.0 / +6.0 dB, USEF +12.8 / +5.0, SpEx+ +0.4 / +5.7 (2 / 3 speakers).
By the pre-stated rule, WeSep and USEF improve on the baseline in 2-speaker overlap; nobody meets it in 3-speaker overlap
(WeSep: leakage ratio 0.96 > 0.5, dominated by one mix). CPU real-time factor on a 10 s mix: WeSep 0.97, USEF-TSE 5.0, SpEx+ 0.24.

Licences: WeSep weights unclear (not approved for deployment); USEF-TSE academic / non-commercial only; SpEx+ clear
(Apache-2.0 per model card) but did not improve. Recommended validated model for deployment: **none**. The gated baseline
stays the default; no production code was changed.

Fixes found only by running real weights (each has a regression test): SpEx+ checkpoint keys carry a `sep_network.` prefix;
USEF checkpoint needs `weights_only=False` (pinned, trusted) and its config path is `chkpt/USEF-SepFormer/wsj0-2mix/config.yaml`
plus one more imported helper file; wespeaker imports s3prl/whisper/transformers/peft eagerly (stubbed, never used by
BSRNN); the WeSep file API needs TorchCodec so the in-memory call is used; all three models output arbitrary polarity and level
(scale-invariant training), so each window is scaled by <est, mix>/<est, est> (mixture only).

## How to run (laptop)

1. `product\tools\Setup-Overlap.cmd` (approval-first, separate folder `%LOCALAPPDATA%\FocusVoice\overlap`; run
   `Setup-ClearerVoice.cmd` first for MossFormer2). Readiness: `python -m focus_ml.voice.cli readiness`.
2. `python product/tools/overlap_set.py --solo-dir <solo wavs> --out overlap-set --language egyptian_arabic --noise-dir <MUSAN noise>`
   (24 mixes: 2 and 3+ overlap x target -6/0/+6 dB x noise none/20/10/0 dB; without `--noise-dir` white noise is
   used and labelled). Solo files are `<speaker>*.wav`, at least 3 speakers, at least 25 s each.
3. `python product/tools/overlap_bakeoff.py --set overlap-set --out bakeoff-out [--real-dir real-clips]`
   -> `report.html` (per category tables, speed/VRAM, blocked candidates with evidence, licences, blind players),
   `report.json`, `decision.md`.

Metrics are split by target-alone / 2-overlap / 3+-overlap: SI-SDRi (muted = -30 dB floor), wrong-person rate
(muted regions excluded, muted share shown), target retention, RTF on overlap audio, peak VRAM. Real clips get
players only (no reference). Region truth is oracle (turn level), so the extractor is measured apart from the
diarizer.
