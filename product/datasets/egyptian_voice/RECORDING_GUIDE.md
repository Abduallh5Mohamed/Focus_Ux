# Recording guide — Egyptian voice set (audio only)

Goal: real Egyptian Arabic recordings that let us measure whether the pipeline can tell
people apart and keep only the chosen voice. Speak naturally (conversation, reading, a story);
the content does not matter and is never analysed.

**Before recording:** every person signs `CONSENT_FORM.md`. Use a phone, WAV or any format ffmpeg reads
(`.wav` preferred for solo files; `.mp4/.mov` allowed). Aim for **at least 5 speakers**, mixed men and women
(minimum 3), including at least two with similar voices.

## 1. Solo recordings (`kind: "solo"`) — required, the ground truth
Each person alone, nobody else talking, 1–2 minutes each in total, in several files:
| Condition | Values to cover (at least one file each) |
|---|---|
| Volume | `quiet`, `normal`, `loud` (no clipping: if the phone shows red, move back) |
| Distance | near (about 30 cm) and far (about 1.5–2 m) → `distance_m` |
| Noise | `quiet` room, `street`/`traffic`/`cafe`/`fan` background |
| Room | `small` room, `large` room, `echoey` (tiles, empty room), `car` |
Silence between sentences is fine. Do not whisper, shout or imitate other voices.

## 2. Real overlap (`kind: "overlap"`)
- **2 people**: talk over each other for several seconds, 30–60 s per clip.
- **3+ people**: a group conversation with interruptions, 30–60 s.
Real overlap has no per-person reference, so each clip needs an **annotation** file
`{"segments": [{"speaker": "S01", "start": 0.0, "end": 3.2}, ...]}` (who spoke when, by listening).
Also record each person solo (section 1), in the same room if possible.

## 3. Target leaves the frame (`kind: "leaves_frame"`)
Video with 2–3 people; the future target speaks, walks out of view and keeps talking, then returns.
Only the audio is used; the video is kept to prepare later (camera) tests. Add an annotation like section 2.

## Manifest
Copy `manifest.template.json` to `manifest.json` and describe every file (id, kind, file, speakers,
consent_ids, conditions). Check with:

    python product/tools/validate_voice_recordings.py product/datasets/egyptian_voice

Errors (missing file, unsigned consent, solo with two speakers, no annotation) must be fixed.
Warnings show missing coverage (speakers, volumes, distances, noise, rooms, overlap sizes).

## Ground-truth mixes from the solo files
    python product/tools/three_speaker_set.py --solo-dir <folder of S01*.wav,S02*.wav,...> \
        --out <mix folder> --speakers-per-mix 3 --overlap-s 1.5 [--snr-db 15]
Name solo files `<speaker>__<anything>.wav` (e.g. `S01__quiet_near.wav`). The first 12 s of each speaker is
set aside as the separate enrollment recording. Files in `audio/` and `annotations/` stay out of Git
(see `.gitignore`); keep them in shared storage.
