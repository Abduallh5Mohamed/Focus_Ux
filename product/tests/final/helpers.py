"""Tone-based dataset and engine for the final-evaluation tests (no model weights)."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

from fakes import FakeEmbedder, SR, tone
from focus_ml.isolation_engines import write_wav
from focus_ml.voice.diarizer import from_turns
from focus_ml.voice.engine import AudioOnlyEngine
from focus_ml.voice.types import Segment

TURNS = {"a": [(0, 6), (12, 18)], "b": [(6, 12), (16, 18)]}
FREQ = {"a": 220.0, "b": 440.0}
TOTAL = 18.0


class ToneDiarizer:
    """Labels each 0.5 s window by which tones are present, so it works on a mix and on a reference."""
    model_id = "tone-fake"

    def diarize(self, samples):
        win, turns = int(0.5 * SR), []
        for i in range(len(samples) // win):
            seg = np.asarray(samples[i * win:(i + 1) * win], dtype=np.float64)
            spec = np.abs(np.fft.rfft(seg, n=SR))
            for name, f in (("S1", 220), ("S2", 440)):
                if spec[f - 3:f + 4].sum() > 200:
                    turns.append(Segment(i * 0.5, (i + 1) * 0.5, name))
        merged = []
        for t in turns:
            if merged and merged[-1].speaker == t.speaker and abs(merged[-1].end - t.start) < 1e-9:
                merged[-1] = Segment(merged[-1].start, t.end, t.speaker)
            else:
                merged.append(t)
        return from_turns(merged)

    def unload(self):
        pass


def make_engine():
    return AudioOnlyEngine(ToneDiarizer(), FakeEmbedder())


def make_dataset(root: Path, *, with_video=True, tags=("face_disappears",)) -> Path:
    ref = {}
    for spk, spans in TURNS.items():
        x = np.zeros(int(TOTAL * SR), dtype=np.float32)
        for a, b in spans:
            x[int(a * SR):int(b * SR)] += tone(FREQ[spk], b - a)
        ref[spk] = x
    mix = ref["a"] + ref["b"]
    base = root / "clips" / "c1"
    base.mkdir(parents=True)
    write_wav(str(base / "mix.wav"), mix, SR)
    for spk in ref:
        write_wav(str(base / f"{spk}_ref.wav"), ref[spk], SR)
    if with_video:
        done = subprocess.run(
            [shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "testsrc=s=320x240:r=25:d=18", "-i", str(base / "mix.wav"), "-c:v", "mpeg4", "-c:a", "pcm_s16le",
             "-shortest", str(base / "video.avi")], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    for s_ in ("a", "b"):
        (base / f"{s_}.txt").write_text("نص تجريبي", encoding="utf-8")
    manifest = {"schema_version": 1, "dataset_id": "tone-unit", "clips": [{
        "id": "c1", "status": "ready", "tags": list(tags), "mix_audio": "clips/c1/mix.wav",
        **({"video": "clips/c1/video.avi"} if with_video else {}),
        "source": {"description": "synthetic tones", "url": "local://test", "license": "test-only"},
        "speakers": [{"id": s, "ref_audio": f"clips/c1/{s}_ref.wav", "transcript": f"clips/c1/{s}.txt",
                      "transcript_status": "provisional_asr"} for s in ("a", "b")],
        "targets": ["a", "b"]}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root
