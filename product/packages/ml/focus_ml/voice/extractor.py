"""Extractors turn labelled regions into audio.

Two mask baselines live here, both of them plain DSP (no model):

``GatedBaseline``
    1 inside the target's solo speech, 0 everywhere else. This is what the
    first shipped build used. Measured on a real job it produced digital
    silence for 41.7 % of the timeline: the background bed stopped dead for
    up to 8 s at a time and came back at full level under speech, which
    sounds like a broken file.

``DuckedBaseline``
    The default now. The target stays at unity and everything else is ducked
    to ``floor_db`` (-12 dB) with a 30 ms raised-cosine ramp, so the bed is
    attenuated instead of switched off: no digital silence, no pumping. It is
    still a gate - it does not separate overlapping sources. Removing the bed
    *under* speech needs a real separator model; see
    docs/AUDIO_ISOLATION_DIAGNOSIS.md.

Overlap extraction is a later, replaceable implementation of the same
interface."""
from __future__ import annotations

import os
from typing import Protocol

import numpy as np

from ..isolation_engines import fit_samples
from .types import SAMPLE_RATE, TARGET, LabelledRegion

EXTRACTOR_CHOICES = ("ducked", "gated", "music", "separation")
DEFAULT_EXTRACTOR = "ducked"
DEFAULT_FLOOR_DB = -12.0
DEFAULT_FADE_MS = 30.0
# Diarization splits one speaker's turn at every short pause: 128 of 161 gaps
# between target spans on a real job were < 100 ms. Bridging them keeps the bed
# steady through a speaker's own pauses instead of pumping 160 times.
DEFAULT_BRIDGE_MS = 250.0


class Extractor(Protocol):
    name: str

    def extract(self, samples: np.ndarray, regions: list[LabelledRegion]) -> np.ndarray: ...


def target_mask(n: int, regions, sr: int = SAMPLE_RATE, fade_ms: float = 10.0,
                floor: float = 0.0, bridge_ms: float = 0.0) -> np.ndarray:
    """1 inside target regions, ``floor`` elsewhere, with raised-cosine ramps
    placed INSIDE the region edges so no other speaker's audio leaks through a
    fade. ``floor=0`` is the hard gate; ``floor=10**(-12/20)`` ducks the
    background instead of muting it.

    ``bridge_ms`` treats two target spans separated by less than that as one
    span. Diarization splits one speaker's turn at every short pause: on a real
    job 128 of the 161 gaps between target spans were shorter than 100 ms, so
    the bed was being ducked and restored ~160 times - audible as pumping even
    though no sample was ever silent. Bridging at 250 ms collapses those to 25.
    """
    if not 0.0 <= floor <= 1.0:
        raise ValueError("floor must be in [0, 1]")
    if bridge_ms < 0.0:
        raise ValueError("bridge_ms must not be negative")
    bridge = int(sr * bridge_ms / 1000)
    spans = []
    for r in sorted((r for r in regions if r.label == TARGET), key=lambda r: r.start):
        a, b = max(0, int(round(r.start * sr))), min(n, int(round(r.end * sr)))
        if b <= a:
            continue
        if spans and a - spans[-1][1] <= max(bridge, 0):
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    mask = np.full(n, float(floor), dtype=np.float32)
    fade = int(sr * fade_ms / 1000)
    for a, b in spans:
        f = min(fade, (b - a) // 2)
        mask[a:b] = 1.0
        if f > 0:
            ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, f, endpoint=False))).astype(np.float32)
            if a > 0:               # no fade at the very start/end of the file
                mask[a:a + f] = floor + (1.0 - floor) * ramp
            if b < n:
                mask[b - f:b] = floor + (1.0 - floor) * ramp[::-1]
    return mask


class GatedBaseline:
    name = "gated_baseline"

    def __init__(self, fade_ms: float = 10.0):
        self.fade_ms = fade_ms

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32)
        out = x * target_mask(len(x), regions, fade_ms=self.fade_ms)
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))   # canonical length


