"""Region routing for the audio-only engine: strict isolation or continuity.

  target alone        -> original audio, passed through
  other alone         -> suppressed
  overlap             -> sent to a real extractor (``overlap.HybridExtractor``) when one is
                         enabled AND validated; otherwise suppressed like other speech
  anything uncertain  -> suppressed in ``strict`` mode (and reported as possible target loss); in
                         ``continuity`` mode the original mixture plays at a reduced volume with smooth
                         fades. Only UNCERTAIN speech does this: speech confidently assigned to another
                         speaker stays suppressed in both modes.

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
from .types import SAMPLE_RATE, TARGET, UNCERTAIN

STRICT, CONTINUITY = "strict", "continuity"
MODES = (STRICT, CONTINUITY)
DEFAULT_CONTINUITY_GAIN_DB = -18.0
STRICT_NOTICE = ("Strict isolation: {seconds:.1f} s of speech that could not be confirmed as the selected voice "
                 "was muted. The selected voice may be partly missing there.")
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


def _span(r_start, r_end, n, sr=SAMPLE_RATE):
    return max(0, int(round(r_start * sr))), min(n, int(round(r_end * sr)))


def kept_spans(regions, pieces, n: int, sr: int = SAMPLE_RATE) -> list[tuple[int, int]]:
    """Sample spans whose audio is confirmed target: target regions + verified extractions."""
    spans = [_span(r.start, r.end, n, sr) for r in regions if r.label == TARGET]
    spans += [_span(p["start"], p["end"], n, sr) for p in pieces if p.get("status") == "extracted"]
    return [(a, b) for a, b in spans if b > a]


def unconfirmed_spans(regions, pieces, n: int, sr: int = SAMPLE_RATE) -> list[tuple[int, int]]:
    """Uncertain speech with no confirmed target audio: where the selected voice may be lost in strict
    mode, and where continuity mode plays the reduced original mix."""
    from ..overlap.hybrid import merge_spans, subtract_spans
    unc = merge_spans([_span(r.start, r.end, n, sr) for r in regions if r.label == UNCERTAIN])
    return subtract_spans(unc, merge_spans(kept_spans(regions, pieces, n, sr)))


def continuity_mix(x, strict_out, fallback, config: RoutingConfig) -> tuple[np.ndarray, float]:
    """strict output + the original at reduced volume over the ``fallback`` spans only. The fallback
    weight ramps smoothly (raised cosine), the sum is scaled down if it would exceed the ceiling (so
    it never clips), and length is unchanged."""
    n = len(x)
    cover = np.zeros(n, dtype=np.float32)
    for a, b in fallback:
        cover[a:b] = 1.0
    f = int(SAMPLE_RATE * config.continuity_fade_ms / 1000)
    if f > 1 and fallback:
        k = (0.5 - 0.5 * np.cos(np.linspace(0, 2 * np.pi, f, endpoint=False))).astype(np.float32)
        pad = np.pad(cover, (f, f), mode="edge")     # file edges are not region edges
        cover = np.clip(np.convolve(pad, k / k.sum(), mode="same")[f:f + n], 0.0, 1.0)
    weight = cover * config.gain
    out = strict_out + weight * x
    fallback_s = float(np.sum(weight > 1e-3 * config.gain)) / SAMPLE_RATE
    return limit_peak(out, config.ceiling), fallback_s


def limit_peak(out, ceiling: float) -> np.ndarray:
    """Never amplifies: a signal whose peak exceeds the ceiling is scaled down as a whole (no clipping)."""
    out = np.asarray(out, dtype=np.float32)
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return (out * (ceiling / peak)).astype(np.float32) if peak > ceiling else out


def _error_record(exc: BaseException) -> dict:
    if isinstance(exc, BlockedError):
        return exc.as_record()
    return {"kind": "extractor_error", "message": "the overlap extractor failed while running",
            "evidence": f"{type(exc).__name__}: {exc}"[:300]}


@dataclass
class RoutedExtractor:
    """``voice.extractor.Extractor`` implementation. ``hybrid`` is an optional, already
    built ``HybridExtractor`` (its model loads once and each window runs once per call)."""
    hybrid: object | None = None
    config: RoutingConfig = field(default_factory=RoutingConfig)
    name: str = "routed"
    last_report: dict = field(default_factory=dict)
    skip_reason: str | None = None
    requested: str | None = None   # extractor name the operator asked for (None = disabled)

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        n = len(x)
        report = {"mode": self.config.mode, "overlap_requested": self.requested, "overlap_extractor": None,
                  "overlap_extraction": "disabled", "overlap_error": None, "fallback_used": False,
                  "fallback_seconds": 0.0, "isolation_claim": "strict_isolation", "notices": []}
        pieces: list[dict] = []
        out = None
        from ..overlap.hybrid import overlap_spans
        spans = overlap_spans(regions, n)   # overlap present in the input, whatever happens next
        report["overlap_observed_seconds"] = round(sum(b - a for a, b in spans) / SAMPLE_RATE, 3)
        report["overlap_observed_regions"] = len(spans)
        if self.hybrid is not None:
            try:
                # Checked up front so a missing/failed checkpoint is reported even when no window would run.
                self.hybrid.extractor.check_ready()
                out = self.hybrid.extract(x, regions)
                hr = self.hybrid.last_report
                pieces = hr.get("pieces", [])
                report.update(overlap_extractor=hr.get("extractor"), overlap_mechanism=hr.get("mechanism"),
                              overlap_extraction="ran", hybrid=hr)
            except Exception as exc:   # explicit, reported fallback: never silent, never a crash
                rec = _error_record(exc)
                report.update(overlap_extraction="failed", overlap_error=rec)
                report["notices"].append(
                    f"Overlap extraction FAILED ({rec['kind']}): {rec['message']}. No overlap audio was "
                    "extracted; the gated baseline was used instead.")
        if self.hybrid is None and self.skip_reason:
            report.update(overlap_extraction="skipped", overlap_error=self.skip_reason)
            report["notices"].append("Overlap extraction was requested but SKIPPED: " + self.skip_reason + ".")
        if out is None:
            out = GatedBaseline().extract(x, regions)
        if len(out) != n:
            raise RuntimeError(f"routed output has {len(out)} samples, expected {n}")
        risk = unconfirmed_spans(regions, pieces, n)
        risk_s = sum(b - a for a, b in risk) / SAMPLE_RATE
        report["unconfirmed_seconds"] = round(risk_s, 3)
        fb = 0.0
        if self.config.mode == CONTINUITY:
            out, fb = continuity_mix(x, out, risk, self.config)
            report.update(fallback_used=fb > 0, fallback_seconds=round(fb, 3),
                          continuity_gain_db=self.config.continuity_gain_db,
                          isolation_claim="not_isolation" if fb > 0 else "strict_isolation")
            if fb > 0:
                report["notices"].append(CONTINUITY_NOTICE)
        else:
            out = limit_peak(out, self.config.ceiling)
            if risk_s > 0:
                report["notices"].append(STRICT_NOTICE.format(seconds=risk_s))
        report["target_may_be_lost"] = self.config.mode == STRICT and risk_s > 0
        report.update(route_labels=_route_labels(report, pieces, risk_s, fb),
                      route_seconds=_route_seconds(regions, pieces, report, risk_s, fb))
        self.last_report = report
        return out


def _route_labels(report: dict, pieces, risk_s: float, fb: float) -> list[str]:
    """Which paths the job actually took (never inferred from settings alone)."""
    state, labels = report["overlap_extraction"], []
    if state == "ran" and any(p.get("status") == "extracted" for p in pieces):
        labels.append("genuine_extraction")
    if state != "ran":
        labels.append("gated_baseline")
    if state == "skipped":
        labels.append("extraction_skipped")
    if state == "failed":
        labels.append("extraction_failed")
    if report["mode"] == STRICT and (risk_s > 0 or report.get("overlap_observed_seconds")):
        labels.append("strict_muting")
    if fb > 0:
        labels.append("continuity_fallback")
    return labels


def _route_seconds(regions, pieces, report: dict, risk_s: float, fb: float) -> dict:
    sec = lambda items: round(sum(b - a for a, b in items), 3)   # noqa: E731
    target = sum(r.end - r.start for r in regions if r.label == TARGET)
    got = sum(p["end"] - p["start"] for p in pieces if p.get("status") == "extracted")
    return {"target_passthrough": round(target, 3), "genuine_extraction": round(got, 3),
            "strict_muted_unconfirmed": round(risk_s, 3) if report["mode"] == STRICT else 0.0,
            "continuity_fallback": round(fb, 3)}


MAX_SUMMARY_REGIONS = 200


def summarize_routing(report: dict | None) -> dict:
    """Short, wire-safe routing summary of one isolation run. It states what actually
    happened (extractor ran or not, pieces kept or muted, whether the original mix
    played) and never describes a fallback as isolation."""
    report = report or {}
    hybrid = report.get("hybrid") or {}
    pieces = hybrid.get("pieces") or []
    state = report.get("overlap_extraction") or "disabled"
    ran = state == "ran"
    err = report.get("overlap_error")
    reason = err if isinstance(err, str) else (err.get("kind") if isinstance(err, dict) else None)
    extracted = [p for p in pieces if p.get("status") == "extracted"]
    lost = [p for p in pieces if p.get("status") != "extracted" and p.get("source") != "other"]
    name = report.get("overlap_extractor") or report.get("overlap_requested")
    fallback = bool(report.get("fallback_used"))
    return {
        "extractor_requested": report.get("overlap_requested"),
        "extractor_ran": ran,
        "overlap_extraction": state,
        "reason": reason,
        "mode": report.get("mode") or STRICT,
        "overlap_seconds": float(hybrid.get("overlap_seconds") if ran
                                 else report.get("overlap_observed_seconds") or 0.0),
        "windows": int(hybrid.get("windows") or 0),
        "pieces_extracted": len(extracted),
        "pieces_muted": len(lost) if ran
        else int(report.get("overlap_observed_regions") or 0),
        "muted_seconds": float(hybrid.get("uncertain_muted_seconds") if ran
                               else report.get("overlap_observed_seconds") or 0.0),
        "fallback_used": fallback,
        "fallback_seconds": float(report.get("fallback_seconds") or 0.0),
        "isolation_claim": "not_isolation" if fallback else "strict_isolation",
        "route_labels": list(report.get("route_labels") or []),
        "notices": [str(t)[:400] for t in (report.get("notices") or [])][:6],
        "route_seconds": dict(report.get("route_seconds") or {}),
        "engine_path": "extractor" if ran else "gated_baseline",
        "recovery_seconds": float(hybrid.get("recovery_seconds") or 0.0),
        "unconfirmed_seconds": float(report.get("unconfirmed_seconds") or 0.0),
        "target_may_be_lost": bool(report.get("target_may_be_lost")),
        "regions": [
            {"start_ms": int(round(p["start"] * 1000)), "end_ms": int(round(p["end"] * 1000)),
             "route": name if p.get("status") == "extracted" else (
                 "continuity_fallback" if (report.get("mode") == CONTINUITY and p.get("source") != "other")
                 else "strict_muting"),
             "status": p.get("status") or "muted",
             "reason": str(p.get("reason") or "")[:80]}
            for p in pieces[:MAX_SUMMARY_REGIONS]],
    }
