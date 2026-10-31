# FOCUS quality audit and first corrections — 2026-10-31

Worktree: main-0aec6d07, based on 183c7d4 with existing WorkBuddy changes preserved. No reset/pull/commit/push. No original A:/focus files/environment modified. No packages or weights downloaded.

## Corrections made

- Dev API base defaults to /api when no explicit override is supplied. Production and explicit overrides retained. Added env regression tests.
- UI and server mix defaults now add zero residual/other voices. User can explicitly change the mixer.
- Speech-separation output no longer deliberately adds the other stem in target gaps.
- Timing-only source selection fails when there are no TARGET spans or the source timing-contrast spread is under 1dB, instead of choosing the first stem on a tie. This 1dB heuristic is a provisional guard, NOT calibrated identity confidence.
- Extractor metadata identifies timing_contrast selection and other_source_added=false. The implementation still masks by TARGET regions: full-overlap voiceprint-conditioned extraction is NOT implemented by this change.

## Observed validation

- Python targeted separation/level-fit/export tests: 17 passed. ffprobe supplied through process-only PATH from A:/Focus_Ux/runtime/audit_20261030/bin. Starlette httpx deprecation warning remains.
- Frontend env and voice-mix tests: 8 passed; TypeScript/Vite build passed.
- Real existing MossFormer2_SS_16K inference on constructed 6s mixture of two source recordings completed, model progress reports 51.16s (not full process wall time). Final files decoded by soundfile. No GT/reference passed to the separator.
- Measured runtime torch: 2.15.0+cpu, torch.version.cuda=None, CUDA unavailable despite RTX3060 being present. This runtime cannot deliver GPU performance until a separate compatible GPU environment is approved/provisioned. Do not modify A:/focus or install CUDA implicitly.

## Objective measurements and limits

Evidence: A:/FocusLocalTrialReports/quality_audit/measured_si_sdr.json.

| Target | Input SI-SDR | Best separated stem SI-SDR | Improvement |
|---|---:|---:|---:|
| Left | -13.86dB | 10.44dB | +24.31dB |
| Right | 13.22dB | 19.18dB | +5.96dB |

References were used ONLY by evaluation to pick the best stem. This is ORACLE source assignment, not proof the product selects the intended voice. Source levels were not equalized; mixture is dominated by the right source. One short synthetic mixture is not a dataset acceptance result, listening judgement, natural-conversation result, Egyptian-Arabic validation or 3-speaker proof. No PESQ/ViSQOL measured.

Evidence: measured_export_mix.json. New target-only render preserves left stem SI-SDR 10.44dB; residual addition is blocked for that weak source because original correlation fails the reliability check. For the strong right source, old 25% residual render scored19.44dB and new zero-residual19.18dB. Thus removing residual is semantically correct for target-only mode but does NOT establish a universal numerical improvement or prove the handoff's claimed 3.3dB degradation. Speech/gap contrast is not SI-SDR.

Raw stems, original mixture, reference WAVs and old/new render WAVs are in the external quality_audit folder. No personal recording was uploaded to third parties. Human listening remains required.

## Next acceptance gates

1. Obtain approval to create a separate GPU-compatible ClearerVoice environment under A:/Focus_runtime, reuse existing weights; test import/CUDA compatibility before real inference. No system CUDA upgrade or legacy environment change.
2. Replace timing-only stem assignment with enrollment-embedding comparison on separated sources, validate margins/refusal behavior; handle chunk permutation before streaming. Preserve target during overlap only after identity validation.
3. Run balanced two-source AND three-source GT tests. Current model is a TWO-source separator; do not promise three-speaker extraction. Compare other available models only after proving their real availability.
4. Repeat actual website upload/enrollment/job/export journey in this worktree; current changes have not been validated through a running browser. Existing service instances must be identified before any restart. Do not claim these changes are live.
5. Listen at matched loudness, inspect missing words/artifacts and temporal leakage, then measure final encoded MP4 against WAV/reference. No clean reference => no invented SI-SDR/PESQ.

These changes are an audited first correction, not a finished product or real-time acceptance.
