"""Run Demucs on one file and keep the vocals stem.

This script runs in the SEPARATE Demucs environment (torch + demucs), not in
the product's ML environment: ``focus_ml`` stays numpy-only. The product calls
it through ``focus_ml.voice.music.DemucsSeparator``.

    <demucs python> product/tools/demucs_separate.py in.wav out.wav \
        [--model htdemucs] [--device cpu]

Nothing is downloaded here unless the weights are missing AND
``--allow-download`` is passed: the same "no silent download" rule as the
ClearerVoice engines.
"""
from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _configure_cache() -> Path:
    """Keep every Demucs/torch artifact inside the project tree."""
    home = os.environ.get("FOCUS_DEMUCS_DIR") or str(PROJECT_ROOT / "model-assets" / "demucs")
    path = Path(home)
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TORCH_HOME", str(path / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(path / "cache"))
    os.environ.setdefault("HF_HOME", str(path / "hf"))
    return path


def read_wav(path: str):
    """PCM16/PCM32 mono or stereo WAV -> (float32 [channels, samples], rate).

    Deliberately avoids torchaudio's I/O: torchaudio 2.11 routes load/save
    through TorchCodec, which is an extra native dependency this runner does
    not need. The product always hands us a plain PCM16 WAV."""
    with wave.open(path, "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise SystemExit(f"unsupported WAV sample width: {width}")
    return data.reshape(-1, channels).T, rate


def write_wav(path: str, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(samples.shape[0])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.T.tobytes())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--model", default=os.environ.get("FOCUS_DEMUCS_MODEL", "htdemucs"))
    ap.add_argument("--device", default=os.environ.get("FOCUS_DEMUCS_DEVICE", "cpu"))
    ap.add_argument("--allow-download", action="store_true")
    args = ap.parse_args(argv)

    home = _configure_cache()
    if not args.allow_download:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    try:
        import torch
        import torchaudio.functional as F
        from demucs.apply import apply_model
        from demucs.pretrained import get_model
    except ImportError as exc:  # pragma: no cover - environment dependent
        print(f"demucs environment incomplete: {exc}", file=sys.stderr)
        return 3

    try:
        model = get_model(args.model)
    except Exception as exc:  # noqa: BLE001 - weights missing / no network
        print(f"model {args.model!r} unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"weights are expected under {home}", file=sys.stderr)
        return 4
    model.eval()

    data, sr = read_wav(args.src)
    wav = torch.from_numpy(np.ascontiguousarray(data))
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)                       # htdemucs is stereo-in
    if sr != model.samplerate:
        wav = F.resample(wav, sr, model.samplerate)

    reference = wav.mean(0)
    scale = reference.std() + 1e-8
    normalised = (wav - reference.mean()) / scale
    with torch.no_grad():
        sources = apply_model(model, normalised[None], device=args.device,
                              split=True, overlap=0.25, progress=True)[0]
    sources = sources * scale + reference.mean()

    vocals = sources[model.sources.index("vocals")].mean(0, keepdim=True)
    if model.samplerate != sr:
        vocals = F.resample(vocals, model.samplerate, sr)
    write_wav(args.dst, vocals.clamp(-1.0, 1.0).numpy(), sr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
