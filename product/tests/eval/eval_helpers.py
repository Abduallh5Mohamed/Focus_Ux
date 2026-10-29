"""Synthetic fixtures for focus_eval tests (test-only signals, no real speech)."""
from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np

SR = 16000


def voice(pitch: float, seed: int, seconds: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    sig = sum(np.sin(2 * np.pi * pitch * k * t + rng.uniform(0, 6)) / k for k in range(1, 8))
    env = (0.5 + 0.5 * np.sin(2 * np.pi * (2 + seed) * t + seed)) ** 2
    return sig * env * 0.2 + rng.normal(0, 0.002, t.size)


def write_wav(path: Path, data: np.ndarray, rate: int = SR, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(data, -1, 1)
    pcm = (np.repeat(pcm[:, None], channels, axis=1) if channels > 1 else pcm[:, None])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((pcm * 32767).astype("<i2").tobytes())


def make_dataset(root: Path, status: str = "ready", status_b: str = "human_verified") -> dict:
    a, b = voice(150, 1), voice(230, 2)
    mix = a + b
    base = root / "clips" / "c1"
    write_wav(base / "mix.wav", mix)
    write_wav(base / "a_ref.wav", a)
    write_wav(base / "b_ref.wav", b)
    (base / "a.txt").write_text("أنا كنت معيدة في الجامعة", encoding="utf-8")
    (base / "b.txt").write_text("بشتغل دكتور", encoding="utf-8")
    src = {"description": "synthetic", "url": "local://test", "license": "test-only"}
    manifest = {
        "schema_version": 1,
        "dataset_id": "unit",
        "clips": [
            {
                "id": "c1", "status": status, "tags": ["overlap"],
                "mix_audio": "clips/c1/mix.wav", "source": src,
                "speakers": [
                    {"id": "a", "ref_audio": "clips/c1/a_ref.wav", "transcript": "clips/c1/a.txt",
                     "transcript_status": "human_verified"},
                    {"id": "b", "ref_audio": "clips/c1/b_ref.wav", "transcript": "clips/c1/b.txt",
                     "transcript_status": status_b},
                ],
                "targets": ["a", "b"],
            },
            {"id": "c2", "status": "template", "tags": [], "speakers": [], "targets": []},
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {"a": a, "b": b, "mix": mix}


def make_run(root: Path, sigs: dict, label: str = "run", swap: bool = False,
             drop_b: bool = False, text_a: str = "أنا كنت معيدة في الجامعة",
             text_b: str = "بشتغل دكتور") -> Path:
    rng = np.random.default_rng(9)
    ea, eb = (sigs["b"], sigs["a"]) if swap else (sigs["a"], sigs["b"])
    base = root / "c1"
    write_wav(base / "a.wav", ea + rng.normal(0, 0.001, ea.size))
    if not drop_b:
        write_wav(base / "b.wav", eb + rng.normal(0, 0.001, eb.size))
    (base / "a.txt").write_text(text_a, encoding="utf-8")
    (base / "b.txt").write_text(text_b, encoding="utf-8")
    (root / "run.json").write_text(json.dumps({"label": label}), encoding="utf-8")
    return root
