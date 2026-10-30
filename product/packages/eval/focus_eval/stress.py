"""Deterministic synthetic degradations for the limitations study (numpy only).

These are SYNTHETIC approximations: white-ish noise at a stated SNR and a
statistical room response (exponentially decaying noise). They show how the
pipeline degrades, not how it behaves in a real noisy or echoing room. Real
whisper, shout and room recordings must be added to the dataset by tag.
"""
from __future__ import annotations

import numpy as np

SR = 16000
CONDITIONS = {
    "noise_20db": {"kind": "noise", "snr_db": 20.0},
    "noise_10db": {"kind": "noise", "snr_db": 10.0},
    "noise_0db": {"kind": "noise", "snr_db": 0.0},
    "reverb_rt60_0.4s": {"kind": "reverb", "rt60_s": 0.4},
    "reverb_rt60_0.8s": {"kind": "reverb", "rt60_s": 0.8},
}


def _seed(name: str, seed: int) -> np.random.Generator:
    return np.random.default_rng([seed] + [ord(c) for c in name])


def add_noise(x, snr_db: float, rng) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    white = rng.standard_normal(len(x))
    spec = np.fft.rfft(white)
    spec /= np.sqrt(np.maximum(np.arange(len(spec)), 1))   # pink-ish: speech-like room noise
    noise = np.fft.irfft(spec, n=len(x))
    power = max(float((x ** 2).mean()), 1e-12)
    noise *= np.sqrt(power / max(float((noise ** 2).mean()), 1e-12)) / 10 ** (snr_db / 20)
    return x + noise


def add_reverb(x, rt60_s: float, rng, sr: int = SR) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    n = int(rt60_s * sr)
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * 10 ** (-3.0 * t / rt60_s)   # -60 dB at rt60
    ir[0] = 1.0                                               # direct path
    size = 1 << int(np.ceil(np.log2(len(x) + n)))
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[:len(x)]
    scale = np.sqrt(max(float((x ** 2).mean()), 1e-12) / max(float((wet ** 2).mean()), 1e-12))
    return wet * scale


def degrade(x, condition: str, seed: int = 0) -> np.ndarray:
    spec = CONDITIONS[condition]
    rng = _seed(condition, seed)
    out = add_noise(x, spec["snr_db"], rng) if spec["kind"] == "noise" else add_reverb(x, spec["rt60_s"], rng)
    peak = float(np.abs(out).max())
    return (out * (0.95 / peak) if peak > 0.95 else out).astype(np.float32)
