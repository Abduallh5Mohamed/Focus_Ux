"""Reference-based scoring for the real-weights experiment (numpy, plus pystoi/pesq when present).

All scores are computed on the OVERLAP REGION (samples where the target and at least one
other speaker talk) and, for context, on the whole clip. Terms:

  SI-SDRi          SI-SDR(output, target ref) - SI-SDR(mixture, target ref); muted output = floor (-30 dB)
  target retention share of the target reference's energy that is in the output: a_t^2, where a_t is the
                   least-squares weight of the target reference when the output is fitted by all the clean
                   references (0 = absent, 1 = present at the right level)
  leakage share    share of the interferers' reference energy that is in the output (same fit)
  leakage ratio    interferer energy kept / target energy kept (None when no target energy is kept)
  muted            share of 20 ms frames whose RMS is below 0.1 % of the mixture's RMS
  STOI / PESQ      objective quality of the output against the clean target reference (pystoi, pesq wideband)
"""
from __future__ import annotations

import statistics

import numpy as np

from ..engine_report import si_sdr
from .metrics import MUTED_REL_RMS, SDR_CEIL_DB, SDR_FLOOR_DB

SR = 16000
FRAME = 320                     # 20 ms


def overlap_mask(regions: list[dict], target: str, n: int, sr: int = SR) -> np.ndarray:
    """True where the target and at least one other speaker are active."""
    m = np.zeros(n, dtype=bool)
    for r in regions:
        if target in r["active"] and len(set(r["active"])) >= 2:
            m[int(round(r["start"] * sr)):min(n, int(round(r["end"] * sr)))] = True
    return m


def _clamp(v: float) -> float:
    return float(min(SDR_CEIL_DB, max(SDR_FLOOR_DB, v)))


def muted_share(est, mix, mask) -> float | None:
    """Share of 20 ms frames inside ``mask`` that are (nearly) silent."""
    est, mix = np.asarray(est, np.float64), np.asarray(mix, np.float64)
    ref_rms = max(float(np.sqrt(np.mean(mix[mask] ** 2))) if mask.any() else 0.0, 1e-12)
    muted = total = 0
    for a in range(0, len(est) - FRAME + 1, FRAME):
        if mask[a:a + FRAME].all():
            total += 1
            muted += float(np.sqrt(np.mean(est[a:a + FRAME] ** 2))) < MUTED_REL_RMS * ref_rms
    return None if not total else round(muted / total, 4)


def decompose(est, refs: dict, target: str, mask) -> dict:
    """Least-squares fit of ``est`` by the clean references inside ``mask``."""
    names = [target] + sorted(s for s in refs if s != target)
    A = np.stack([np.asarray(refs[s], np.float64)[mask] for s in names], axis=1)
    e = np.asarray(est, np.float64)[mask]
    energy = (A ** 2).sum(axis=0)
    w, *_ = np.linalg.lstsq(A, e, rcond=None)
    kept = (w ** 2) * energy                          # energy of each reference present in the output
    tgt_kept = float(max(w[0], 0.0) ** 2 * energy[0])
    other_total = float(energy[1:].sum())
    other_kept = float(kept[1:].sum())
    silent = float(np.sum(e * e)) < 1e-12
    return {"target_retention": round(float(max(w[0], 0.0) ** 2), 4),
            "leakage_share": round(other_kept / other_total, 4) if other_total > 0 else 0.0,
            "leakage_ratio": None if silent or tgt_kept <= 1e-9 * max(energy[0], 1e-12)
            else round(other_kept / tgt_kept, 4)}


def quality(est, ref) -> dict:
    """STOI and wideband PESQ against the clean reference. Errors are returned, not hidden."""
    out = {"stoi": None, "pesq": None, "quality_errors": []}
    est, ref = np.asarray(est, np.float64), np.asarray(ref, np.float64)
    try:
        from pystoi import stoi
        out["stoi"] = round(float(stoi(ref, est, SR, extended=False)), 4)
    except Exception as exc:       # noqa: BLE001 - reported
        out["quality_errors"].append(f"stoi: {type(exc).__name__}: {exc}")
    try:
        from pesq import pesq
        out["pesq"] = round(float(pesq(SR, ref.astype(np.float32), est.astype(np.float32), "wb")), 3)
    except Exception as exc:       # noqa: BLE001 - reported
        out["quality_errors"].append(f"pesq: {type(exc).__name__}: {exc}")
    return out


def score_scope(est, mix, refs: dict, target: str, mask, with_quality: bool = True) -> dict | None:
    """Scores of one output inside ``mask`` (None when the mask is empty)."""
    if not mask.any():
        return None
    est = np.asarray(est, np.float64)
    mixa = np.asarray(mix, np.float64)
    ref = np.asarray(refs[target], np.float64)
    muted = muted_share(est, mixa, mask)
    e, m, r = est[mask], mixa[mask], ref[mask]
    fully_muted = muted == 1.0
    sdr = SDR_FLOOR_DB if fully_muted else _clamp(si_sdr(e, r))
    sdr_mix = _clamp(si_sdr(m, r))
    row = {"seconds": round(mask.sum() / SR, 3), "si_sdr_db": round(sdr, 3), "si_sdr_mix_db": round(sdr_mix, 3),
           "si_sdri_db": round(sdr - sdr_mix, 3), "muted_share": muted, **decompose(est, refs, target, mask)}
    if with_quality:
        row.update({"stoi": None, "pesq": None, "quality_errors": ["output is silent"]} if fully_muted
                   else quality(e, r))
    return row


def score_output(est, mix, refs: dict, target: str, regions: list[dict]) -> dict:
    n = len(mix)
    ov = overlap_mask(regions, target, n)
    whole = np.ones(n, dtype=bool)
    return {"overlap": score_scope(est, mix, refs, target, ov), "clip": score_scope(est, mix, refs, target, whole)}


# ------------------------------------------------------------------ pooling
POOLED = ("si_sdri_db", "target_retention", "leakage_share", "leakage_ratio", "muted_share", "stoi", "pesq")


def pool(rows: list[dict]) -> dict:
    """Mean over mixes (each mix weighs the same); ``_n`` counts the mixes that had a value."""
    out = {"mixes": len(rows)}
    for k in POOLED:
        vals = [r[k] for r in rows if r and r.get(k) is not None]
        out[k] = round(statistics.fmean(vals), 3) if vals else None
        out[k + "_n"] = len(vals)
    return out


# ------------------------------------------------------------- the stated rule
MIN_SI_SDRI_DB = 1.0
MIN_RETENTION = 0.30
MAX_LEAKAGE_RATIO = 0.50


def improves(p: dict | None) -> dict:
    """The comparison rule (COMPARISON_RULE.md, item 5) applied to a pooled overlap result."""
    if not p or p.get("si_sdri_db") is None:
        return {"improves": False, "reasons": ["no measurement"]}
    why = []
    if p["si_sdri_db"] < MIN_SI_SDRI_DB:
        why.append(f"SI-SDRi {p['si_sdri_db']} dB is below +{MIN_SI_SDRI_DB} dB")
    if (p["target_retention"] or 0) < MIN_RETENTION:
        why.append(f"target retention {p['target_retention']} is below {MIN_RETENTION}")
    ratio = p.get("leakage_ratio")
    if ratio is None:
        why.append("no target energy kept, leakage ratio undefined")
    elif ratio > MAX_LEAKAGE_RATIO:
        why.append(f"leakage ratio {ratio} is above {MAX_LEAKAGE_RATIO}")
    return {"improves": not why, "reasons": why}
