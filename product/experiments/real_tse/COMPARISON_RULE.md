# Comparison rule (written before any result was read)

Data: LibriSpeech dev-clean (English read speech, CC-BY-4.0). **Not Egyptian Arabic.** Device: CPU.

1. **Same inputs for everyone.** Every candidate and the gated baseline get the same 12 mixtures (6 two-speaker,
   6 three-speaker), the same separate enrollment clip per target, the same oracle region labels, the same
   hybrid settings (4 s windows, 20 ms seams, voiceprint check at the embedder's target threshold) and the same
   seed (`--seed 83`). Nothing is tuned per candidate.
2. **2-speaker and 3-speaker groups are never pooled together.** (The overlap region of a 3-speaker partial mix also contains stretches with the target plus only one other speaker; the group label says so.) Each is ranked on its own.
3. **Ranking uses the overlap region only** (samples where the target and at least one other speaker talk),
   on the *hybrid* output, because that is what FOCUS would run (target solo turns pass through, extraction only
   in overlap). Raw whole-mixture extraction is reported next to it, not ranked.
4. **8 kHz models** (USEF-TSE, SpEx+) get audio resampled 16 -> 8 kHz and their output is resampled back to
   16 kHz before scoring, so all outputs are scored at 16 kHz. Their content above 4 kHz is lost; this bandwidth
   loss is noted in the report and is part of what is measured.
5. **Muted output counts as -30 dB SI-SDR** (clamp [-30, 50] dB), so the gated baseline's SI-SDRi in overlap is about
   -30 dB by construction. Beating it on SI-SDRi alone therefore proves nothing. A candidate counts as
   **improving** over the gated baseline in a group only if, pooled over that group's overlap regions, all of:
   * SI-SDRi is at least +1 dB (better than leaving the mixture untouched, hence also better than the baseline);
   * target retention is at least 0.30 (share of the target reference energy kept);
   * interferer leakage ratio (interferer energy kept / target energy kept) is at most 0.50.
   Otherwise the group's result for that candidate is "does not improve", and the gated baseline stays.
6. **Ranking among improving candidates**: highest pooled overlap SI-SDRi. Mean over mixes (each mix weighs the same).
7. **Reported but not used for ranking**: STOI and PESQ (wideband) against the clean target reference in the
   overlap region, muted share, CPU processing time, real-time factor, whole-clip scores.
8. **Only real pretrained weights.** A candidate that fails to load or run is reported as failed with the exact
   error and is excluded from the numbers; no stub, oracle or fake extractor appears.
9. **Licence gate.** A candidate with unclear or non-commercial weights is never described as approved for
   deployment, even if it wins.
10. **Polarity and level.** The three checkpoints are trained with scale-invariant losses, so their output level and
    polarity are arbitrary (seen in a one-mix smoke test: SpEx+ peaks of ~1e5, USEF-TSE inverted and about 3x too loud).
    The same step is applied to all three: each extracted window is multiplied by <est, mixture> / <est, est>,
    which uses only the mixture, never a reference. Without it the hybrid output is not usable. Retention is therefore
    a measure of how much of the target is present after this common convention.
