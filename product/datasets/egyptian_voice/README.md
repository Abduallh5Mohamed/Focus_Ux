# Egyptian voice recording kit

Audio-only recordings for the voice pipeline (`docs/VOICE_PIPELINE.md`). Separate from the older
`egyptian_eval` set, which scores isolation output against transcripts.

- `CONSENT_FORM.md` — sign before recording (Arabic/English)
- `RECORDING_GUIDE.md` — what to record
- `manifest.template.json` — manifest format; validate with `product/tools/validate_voice_recordings.py`

No recordings are committed. `audio/` and `annotations/` are ignored by Git.