class DuckedBaseline:
    """Target at unity, everything else ducked to ``floor_db`` (never to zero).

    Why this exists: the hard gate writes exact digital silence outside the
    target's speech. On a real job that was 41.7 % of the file and 18 separate
    gaps (longest 8.0 s) cut out of a continuous background bed, so the bed
    stopped dead and restarted at full level. Ducking keeps the timeline
    continuous - the bed is attenuated, not switched off - while the target
    keeps its full level.

    It is still a gate: it cannot remove a bed that overlaps the target's
    speech. That needs a separator model, which this extractor does not claim
    to be.
    """

    name = "ducked_baseline"

    def __init__(self, floor_db: float = DEFAULT_FLOOR_DB, fade_ms: float = DEFAULT_FADE_MS,
                 bridge_ms: float = DEFAULT_BRIDGE_MS):
        if not -60.0 <= floor_db <= 0.0:
            raise ValueError("floor_db must be in [-60, 0]")
        if not 0.0 < fade_ms <= 200.0:
            raise ValueError("fade_ms must be in (0, 200]")
        if not 0.0 <= bridge_ms <= 2000.0:
            raise ValueError("bridge_ms must be in [0, 2000]")
        self.floor_db = float(floor_db)
        self.fade_ms = float(fade_ms)
        self.bridge_ms = float(bridge_ms)

    @property
    def floor(self) -> float:
        return float(10.0 ** (self.floor_db / 20.0))

    def params(self) -> dict:
        return {"floor_db": self.floor_db, "fade_ms": self.fade_ms, "bridge_ms": self.bridge_ms}

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32)
        mask = target_mask(len(x), regions, fade_ms=self.fade_ms, floor=self.floor,
                           bridge_ms=self.bridge_ms)
        out = x * mask
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))   # canonical length


def _env_float(env, name: str, default: float) -> float:
    try:
        return float(env[name])
    except (KeyError, TypeError, ValueError):
        return default


def build_extractor(name: str | None = None, *, floor_db: float | None = None,
                    fade_ms: float | None = None, bridge_ms: float | None = None,
                    env=None) -> Extractor:
    """The one place that decides which mask runs.

    ``FOCUS_VOICE_EXTRACTOR`` = ``ducked`` (default), ``gated``, ``music`` or
    ``separation``; ``FOCUS_VOICE_FLOOR_DB`` (default -12),
    ``FOCUS_VOICE_FADE_MS`` (default 30) and ``FOCUS_VOICE_BRIDGE_MS``
    (default 250) tune the ducked baseline. ``gated`` is kept so the old
    behaviour stays reproducible in an A/B listening comparison; ``music``
    adds the opt-in Demucs pre-cleaner and ``separation`` the opt-in
    ClearerVoice speech separator (each needs its own environment and weights,
    see ``focus_ml.voice.music`` / ``focus_ml.voice.separation``).
    """
    source = os.environ if env is None else env
    choice = (name or source.get("FOCUS_VOICE_EXTRACTOR") or DEFAULT_EXTRACTOR).strip().lower()
    floor = _env_float(source, "FOCUS_VOICE_FLOOR_DB", DEFAULT_FLOOR_DB) if floor_db is None else floor_db
    fade = _env_float(source, "FOCUS_VOICE_FADE_MS", DEFAULT_FADE_MS) if fade_ms is None else fade_ms
    bridge = (_env_float(source, "FOCUS_VOICE_BRIDGE_MS", DEFAULT_BRIDGE_MS)
              if bridge_ms is None else bridge_ms)
    if choice in ("gated", "gated_baseline"):
        # The old baseline keeps its 10 ms fade unless a caller asks otherwise;
        # the FOCUS_VOICE_* tuning only applies to the ducked baseline.
        return GatedBaseline(fade_ms=fade if fade_ms is not None else 10.0)
    if choice in ("ducked", "ducked_baseline"):
        return DuckedBaseline(floor_db=floor, fade_ms=fade, bridge_ms=bridge)
    if choice in ("music", "music_suppressed", "demucs"):
        from .music import build_music_extractor   # lazy: keeps torch out of import
        return build_music_extractor(env=source)
    if choice in ("separation", "speech_separation", "speech"):
        from .separation import build_separation_extractor   # lazy, same reason
        return build_separation_extractor(env=source)
    raise ValueError(f"unknown extractor {choice!r}; choose one of {EXTRACTOR_CHOICES}")
