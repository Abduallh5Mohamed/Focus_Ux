"""Region routing for the audio-only engine: strict isolation or continuity.

  target alone        -> original audio, passed through
  other alone         -> suppressed
  overlap             -> sent to a real extractor (``overlap.HybridExtractor``) when one is
                         enabled AND validated; otherwise suppressed like other speech
  anything uncertain  -> suppressed in ``strict`` mode; in ``continuity`` mode the original
                         mixture plays at a reduced volume with smooth fades

DISABLED BY DEFAULT. No extractor runs unless ``FOCUS_OVERLAP_EXTRACTOR`` names one, and
that setting stays off for production until the candidate passed a real-inference
validation (docs/OVERLAP_PRODUCTION.md). Continuity mode is NOT speaker isolation: it
lets other voices be heard, so every result that used it says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..overlap.base import BlockedError
from .extractor import GatedBaseline
from .types import SAMPLE_RATE, TARGET

STRICT, CONTINUITY = "strict", "continuity"
MODES = (STRICT, CONTINUITY)
DEFAULT_CONTINUITY_GAIN_DB = -18.0
CONTINUITY_NOTICE = ("Continuity mode: parts without a confirmed target voice play the original mix at "
                     "reduced volume. Other voices are audible there; this is not speaker isolation.")


@dataclass
class RoutingConfig:
    mode: str = STRICT
    continuity_gain_db: float = DEFAULT_CONTINUITY_GAIN_DB   # must be < 0
    continuity_fade_ms: float = 30.0
    ceiling: float = 0.98                                     # output never exceeds this

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, not {self.mode!r}")
        if not self.continuity_gain_db < 0:
            raise ValueError("continuity_gain_db must be negative (reduced volume)")
        if self.continuity_fade_ms < 0 or not 0 < self.ceiling <= 1:
            raise ValueError("invalid continuity fade or ceiling")

    @property
    def gain(self) -> float:
        return float(10 ** (self.continuity_gain_db / 20))


def routing_from_env(env) -> tuple[RoutingConfig, str | None]:
    """(config, overlap extractor name or None). Anything unset means strict + no extractor."""
    mode = (env.get("FOCUS_ISOLATION_MODE") or STRICT).strip().lower()
    kw = {}
    if env.get("FOCUS_CONTINUITY_GAIN_DB"):
        kw["continuity_gain_db"] = float(env["FOCUS_CONTINUITY_GAIN_DB"])
    name = (env.get("FOCUS_OVERLAP_EXTRACTOR") or "").strip() or None
    return RoutingConfig(mode=mode, **kw), name


def kept_spans(regions, pieces, n: int, sr: int = SAMPLE_RATE) -> list[tuple[int, int]]:
    """Sample spans whose audio is confirmed target: target regions + verified extractions."""
    spans = [(int(round(r.start * sr)), int(round(r.end * sr))) for r in regions if r.label == TARGET]
    spans += [(int(round(p["start"] * sr)), int(round(p["end"] * sr)))
              for p in pieces if p.get("status") == "extracted"]
    return [(max(0, a), min(n, b)) for a, b in spans if min(n, b) > max(0, a)]


def continuity_mix(x, strict_out, kept, config: RoutingConfig) -> tuple[np.ndarray, float]:
    """strict output + the original at reduced volume where nothing was confirmed.
    The fallback weight ramps smoothly (raised cosine), the sum is scaled down if it
    would exceed the ceiling (so it never clips), and length is unchanged."""
    n = len(x)
    cover = np.zeros(n, dtype=np.float32)
    for a, b in kept:
        cover[a:b] = 1.0
    f = int(SAMPLE_RATE * config.continuity_fade_ms / 1000)
    if f > 1:
        k = (0.5 - 0.5 * np.cos(np.linspace(0, 2 * np.pi, f, endpoint=False))).astype(np.float32)
        pad = np.pad(cover, (f, f), mode="edge")     # file edges are not region edges
        cover = np.clip(np.convolve(pad, k / k.sum(), mode="same")[f:f + n], 0.0, 1.0)
    weight = (1.0 - cover) * config.gain
    out = strict_out + weight * x
    peak = float(np.max(np.abs(out))) if n else 0.0
    if peak > config.ceiling:
        out = out * (config.ceiling / peak)
    fallback_s = float(np.sum(weight > 1e-3 * config.gain)) / SAMPLE_RATE
    return out.astype(np.float32), fallback_s


@dataclass
class RoutedExtractor:
    """``voice.extractor.Extractor`` implementation. ``hybrid`` is an optional, already
    built ``HybridExtractor`` (its model loads once and each window runs once per call)."""
    hybrid: object | None = None
    config: RoutingConfig = field(default_factory=RoutingConfig)
    name: str = "routed"
    last_report: dict = field(default_factory=dict)
    skip_reason: str | None = None

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        n = len(x)
        report = {"mode": self.config.mode, "overlap_extractor": None, "overlap_extraction": "disabled",
                  "overlap_error": None, "fallback_used": False, "fallback_seconds": 0.0,
                  "isolation_claim": "strict_isolation", "notices": []}
        pieces: list[dict] = []
        out = None
        if self.hybrid is not None:
            try:
                out = self.hybrid.extract(x, regions)
                hr = self.hybrid.last_report
                pieces = hr.get("pieces", [])
                report.update(overlap_extractor=hr.get("extractor"), overlap_mechanism=hr.get("mechanism"),
                              overlap_extraction="ran", hybrid=hr)
            except BlockedError as exc:   # explicit, reported fallback: never silent
                report.update(overlap_extraction="failed", overlap_error=exc.as_record())
                report["notices"].append(
                    f"Overlap extraction was unavailable ({exc.kind}); overlap was handled as without it.")
        if self.hybrid is None and self.skip_reason:
            report.update(overlap_extraction="skipped", overlap_error=self.skip_reason)
        if out is None:
            out = GatedBaseline().extract(x, regions)
        if len(out) != n:
            raise RuntimeError(f"routed output has {len(out)} samples, expected {n}")
        if self.config.mode == CONTINUITY:
            out, fb = continuity_mix(x, out, kept_spans(regions, pieces, n), self.config)
            report.update(fallback_used=fb > 0, fallback_seconds=round(fb, 3),
                          continuity_gain_db=self.config.continuity_gain_db,
                          isolation_claim="not_isolation" if fb > 0 else "strict_isolation")
            if fb > 0:
                report["notices"].append(CONTINUITY_NOTICE)
        self.last_report = report
        return out
