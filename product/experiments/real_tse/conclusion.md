Measured on CPU, English LibriSpeech read speech (not Egyptian Arabic), 6 two-speaker and 6 three-speaker mixes of about
10 s, oracle region labels, real pretrained weights only. This is a small sample (one mix per condition), so treat the
numbers as a direction, not a precise ranking.

Did any candidate improve over the gated baseline (which mutes every overlap: SI-SDRi about -30 dB, target retention 0)?

2-speaker overlap (rule from COMPARISON_RULE.md applied to the hybrid output):
- REAL-TSE WeSep BSRNN: improves. SI-SDRi +16.1 dB in overlap, target retention 0.94, interferer leakage share ~0 (ratio 0.0),
  STOI 0.91, PESQ 2.87, muted 4 %. Whole-mixture raw extraction is even better (+18.0 dB).
- USEF-TSE: improves by the rule, but only barely in hybrid form (+1.8 dB, retention 0.59, 29 % muted, because the
  voiceprint check rejected many of its 8 kHz outputs). Raw whole-mixture extraction is strong (+12.8 dB, retention 0.94).
- SpEx+: does not improve. Raw +0.4 dB; hybrid -19.8 dB because 80 % of its output was muted by the voiceprint check.

3-speaker mixes (caveat: in the partial mixes some stretches have only the target plus ONE other speaker, and the overlap region includes them; only the 3 full-overlap mixes are pure target + 2, where WeSep hybrid is +2.96 dB, USEF raw +2.3 dB):
- No candidate meets the rule. WeSep gets closest: hybrid SI-SDRi +4.6 dB, retention 0.71, leakage share 7 %, but the
  pooled leakage ratio is 0.96 (limit 0.5), driven mostly by one mix (full overlap, target 6 dB quieter: ratio 4.9,
  SI-SDRi -1.1 dB). Raw WeSep +6.0 dB, USEF +5.0 dB, SpEx+ +5.7 dB, all with 13-19 % of the interferer energy kept.
  Extraction in 3-speaker overlap is therefore partly useful but unreliable, especially when the target is the quietest voice.

Things to know when reading the tables:
- Raw vs hybrid: the hybrid's voiceprint check (the production-shaped safeguard) is what mutes most of the 8 kHz models'
  output. That is a result about the check plus the models' band limit, not only about separation. The raw rows show
  separation alone.
- The pooled "leakage ratio" is a mean of per-mix ratios and is dominated by mixes where little target energy is kept;
  "leakage share" (share of interferer energy kept) is the steadier number.
- Output level and polarity of all three checkpoints had to be fixed by the same least-squares step (rule item 10);
  without it the numbers are not usable.
- 8 kHz models lose everything above 4 kHz, which lowers STOI and PESQ against the 16 kHz reference.
- WeSep is also the slowest to load and, on CPU, runs at about 1.0x real time on a 10 s mix; USEF-TSE about 5x (too slow on CPU);
  SpEx+ about 0.24x. GPU timing and VRAM are not measured here.

Licence-qualified recommendation:
- Technically best: WeSep BSRNN in 2-speaker overlap. Its weights have NO explicit licence ("unclear, not approved for
  deployment"). USEF-TSE is "academic / non-commercial only". Neither is approved for deployment. SpEx+ (Apache-2.0 per the
  model card, "clear for unrestricted use") did not improve over muting, so there is no licence-clean model that helps today.
- Recommended validated model: none approved for deployment. WeSep is validated for research use only.

Smallest production change if the licence is later resolved (proposal only, not built, defaults stay as they are):
use the existing HybridExtractor with the WeSep adapter in place of the gated baseline's muting, behind a default-off
setting, only for regions the diarizer labels as a 2-speaker overlap that includes the target, and keep the voiceprint
check that mutes uncertain output. The experiment used ground-truth region labels, so a real diarizer's overlap detection
is still unmeasured. 3-speaker overlap stays muted.

Most likely next options: (1) ask the REAL-TSE authors for a licence or retrain WeSep BSRNN on licensed data; (2) fine-tune on
Egyptian Arabic mixtures (the checkpoints saw only English); (3) measure on the RTX 3050 with the commands in
RTX3050_COMMANDS.md before relying on any timing.
