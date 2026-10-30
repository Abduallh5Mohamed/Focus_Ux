"""Scoring of extraction candidates per region category, aggregation and the decision.

Pure numpy. Region categories (by who is speaking, from ground truth):
  target_alone   only the target speaks             (should pass through)
  overlap_2      the target and one other speak
  overlap_3plus  the target and two or more others speak
  others_overlap two or more others, no target       (should be silent)
"""
from __future__ import annotations

import statistics

import numpy as np

from ..engine_report import si_sdr

CATEGORIES = ("target_alone", "overlap_2", "overlap_3plus", "others_overlap")
OVERLAP_CATEGORIES = ("overlap_2", "overlap_3plus")
MIN_REGION_S = 0.3
SDR_FLOOR_DB = -30.0     # muted output counts as this, not -infinity
SDR_CEIL_DB = 50.0
MUTED_REL_RMS = 1e-3     # output below this share of the mixture level counts as muted

MIN_GAIN_DB = 1.0            # a candidate must beat the gated baseline by this in overlap
MAX_WRONG_PERSON = 0.10
MIN_RETENTION = 0.30


def region_category(active: list[str], target: str) -> str | None:
    n = len(set(active))
    if n == 0:
        return None
    if target in active:
        return "target_alone" if n == 1 else ("overlap_2" if n == 2 else "overlap_3plus")
    return "others_overlap" if n >= 2 else None      # others alone: muted by design, not scored


def _clamp(v: float) -> float:
    return float(min(SDR_CEIL_DB, max(SDR_FLOOR_DB, v)))


def score_clip(est, mix, refs: dict, target: str, regions: list[dict], sr: int = 16000) -> list[dict]:
    """One row per scored region. ``regions``: {start, end, active:[speakers]}."""
    est = np.asarray(est, np.float64)
    mix = np.asarray(mix, np.float64)
    rows = []
    for r in regions:
        cat = region_category(r["active"], target)
        a, b = int(round(r["start"] * sr)), int(round(r["end"] * sr))
        if cat is None or (b - a) / sr < MIN_REGION_S:
            continue
        e, m = est[a:b], mix[a:b]
        row = {"category": cat, "start": r["start"], "end": r["end"], "seconds": (b - a) / sr}
        e_rms = float(np.sqrt(np.mean(e * e)))
        m_rms = max(float(np.sqrt(np.mean(m * m))), 1e-12)
        row["muted"] = e_rms < MUTED_REL_RMS * m_rms
        if cat == "others_overlap":
            row["leakage_db"] = round(20 * np.log10(max(e_rms, 1e-12) / m_rms), 2)
            rows.append(row)
            continue
        ref = np.asarray(refs[target], np.float64)[a:b]
        row["si_sdr_db"] = SDR_FLOOR_DB if row["muted"] else round(_clamp(si_sdr(e, ref)), 3)
        row["si_sdr_mix_db"] = round(_clamp(si_sdr(m, ref)), 3)
        row["si_sdri_db"] = round(row["si_sdr_db"] - row["si_sdr_mix_db"], 3)
        row["retention"] = round(float(min(1.0, max(0.0, np.dot(e, ref) / (np.dot(ref, ref) + 1e-12)))), 4)
        if row["muted"]:
            row["wrong_person"] = None
        else:
            scores = {s: si_sdr(e, np.asarray(refs[s], np.float64)[a:b]) for s in r["active"]}
            row["wrong_person"] = max(scores, key=scores.get) != target
        rows.append(row)
    return rows


def clip_si_sdri(est, mix, ref) -> float:
    muted = float(np.sqrt(np.mean(np.asarray(est, np.float64) ** 2))) < 1e-9
    return round((SDR_FLOOR_DB if muted else _clamp(si_sdr(est, ref))) - _clamp(si_sdr(mix, ref)), 3)


def _mean(v):
    return round(statistics.fmean(v), 3) if v else None


def aggregate(rows: list[dict]) -> dict:
    """Per category: SI-SDRi (mean/median), wrong-person rate (among non-muted
    regions), muted share, target retention, leakage."""
    out = {}
    for cat in CATEGORIES:
        rs = [r for r in rows if r["category"] == cat]
        if not rs:
            out[cat] = None
            continue
        entry = {"regions": len(rs), "seconds": round(sum(r["seconds"] for r in rs), 2),
                 "muted_share": round(sum(r["muted"] for r in rs) / len(rs), 4)}
        if cat == "others_overlap":
            entry["leakage_db_mean"] = _mean([r["leakage_db"] for r in rs])
        else:
            sdri = [r["si_sdri_db"] for r in rs]
            judged = [r for r in rs if r["wrong_person"] is not None]
            entry.update(
                si_sdri_db_mean=_mean(sdri), si_sdri_db_median=round(statistics.median(sdri), 3),
                retention_mean=_mean([r["retention"] for r in rs]),
                wrong_person_rate=round(sum(r["wrong_person"] for r in judged) / len(judged), 4)
                if judged else None,
                wrong_person_judged=len(judged))
        out[cat] = entry
    return out


