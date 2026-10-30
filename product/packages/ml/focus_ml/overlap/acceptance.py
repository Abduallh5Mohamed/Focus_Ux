"""Acceptance cases A-D for the production overlap path, with explicit definitions.

  A target alone | B other speaker alone | C target + one other | D target + two others

Mixtures are built from CLEAN per-speaker recordings, so references exist. All metrics
are computed from the real output; a metric that does not apply to a case is None.

  target_retention     share of the target reference's energy present in the output
                       (projection of output onto the reference / reference energy)
  leakage              share of the other speakers' reference energy present in the output
  si_sdri_db           SI-SDR(output) - SI-SDR(mixture) against the target reference
  silent_pct           % of output samples that are digital silence (|x| < 1e-4)
  sync_lag_samples     lag (+/- 50 ms search) that best aligns output with the target
                       reference; 0 = in sync. Length equality is reported separately.
"""
from __future__ import annotations

import numpy as np

from ..engine_report import si_sdri
from ..voice.types import SAMPLE_RATE, TARGET, UNCERTAIN, OTHER, LabelledRegion

CASES = ("A", "B", "C", "D")
SILENCE = 1e-4


def build_case(case: str, target, others: list, seconds: float = 8.0):
    """(mixture, target_ref or None, other_refs, regions). Region labels are ground truth."""
    n = int(seconds * SAMPLE_RATE)
    fit = lambda s: np.resize(np.asarray(s, dtype=np.float32), n).astype(np.float32)  # noqa: E731
    need = {"A": 0, "B": 1, "C": 1, "D": 2}[case]
    if len(others) < need:
        raise ValueError(f"case {case} needs {need} other-speaker recording(s)")
    t = fit(target) if case != "B" else None
    o = [fit(x) for x in others[:need]]
    mix = sum(([t] if t is not None else []) + o)
    label, reason = {"A": (TARGET, "target_only"), "B": (OTHER, "other_only")}.get(case, (UNCERTAIN, "overlap"))
    return mix.astype(np.float32), t, o, [LabelledRegion(0.0, seconds, label, None, None, reason)]


def _proj_energy(x, ref) -> float:
    d = float(np.dot(ref, ref))
    return float(np.dot(x, ref) ** 2 / d) if d > 0 else 0.0


def sync_lag(out, ref, max_lag: int = SAMPLE_RATE // 20) -> int:
    out, ref = np.asarray(out, np.float64), np.asarray(ref, np.float64)
    best, best_v = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1, 4):
        a, b = (out[lag:], ref[:len(ref) - lag]) if lag >= 0 else (out[:lag], ref[-lag:])
        m = min(len(a), len(b))
        v = float(np.dot(a[:m], b[:m]))
        if v > best_v:
            best, best_v = lag, v
    # refine around the coarse optimum
    for lag in range(best - 3, best + 4):
        if abs(lag) > max_lag:
            continue
        a, b = (out[lag:], ref[:len(ref) - lag]) if lag >= 0 else (out[:lag], ref[-lag:])
        m = min(len(a), len(b))
        v = float(np.dot(a[:m], b[:m]))
        if v > best_v:
            best, best_v = lag, v
    return int(best)   # > 0: the output lags the reference by that many samples


def score_case(case, out, mix, target_ref, other_refs, seconds_processing, peak_vram_mib) -> dict:
    out = np.asarray(out, dtype=np.float64)
    row = {"case": case, "length_equal": len(out) == len(mix), "processing_seconds": round(seconds_processing, 3),
           "peak_vram_mib": peak_vram_mib,
           "silent_pct": round(100.0 * float(np.mean(np.abs(out) < SILENCE)), 2),
           "target_retention": None, "leakage": None, "si_sdri_db": None, "sync_lag_samples": None}
    n = min(len(out), len(mix))
    o = out[:n]
    if target_ref is not None:
        t = np.asarray(target_ref, np.float64)[:n]
        row["target_retention"] = round(_proj_energy(o, t) / float(np.dot(t, t) + 1e-12), 4)
        row["si_sdri_db"] = round(si_sdri(o, mix[:n], t), 2)
        row["sync_lag_samples"] = sync_lag(o, t)
    if other_refs:
        e_other = sum(float(np.dot(r[:n], r[:n])) for r in other_refs)
        row["leakage"] = round(sum(_proj_energy(o, np.asarray(r, np.float64)[:n]) for r in other_refs)
                               / (e_other + 1e-12), 4)
    return row
