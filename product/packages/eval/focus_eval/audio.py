"""Audio loading and isolation metrics (SI-SDR, lag alignment).

Ported from the legacy ``align_eval.py`` (sign convention verified there):
    lag < 0 -> estimate is LATE  -> trim the head of the estimate
    lag > 0 -> estimate is EARLY -> trim the head of the reference
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 16000
MAX_LAG = 800  # +-50 ms at 16 kHz
EDGE_WARN = 0.9  # warn when |lag| >= 90% of MAX_LAG


class AudioError(ValueError):
    pass


def load_audio(path: str | Path, sr: int = SR) -> np.ndarray:
    """Load a PCM WAV as mono float64, resampled linearly to ``sr``.

    Only integer PCM WAV is supported (convert other inputs with ffmpeg first).
    """
    try:
        with wave.open(str(path), "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"{path}: not a readable PCM WAV ({exc})") from exc
    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        ints = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float64) / (1 << 23)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise AudioError(f"{path}: unsupported sample width {width}")
    if channels > 1:
        data = data[: len(data) // channels * channels].reshape(-1, channels).mean(axis=1)
    if data.size == 0:
        raise AudioError(f"{path}: contains no samples")
    if rate != sr:
        n = int(round(len(data) * sr / rate))
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return data


def lag_of(est: np.ndarray, ref: np.ndarray, max_lag: int = MAX_LAG) -> tuple[int, bool]:
    """Lag in samples maximising sum(ref[n+lag] * est[n]), searched in +-max_lag."""
    max_lag = max(0, min(max_lag, min(len(est), len(ref)) - 1))
    nfft = 1 << int(np.ceil(np.log2(len(est) + len(ref))))
    corr = np.fft.irfft(np.fft.rfft(ref, nfft) * np.conj(np.fft.rfft(est, nfft)), nfft)
    lags = np.arange(-max_lag, max_lag + 1)
    lag = int(lags[int(np.argmax(corr[lags % nfft]))])
    edge = max_lag > 0 and abs(lag) >= EDGE_WARN * max_lag
    return lag, edge


def align(est: np.ndarray, ref: np.ndarray, max_lag: int = MAX_LAG):
    lag, edge = lag_of(est, ref, max_lag)
    if lag > 0:
        ref = ref[lag:]
    elif lag < 0:
        est = est[-lag:]
    n = min(len(est), len(ref))
    return est[:n], ref[:n], lag, edge


def si_sdr(est: np.ndarray, ref: np.ndarray) -> float:
    est = est - est.mean()
    ref = ref - ref.mean()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    t = a * ref
    e = est - t
    return float(10.0 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(e, e) + 1e-12)))


def aligned_si_sdr(est: np.ndarray, ref: np.ndarray) -> tuple[float, int, bool]:
    e, r, lag, edge = align(est, ref)
    if len(e) < 2:
        raise AudioError("signals too short to compare after alignment")
    return si_sdr(e, r), lag, edge