def pooled_overlap(agg: dict, categories=OVERLAP_CATEGORIES) -> dict | None:
    """Overlap categories combined (region-count weighted) for the decision."""
    parts = [agg[c] for c in categories if agg.get(c)]
    if not parts:
        return None
    w = [p["regions"] for p in parts]
    wm = lambda key: (None if any(p[key] is None for p in parts)
                      else round(sum(p[key] * k for p, k in zip(parts, w)) / sum(w), 3))
    return {"regions": sum(w), "si_sdri_db_mean": wm("si_sdri_db_mean"),
            "retention_mean": wm("retention_mean"), "wrong_person_rate": wm("wrong_person_rate")}


FINE_TUNING_PLAN = (
    "No candidate beats the gated baseline in overlap by the required margin, so use fine-tuning: "
    "(1) simulate Egyptian Arabic mixtures from the team's solo recordings with "
    "product/tools/overlap_set.py (2 and 3+ speakers, target -6/0/+6 dB, MUSAN noise at several SNRs), "
    "keeping each speaker's enrollment out of the mixes; (2) fine-tune the best-measured target-conditioned "
    "base model (REAL-TSE WeSep BSRNN, whose training code is open) on those mixtures plus public data to "
    "avoid forgetting; (3) budget roughly 20-40 GPU hours on one 24 GB cloud GPU for the first round "
    "(an estimate, not a measurement), then re-run this bake-off on held-out Egyptian speakers.")


def decide(summary: dict, baseline: dict, basis: dict) -> dict:
    """summary: candidate -> {"overlap": pooled dict | None, "info": {...}, "blocked": record | None}.
    baseline: pooled overlap dict of the gated baseline (same mixes)."""
    eligible, reasons = [], {}
    for name, s in summary.items():
        o = s.get("overlap")
        base_sdri = (s.get("baseline_overlap") or baseline or {}).get("si_sdri_db_mean")
        if s.get("blocked"):
            reasons[name] = f"blocked: {s['blocked']['kind']}"
        elif not o or o["si_sdri_db_mean"] is None or base_sdri is None:
            reasons[name] = "no measurement"
        elif o["si_sdri_db_mean"] < base_sdri + MIN_GAIN_DB:
            reasons[name] = f"SI-SDRi {o['si_sdri_db_mean']} dB does not beat the gated baseline " \
                            f"({base_sdri} dB) by {MIN_GAIN_DB} dB"
        elif (o["wrong_person_rate"] or 0) > MAX_WRONG_PERSON:
            reasons[name] = f"wrong-person rate {o['wrong_person_rate']} above {MAX_WRONG_PERSON}"
        elif (o["retention_mean"] or 0) < MIN_RETENTION:
            reasons[name] = f"target retention {o['retention_mean']} below {MIN_RETENTION}"
        else:
            eligible.append(name)
    eligible.sort(key=lambda n: summary[n]["overlap"]["si_sdri_db_mean"], reverse=True)
    # candidates that only handle 3+ overlap can never be the general default
    specialists = [n for n in eligible if len(summary[n].get("categories", OVERLAP_CATEGORIES)) < 2]
    eligible = [n for n in eligible if n not in specialists]
    provisional = not (basis.get("language") == "egyptian_arabic" and str(basis.get("device", "")).startswith("cuda"))
    if eligible:
        status = "decided_provisional" if provisional else "decided"
        text = (f"Default: {eligible[0]}. Fallback: {eligible[1] if len(eligible) > 1 else 'the gated baseline (mute overlap)'}.")
    elif not any(s.get("overlap") for s in summary.values()):
        status, text = "no_measurements", ("No candidate produced a measurement, so no default is chosen. "
                                           "The gated baseline (mute overlap) stays in use.")
    else:
        status, text = "no_candidate_improves", ("No candidate improves on the gated baseline in overlap. "
                                                 "The gated baseline stays the default.")
    if specialists:
        text += f" For 3+ overlap only, {specialists[0]} also beats the baseline."
    if provisional:
        text += (f" Measured on: {basis.get('language', 'unknown language')}, device "
                 f"{basis.get('device', 'unknown')}. This is not an Egyptian-Arabic/RTX 3050 result, so it must "
                 "be repeated there before it is relied on.")
    return {"status": status, "default": eligible[0] if eligible else None, "three_plus_option": specialists[0] if specialists else None,
            "fallback": eligible[1] if len(eligible) > 1 else None, "eligible": eligible,
            "rejected": {k: v for k, v in reasons.items()}, "baseline_overlap": baseline, "basis": basis,
            "criteria": {"min_gain_db": MIN_GAIN_DB, "max_wrong_person": MAX_WRONG_PERSON,
                         "min_retention": MIN_RETENTION},
            "text": text,
            "fine_tuning_plan": FINE_TUNING_PLAN if status in ("no_candidate_improves", "no_measurements") else None}
