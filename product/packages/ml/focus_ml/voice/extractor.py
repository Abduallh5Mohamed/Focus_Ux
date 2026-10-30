"""Extractors turn labelled regions into audio. Only the gated baseline exists
here: keep the target's solo speech, mute everyone else. Overlap extraction
is a later, replaceable implementation of the same interface."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from ..isolation_engines import fit_samples
from .types import SAMPLE_RATE, TARGET, LabelledRegion


class Extractor(Protocol):
    name: str

    def extract(self, samples: np.ndarray, regions: list[LabelledRegion]) -> np.ndarray: ...


def target_mask(n: int, regions, sr: int = SAMPLE_RATE, fade_ms: float = 10.0) -> np.ndarray:
    """1 inside target regions, 0 elsewhere, with raised-cosine ramps placed
    INSIDE the region edges so no other speaker's audio leaks through a fade."""
    spans = []
    for r in sorted((r for r in regions if r.label == TARGET), key=lambda r: r.start):
        a, b = max(0, int(round(r.start * sr))), min(n, int(round(r.end * sr)))
        if b <= a:
            continue
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    mask = np.zeros(n, dtype=np.float32)
    fade = int(sr * fade_ms / 1000)
    for a, b in spans:
        f = min(fade, (b - a) // 2)
        mask[a:b] = 1.0
        if f > 0:
            ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, f, endpoint=False))).astype(np.float32)
            if a > 0:               # no fade at the very start/end of the file
                mask[a:a + f] = ramp
            if b < n:
                mask[b - f:b] = ramp[::-1]
    return mask


class GatedBaseline:
    name = "gated_baseline"

    def __init__(self, fade_ms: float = 10.0):
        self.fade_ms = fade_ms

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32)
        out = x * target_mask(len(x), regions, fade_ms=self.fade_ms)
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))   # canonical length
