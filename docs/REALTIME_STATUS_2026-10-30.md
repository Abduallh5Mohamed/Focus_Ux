# Real-time verification — 2026-10-30

Verdict: **not accepted for real-time conversation**. Upload completed with a real isolated WAV after two fixes; transcription failed independently. Live/chunk infrastructure exists, but no successful real GPU camera-to-play acceptance run has been demonstrated.

## Execution evidence

- Source HEAD at audit: `15de736c01a57f72d787eb5eb07493c81cb29fda`, plus local audit fixes below.
- Local web :5000, API :8000, outbound GPU worker. Loopback testing is not public deployment.
- Existing RTX 3060 Laptop 6 GB; original cached models and legacy Python environment, no model downloads or legacy edits.
- Actual input: 6-second two-person video made from existing gt5 clips and their mixture. References were not used as inference outputs.
- Upload accepted (201); both faces detected; selected second/right face.
- First real extraction failed because AAC decoding yielded 96,256 samples (6.016 seconds), while the video had 150 frames (6 seconds). A final 256-sample model window had no remaining mouth frames.
- After tail-context correction, a real 192,556-byte WAV was persisted at `runtime/audit_20261030/selected_second_face.wav` (16 kHz mono, 6.016 seconds).
- In that run, processing started at elapsed 2.375 s and reached transcription at 76.422 s: approximately **74.047 s for the extraction stage boundary interval**, or **12.34 times the 6-second content duration**. This includes worker scheduling/transfer and face preparation; it is not isolated neural-forward timing or browser capture-to-play latency. The session worker was already model-loaded; no valid comparative optimized benchmark was performed.
- Transcription returned HTTP 400 and job did not finalize within the 300-second observation. Thus the full upload workflow did **not** pass end to end, despite the generated audio. Root cause of the original transcription rejection remains unconfirmed.
- Error reporting also had a concrete bug: HTTPError.code is numeric (400), but the API requires a string provider error code. This made reporting the transcription failure fail too. Corrected to PROCESSING_FAILED for non-string codes; regression tests pass. Full-stack rerun confirmed recovery: job completed with audio ready and transcript failed.
- Post-fix rerun: faces ready at 3.469 s, extraction started at 3.500 s, transcription at 81.235 s, job completed at 89.047 s, WAV downloaded at 89.079 s. Extraction interval 77.735 s for 6 seconds (12.96x); total workflow 89.094 s. These are upload-path measurements, not measured live RTF. Unauthenticated download returned 401. Detailed evidence: `runtime/audit_20261030/actual_upload_report.json`.
- API and worker were restarted after the stuck run. Models require startup time; verify `/healthz` connected=true before uploading.

## Changes and checks

### Actual file-paced live diagnostic

Executed `product/tools/live_gate.py --api http://127.0.0.1:8000 --video runtime/audit_20261030/two_speaker_6s.mp4 --face-index 1 --timeout-s 90` against the real worker. Log: `runtime/audit_20261030/live_gate.log`.

- Four chunks ingested, three ready, one unusable, zero missing/duplicates, queue depth 3.
- **Measured chunk-processing RTF 14.5099** (gate target <=0.8).
- Overload at sequence 3; fallback to record-then-process.
- Server received-to-ready median 64.275 s / p95 87.373 s. These exclude capture and browser playback.
- Gate **internal_only**, with failures for speed, overload, unusable chunk, short duration, absent browser capture-to-play and absent quality comparison.
- Tool metadata reports 8 s (four nominal 2-second chunks), although fixture content is 6 s. Its final partial-chunk metadata needs correction before using it for precise duration/throughput comparisons. The above values are recorded as emitted, not represented as a clean 60-second benchmark. Investigate the unusable final chunk; do not assume it is model quality failure.

This directly confirms that the present live pipeline does not meet its own activation gate. It does not measure physical camera-to-ear latency.

- `focus_ml/window_plan.py`: borrow past context for a tiny final tail, write only previously unproduced samples, reject genuinely insufficient visual input. No synthetic ROI frames or dropped audio.
- `focus_ml/adapter.py`: use window plan. Original engine/weights unchanged.
- `tools/windows_worker.py`: normalize failure codes before posting an error.
- Backend suite: 243 passed, 1 skipped, 2 setup errors. The two errors involved Windows environment-variable length limits from giant binary pytest parameter IDs; not established application failures.
- Live/worker targeted suite with ffmpeg available: 35 passed.
- Tail/timing/worker suite: 42 passed before error-code tests were added.
- Latest dedicated tail/error-code regression suite: 13 passed.
- Combined worker/tail/timing suite after both fixes: 45 passed; changed Python modules compile successfully.
- Frontend with installed Vitest 2.1.9: 62 passed, 5 failed due unsupported `toHaveBeenCalledExactlyOnceWith`. Manifest requests newer tooling; resolve dependency/matcher mismatch before claiming a green frontend suite.
- Counts overlap; do not add them together.

## Current milestones

| Milestone | Verified status |
|---|---|
| Local API + UI + GPU bridge | Ran together |
| Two-face detection and right-face selection | Ran with real input |
| Actual isolated audio output | Generated after tail fix; quality not yet validated |
| Upload job completion including transcript failure recovery | Passed post-fix; transcription itself still fails |
| Live capture/chunk/queue implementation | Present; real file-paced diagnostic ran with overload and an unusable chunk |
| Sustained real-time GPU processing | Failed short diagnostic gate; measured RTF 14.5099 |
| Browser capture-to-play p95 | Not measured |
| 60-second moving-face session / overload / reconnect | Acceptance run outstanding |
| Cellular glasses round trip | Not tested; separate hardware development |

## Next work in priority order

1. Preserve the passing upload regression and diagnose actual ASR HTTP 400. Audio-ready/final-state recovery and ownership denial now pass.
2. Propagate adapter timings (detect, landmarks, mouth ROI, separation, transfers) through the worker diagnostics. Profile warmed repeated runs on the same sample. Do not infer bottleneck solely from total elapsed time.
3. Evaluate existing face-preparation optimizations against reference: sparse landmarks/detection, target-only work and persistent tracking where valid. Compare same-content quality, speaker identity and audio continuity before promoting defaults.
4. Correct the file trial's partial-chunk duration metadata and investigate the unusable final chunk, then rerun a longer trial. Current short trial exposed RTF 14.5099 and overload. Avoid rebuilding full face state for each chunk where safely reusable. Keep bounded queues and stale-output handling.
5. Run browser camera trial for at least 60 seconds, with motion/face loss. Measure actual capture-to-play p95 including chunk collection, network, inference and playback. Existing gate asks processing RTF <=0.8 and p95 <=3 s; this gate itself is not proof of comfortable conversational hearing assistance.
6. Compare isolated sound to mixture and references (evaluation only), check artifacts/identity, and conduct user listening trials. If profiling shows model compute alone misses budget, evaluate a lighter streaming alternative before optimizing UI further.

Keep the user-facing claim at experimental upload/chunk processing until measured gates pass. No percentage-complete claim is supported by this audit.
