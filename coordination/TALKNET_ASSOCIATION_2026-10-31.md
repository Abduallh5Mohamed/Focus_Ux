# TalkNet face/audio association — experimental, 2026-10-31

User authorized new TalkNet weights in isolated A:\Focus_runtime only. No original A:\focus modifications, no new separation weights, no push/deploy.

## Assets and provenance
- Upstream: https://github.com/TaoRuijie/TalkNet-ASD
- Source revision: 6d6821479af485e251c4991487e40573b42181b4, external runtime checkout.
- Weights: upstream demo's pretrain_TalkSet.model, official demo Google Drive ID 1AbN9fCf9IexMxEKXLQY2KYBlb-IhSEea.
- Local file: A:\Focus_runtime\active-speaker\weights\pretrain_TalkSet.model (63,227,827 bytes).
- Observed SHA256: d985ddd07dca08864a28337726f5b7d91b6426bebc7327f0e9b21cf9ff1cc937 (local provenance, not a separately published authenticity check).
- Runtime: existing isolated cv-gpu312-reuse Python/CUDA environment. No additional package installations needed. Import model/loss directly, avoiding training/demo dependency on pandas and demo auto-downloads.

## Behavior
face_picker.py provides actual visual candidates independently of Dolphin. talknet_score.py loads model and classifier state strictly with weights_only=True, disables network connections, samples video at 25 fps, builds MFCC features from canonical 16k audio, follows selected anchor conservatively using Haar geometry and upper-face appearance, and outputs per-frame raw ASD scores. This is not biometric face recognition. Cuts/occlusion/motion can lose the track, causing abstention. The score is not a calibrated probability. Four-second inference context differs from upstream multi-context ensemble and needs accuracy validation.

av_sync.py runs isolated scoring using configured FOCUS_TALKNET_PYTHON/SOURCE/WEIGHTS. The existing visibility/suggestion record carries tagged av_sync_v1 evidence; no schema migration or extraction request change. Old on-screen-only evidence is refreshed on a new suggestion request. rank_sync compares scores on non-overlapping diarized speech, requires two usable voiceprints, enough scored solo speech and a provisional margin. It only preselects a suggestion; user confirmation remains mandatory. Ties, one usable voice, insufficient coverage, NaN/Inf or overlap-only speech abstain. No audio stem or voiceprint is invented.

## Measured verification and outstanding blocker
- Real CUDA TalkNet loaded successfully. First 30-second/one-face seek-per-frame attempt: 47.60 s. Sequential decoding rerun: 7.39 s, 745 scored frames. Timing includes process/model startup; not live p95 latency or an isolation benchmark.
- Real API trial of three_speakers_overlap_30s.mp4: three visual candidates, evidence=av_sync returned for all three; face request wall times 8.24, 8.24, 7.86 s. Analysis still produces only one usable voiceprint (second has no solo speech); every face correctly abstained under the implemented rules. THIS DOES NOT SOLVE automatic face-to-voice assignment on this clip.
- Controlled alternating 12-second fixture, including separately balanced version: upstream diarizer still returned one usable voice; suggestion abstained. No end-to-end automatic matching success is claimed. One tracked face's scores differed across known audio halves (about +1.10 vs -2.80), but this alone is not identity-accuracy validation.
- Tests: 25 API tests passed including five synthetic-score selection/abstention tests; 13 web voice-flow tests passed; TypeScript check and git diff --check passed. Synthetic-score tests establish rules, not model accuracy.
- git diff against authoritative 349957f shows no changes in separation.py, voice/engine.py or API mix.py. Existing isolation model, gate configuration and rendering are unchanged; this does not guarantee that a misselected voice would sound correct.
- Evidence: A:\FocusLocalTrialReports\av_sync\*_api_report.json and scores_sequential.json. No session tokens in reports.

## Configuration
Set FOCUS_TALKNET_PYTHON to the isolated GPU Python, FOCUS_TALKNET_SOURCE to the external upstream source checkout, FOCUS_TALKNET_WEIGHTS to the existing checkpoint, FOCUS_FACE_CASCADE to an installed frontal-face Haar cascade. Without weights the scorer errors rather than downloading. The local GPU API launcher has these process-scoped settings. Runtime remains available at localhost:5000.

Automatic association is NOT ready for the user's simultaneous-three-speaker fixture. Next engineering requirement is independent source hypotheses/enrollments (or a validated target-conditioned audiovisual extractor), then discriminative cross-face/cross-source matching and shifted-audio/wrong-face controls. The current two-source separator cannot promise three separate speakers. Do not solve this by forcing three diarization labels or relaxing identity thresholds without measurements.
