"""One extraction interface for overlapping speech, plus shared helpers.

An extractor takes a batch of mixture windows (16 kHz mono float32), the target
voiceprint and the target's enrollment audio, and returns the target waveform
for each window with exactly the window's length.

Honest labels (``CandidateInfo.mechanism``):
  * ``target_conditioned``  - the model itself is conditioned on the enrollment.
  * ``blind_separation_then_voiceprint_selection`` - the model separates all
    voices without knowing who the target is; a separate voiceprint step then
    picks one output. These are NEVER described as voice-conditioned.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..errors import ModelUnavailableError
from ..isolation_engines import fit_samples
from ..voice.match import cosine
from ..voice.types import SAMPLE_RATE, Voiceprint

TARGET_CONDITIONED = "target_conditioned"
BLIND_THEN_SELECT = "blind_separation_then_voiceprint_selection"
SILENT_RMS = 1e-4
ENROLL_MAX_S = 10.0


class BlockedError(ModelUnavailableError):
    """A candidate cannot run here. ``kind`` is machine-readable, ``evidence``
    is the concrete observation (missing file, import error, OOM message)."""

    KINDS = ("missing_weights", "missing_package", "broken_code", "out_of_memory", "not_applicable")

    def __init__(self, message: str, kind: str, evidence: str = ""):
        if kind not in self.KINDS:
            raise ValueError(f"unknown blocker kind {kind!r}")
        super().__init__(message, retryable=False, detail=evidence)
        self.kind, self.evidence = kind, evidence

    def as_record(self) -> dict:
        return {"kind": self.kind, "message": self.message, "evidence": self.evidence}


@dataclass(frozen=True)
class CandidateInfo:
    name: str
    title: str
    mechanism: str
    code_licence: str
    weights_licence: str
    model_rate: int                      # sample rate the model works at
    categories: tuple[str, ...] = ("overlap_2", "overlap_3plus")
    version: str = ""                    # pinned code revision / checkpoint id
    notes: str = ""
    fp16_note: str = ""
    # Rough initial VRAM model used only to pick a first batch size; an
    # out-of-memory error halves the batch, and peak VRAM is measured and logged.
    vram_base_mib: float = 600.0
    vram_per_window_s_mib: float = 60.0

    def as_dict(self) -> dict:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


# ----------------------------------------------------------------- helpers
def _lowpass_fir(cutoff: float, taps: int = 63) -> np.ndarray:
    n = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff * n) * np.hamming(taps)
    return (h / h.sum()).astype(np.float64)


def resample(x, sr_from: int, sr_to: int) -> np.ndarray:
    """Anti-aliased resampling. scipy's polyphase filter when present, otherwise
    a windowed-sinc low-pass followed by linear interpolation."""
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    if sr_from == sr_to or len(x) == 0:
        return x
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(sr_from, sr_to)
        return resample_poly(x, sr_to // g, sr_from // g).astype(np.float32)
    except ImportError:
        pass
    if sr_to < sr_from:
        x = np.convolve(x.astype(np.float64), _lowpass_fir(0.5 * sr_to / sr_from), mode="same")
    return fit_samples(x, sr_from, sr_to, max(1, round(len(x) * sr_to / sr_from)))


def trim_enrollment(enrollment, max_s: float = ENROLL_MAX_S, sr: int = SAMPLE_RATE) -> np.ndarray:
    """At most ``max_s`` seconds, taken around the middle (the ends are often noisy)."""
    e = np.asarray(enrollment, dtype=np.float32).reshape(-1)
    n = int(max_s * sr)
    if len(e) <= n:
        return e
    a = (len(e) - n) // 2
    return e[a:a + n]


def rms(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def vram_reset() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except ImportError:
        pass


def vram_peak_mib() -> float | None:
    try:
        import torch
        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 2**20, 1)
    except ImportError:
        pass
    return None


def is_oom(exc: BaseException) -> bool:
    return type(exc).__name__ == "OutOfMemoryError" or "out of memory" in str(exc).lower()


def select_by_voiceprint(sources: Sequence[np.ndarray], voiceprint: Voiceprint, embedder) -> dict:
    """Pick the separated source whose voice is closest to the voiceprint.
    Silent sources score -1. Returns index, per-source cosine scores, margin."""
    if voiceprint.embedder != embedder.name:
        raise ValueError(f"voiceprint was made with {voiceprint.embedder!r}, not {embedder.name!r}")
    if not len(sources):
        raise ValueError("no separated sources to choose from")
    scores = []
    for s in sources:
        scores.append(-1.0 if rms(s) < SILENT_RMS else cosine(voiceprint.vector, embedder.embed(s)))
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    margin = scores[order[0]] - scores[order[1]] if len(order) > 1 else None
    return {"index": order[0], "scores": [round(s, 4) for s in scores],
            "margin": None if margin is None else round(margin, 4)}


# ------------------------------------------------------------- base classes
class OverlapExtractor:
    """Subclasses implement ``_load``, ``_extract_batch`` and ``check_ready``."""

    info: CandidateInfo

    def __init__(self, device: str = "cpu", fp16: bool = True):
        self.device = device
        self.use_fp16 = bool(fp16) and device.startswith("cuda")
        self.fp16_fallbacks = 0
        self.loaded = False
        self.last_details: list[dict] = []   # one entry per window of the last batch

    # --- lifecycle (one extractor resident at a time)
    def check_ready(self) -> None:
        raise NotImplementedError

    def load(self) -> None:
        if not self.loaded:
            self.check_ready()
            self._load()
            self.loaded = True

    def unload(self) -> None:
        self._unload()
        self.loaded = False
        from ..voice.gpu import release_gpu
        release_gpu()

    def _load(self) -> None: ...
    def _unload(self) -> None: ...

    # --- sizing
    def max_batch(self, window_s: float, vram_budget_mib: float) -> int:
        i = self.info
        per = max(1.0, i.vram_per_window_s_mib * window_s)
        return max(1, int((vram_budget_mib - i.vram_base_mib) // per))

    # --- precision: fp16 on CUDA, with an fp32 retry on NaN/Inf or a numeric error
    def _autocast(self):
        if self.use_fp16:
            from ..voice.gpu import fp16_if_supported
            return fp16_if_supported(self.device)
        return contextlib.nullcontext()

    def _guarded(self, fn):
        try:
            with self._autocast():
                out = fn()
            if self.use_fp16 and not _all_finite(out):
                raise FloatingPointError("fp16 produced NaN/Inf")
            return out
        except Exception as exc:
            if not self.use_fp16 or is_oom(exc):
                raise
            self.use_fp16 = False
            self.fp16_fallbacks += 1
            return fn()

    # --- the interface
    def extract_batch(self, windows: Sequence[np.ndarray], voiceprint: Voiceprint,
                      enrollment: np.ndarray) -> list[np.ndarray]:
        """Target waveform for each mixture window (same length as the window)."""
        self.load()
        wins = [np.asarray(w, dtype=np.float32).reshape(-1) for w in windows]
        if not wins:
            return []
        outs = self._extract_batch(wins, voiceprint, np.asarray(enrollment, dtype=np.float32).reshape(-1))
        if len(outs) != len(wins):
            raise RuntimeError(f"{self.info.name} returned {len(outs)} outputs for {len(wins)} windows")
        return [fit_samples(o, SAMPLE_RATE, SAMPLE_RATE, len(w)) for o, w in zip(outs, wins)]

    def extract(self, window, voiceprint: Voiceprint, enrollment) -> np.ndarray:
        return self.extract_batch([window], voiceprint, enrollment)[0]

    def _extract_batch(self, windows, voiceprint, enrollment) -> list[np.ndarray]:
        raise NotImplementedError


class BlindSelectExtractor(OverlapExtractor):
    """Blind separation, then voiceprint selection of one output per window."""

    def __init__(self, embedder, device: str = "cpu", fp16: bool = True):
        super().__init__(device, fp16)
        self.embedder = embedder

    def _separate_batch(self, windows: list[np.ndarray]) -> list[list[np.ndarray]]:
        """For each window the list of separated sources (16 kHz, window length)."""
        raise NotImplementedError

    def _extract_batch(self, windows, voiceprint, enrollment):
        per_window = self._separate_batch(windows)
        outs, self.last_details = [], []
        for w, sources in zip(windows, per_window):
            sources = [fit_samples(s, SAMPLE_RATE, SAMPLE_RATE, len(w)) for s in sources]
            pick = select_by_voiceprint(sources, voiceprint, self.embedder)
            self.last_details.append({"n_sources": len(sources), **pick})
            outs.append(sources[pick["index"]])
        return outs


def _all_finite(obj) -> bool:
    if isinstance(obj, (list, tuple)):
        return all(_all_finite(o) for o in obj)
    try:
        return bool(np.all(np.isfinite(np.asarray(obj))))
    except TypeError:
        return True


@dataclass
class CandidateStatus:
    name: str
    ready: bool
    blocker: dict | None = None
    info: dict = field(default_factory=dict)
