"""Pure windowing, crossfade merge and loudness helpers for separation.

The legacy product cut audio into back-to-back 2 s windows. Dolphin was tuned
with 4 s windows, and hard cuts leak at the seams. These helpers plan
overlapping windows (the last one is always full length, anchored to the end of
the clip), blend them with complementary sin^2 ramps and level the audio.
numpy is imported lazily so ``import focus_ml`` stays light.
"""
from __future__ import annotations

PRE_TARGET_RMS_DBFS = -23.0
POST_TARGET_RMS_DBFS = -20.0
PEAK_LIMIT = 0.97
MAX_PRE_GAIN_DB = 30.0
SILENCE_RMS = 1e-5


def plan_windows(
    n_samples: int, sample_rate: int, window_s: float, overlap: float = 0.5
) -> list[tuple[int, int]]:
    """Return (start, end) sample spans covering [0, n_samples).

    hop = window * (1 - overlap). A clip shorter than one window is a single
    span. With overlap 0 the legacy back-to-back spans (short tail) are returned.
    Otherwise the final span is shifted back so it is a full window
    instead of a short tail (short windows give the model too little context).
    """
    if n_samples <= 0:
        return []
    if window_s <= 0:
        raise ValueError("window_s must be positive")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("overlap must be in [0, 1)")
    window = max(1, int(round(window_s * sample_rate)))
    if n_samples <= window:
        return [(0, n_samples)]
    if overlap == 0.0:
        # Legacy direct mode: consecutive windows, short final window kept as is.
        return [(s, min(s + window, n_samples)) for s in range(0, n_samples, window)]
    hop = max(1, int(round(window * (1.0 - overlap))))
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        end = start + window
        if end >= n_samples:
            spans.append((n_samples - window, n_samples))
            break
        spans.append((start, end))
        start += hop
    return spans


def _ramp(length: int):
    import numpy as np

    return np.sin(0.5 * np.pi * (np.arange(length) + 0.5) / length) ** 2


def merge_windows(estimates, spans: list[tuple[int, int]], n_samples: int):
    """Crossfade-merge per-window estimates (1-D arrays) into one signal.

    Each window fades in over its overlap with the previous window and fades
    out over its overlap with the next; the result is normalised by the summed
    weights, so edges of the clip keep full weight and the seams have no click.
    """
    import numpy as np

    if len(estimates) != len(spans):
        raise ValueError("one estimate per span is required")
    out = np.zeros(n_samples, dtype=np.float64)
    weight = np.zeros(n_samples, dtype=np.float64)
    for i, ((start, end), est) in enumerate(zip(spans, estimates)):
        length = end - start
        est = np.asarray(est, dtype=np.float64)[:length]
        if len(est) != length:
            raise ValueError("estimate shorter than its window")
        w = np.ones(length, dtype=np.float64)
        if i > 0:
            fade_in = min(max(0, spans[i - 1][1] - start), length)
            if fade_in:
                w[:fade_in] *= _ramp(fade_in)
        if i < len(spans) - 1:
            fade_out = min(max(0, end - spans[i + 1][0]), length)
            if fade_out:
                w[length - fade_out:] *= _ramp(fade_out)[::-1]
        out[start:end] += est * w
        weight[start:end] += w
    np.divide(out, weight, out=out, where=weight > 0)
    return out.astype(np.float32)


def _rms(x) -> float:
    import numpy as np

    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def normalize_input(mix, target_dbfs: float = PRE_TARGET_RMS_DBFS):
    """Scale the mixture to a target RMS. Silence is returned unchanged.
    Returns (audio, gain_db)."""
    import numpy as np

    rms = _rms(mix)
    if rms < SILENCE_RMS:
        return mix, 0.0
    gain_db = min(target_dbfs - 20.0 * np.log10(rms), MAX_PRE_GAIN_DB)
    return (mix * np.float32(10.0 ** (gain_db / 20.0))).astype(np.float32), float(gain_db)


def normalize_output(est, target_dbfs: float = POST_TARGET_RMS_DBFS, peak: float = PEAK_LIMIT):
    """Level the isolated audio to a target RMS without clipping: the gain is
    reduced when needed so the peak stays at or under ``peak``."""
    import numpy as np

    rms = _rms(est)
    top = float(np.max(np.abs(est))) if len(est) else 0.0
    if rms < SILENCE_RMS or top == 0.0:
        return est, 0.0
    gain = min(10.0 ** (target_dbfs / 20.0) / rms, peak / top)
    return (est * np.float32(gain)).astype(np.float32), float(20.0 * np.log10(gain))
