"""Pick which separated voice belongs to the chosen face by lip/audio sync.

Pure CPU/numpy logic. Lip motion only *chooses* the speaker here; it does not
do the isolation (that is the separation model's job).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MIN_SCORE = 0.15      # best score below this: confidence is weak
MIN_MARGIN = 0.05     # best minus runner-up below this: ambiguous
MAX_LAG_FRAMES = 3    # +-120 ms at 25 fps absorbs small A/V offsets
SILENT_RMS = 1e-4


@dataclass
class SourceScore:
    index: int
    score: float
    lag_frames: int = 0
    rms: float = 0.0


@dataclass
class Selection:
    index: int
    confidence: str  # "ok" | "weak" | "ambiguous"
    scores: list[SourceScore] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "selected_source": self.index, "confidence": self.confidence,
            "sources": [
                {"index": s.index, "score": round(s.score, 4),
                 "lag_frames": s.lag_frames, "rms": round(s.rms, 6)}
                for s in self.scores
            ],
        }


def mouth_openness(landmarks) -> np.ndarray:
    """Per-frame inner-lip opening / mouth width from 68-point landmarks."""
    values = []
    for lm in landmarks:
        lm = np.asarray(lm, dtype=np.float64)
        top = lm[[61, 62, 63]].mean(axis=0)
        bottom = lm[[67, 66, 65]].mean(axis=0)
        width = np.linalg.norm(lm[54] - lm[48])
        values.append(np.linalg.norm(top - bottom) / width if width > 0 else 0.0)
    return np.asarray(values, dtype=np.float64)


def energy_envelope(samples, sample_rate: int, fps: int, n_frames: int) -> np.ndarray:
    """RMS of the audio under each video frame."""
    x = np.asarray(samples, dtype=np.float64).reshape(-1)
    hop = sample_rate / fps
    out = np.zeros(n_frames, dtype=np.float64)
    for i in range(n_frames):
        a, b = int(round(i * hop)), int(round((i + 1) * hop))
        seg = x[a:b]
        out[i] = float(np.sqrt(np.mean(seg * seg))) if seg.size else 0.0
    return out


def _z(v: np.ndarray):
    sd = v.std()
    return None if sd < 1e-9 else (v - v.mean()) / sd


def sync_score(mouth, envelope, max_lag: int = MAX_LAG_FRAMES) -> tuple[float, int]:
    """Best Pearson correlation of mouth opening vs audio energy over small lags."""
    mouth = np.asarray(mouth, dtype=np.float64)
    envelope = np.asarray(envelope, dtype=np.float64)
    n = min(len(mouth), len(envelope))
    if n < 8:
        return 0.0, 0
    mouth, envelope = mouth[:n], envelope[:n]
    best, best_lag = -1.0, 0
    for lag in range(-max_lag, max_lag + 1):
        m = mouth[lag:] if lag >= 0 else mouth[:lag]
        e = envelope[:n - lag] if lag >= 0 else envelope[-lag:]
        zm, ze = _z(m), _z(e)
        if zm is None or ze is None:
            continue
        c = float(np.mean(zm * ze))
        if c > best:
            best, best_lag = c, lag
    return (best if best > -1.0 else 0.0), best_lag


def score_sources(sources, sample_rate: int, mouth, fps: int = 25) -> list[SourceScore]:
    scores = []
    for i, src in enumerate(sources):
        env = energy_envelope(src, sample_rate, fps, len(mouth))
        rms = float(np.sqrt(np.mean(np.asarray(src, dtype=np.float64) ** 2))) if len(src) else 0.0
        if rms < SILENT_RMS:
            scores.append(SourceScore(i, 0.0, 0, rms))
            continue
        score, lag = sync_score(mouth, env)
        scores.append(SourceScore(i, score, lag, rms))
    return scores


def choose_source(scores: list[SourceScore], min_score: float = MIN_SCORE,
                  min_margin: float = MIN_MARGIN) -> Selection:
    if not scores:
        raise ValueError("no separated sources to choose from")
    ranked = sorted(scores, key=lambda s: s.score, reverse=True)
    best = ranked[0]
    warnings, confidence = [], "ok"
    if best.score < min_score:
        confidence = "weak"
        warnings.append(
            f"weak lip-sync confidence (best score {best.score:.2f} < {min_score}); "
            "the chosen voice may not be the selected person"
        )
    elif len(ranked) > 1 and best.score - ranked[1].score < min_margin:
        confidence = "ambiguous"
        warnings.append(
            f"two separated voices matched the lips almost equally "
            f"({best.score:.2f} vs {ranked[1].score:.2f}); the choice may be wrong"
        )
    return Selection(best.index, confidence, list(scores), warnings)
