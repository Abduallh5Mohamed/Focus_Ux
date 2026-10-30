"""Metrics for the audio-only voice pipeline. Pure numpy; every number comes
from scores/timelines/audio that a real run produced (this module computes, it
never invents)."""
from __future__ import annotations

import itertools

import numpy as np

HOP_S = 0.01


# ---- verification (embedding quality) -----------------------------------
def far_frr(target_scores, other_scores, threshold: float) -> dict:
    t, o = np.asarray(target_scores, float), np.asarray(other_scores, float)
    return {"threshold": float(threshold),
            "far": float((o >= threshold).mean()) if o.size else None,   # wrong person accepted
            "frr": float((t < threshold).mean()) if t.size else None}    # right person rejected


def eer(target_scores, other_scores) -> dict:
    t, o = np.asarray(target_scores, float), np.asarray(other_scores, float)
    if not t.size or not o.size:
        raise ValueError("EER needs both same-speaker and different-speaker scores")
    best = None
    for th in np.unique(np.concatenate([t, o])):
        far, frr = (o >= th).mean(), (t < th).mean()
        gap = abs(far - frr)
        if best is None or gap < best[0]:
            best = (gap, th, (far + frr) / 2)
    return {"eer": float(best[2]), "threshold": float(best[1]),
            "n_target_trials": int(t.size), "n_other_trials": int(o.size)}


def calibrate_thresholds(target_scores, other_scores, max_far: float = 0.01,
                         max_target_as_other: float = 0.05, min_band: float = 0.05) -> dict:
    """Two thresholds. ``target_threshold``: lowest score with FAR <= max_far
    (almost no wrong person accepted). ``other_threshold``: highest score at
    which at most ``max_target_as_other`` of true-target scores fall at or below
    it (almost no true target called 'other'). Between them: uncertain."""
    t, o = np.sort(np.asarray(target_scores, float)), np.asarray(other_scores, float)
    cands = np.unique(np.concatenate([t, o]))
    hi = next((c for c in cands if (o >= c).mean() <= max_far), float(cands.max()) + 1e-6)
    k = int(np.floor(max_target_as_other * t.size))
    lo = float(t[k]) - 1e-6 if t.size else float(hi)
    lo = min(lo, float(hi) - min_band)   # always leave an uncertain band
    return {"target_threshold": round(float(hi), 4), "other_threshold": round(lo, 4),
            "max_far": max_far, "max_target_as_other": max_target_as_other, "min_band": min_band}


def verification_trials(embeddings: dict, enroll_n: int = 3):
    """embeddings: speaker -> list of unit vectors (utterance order). Enrol on the
    first ``enroll_n`` (mean), test on the rest. Returns (target, other) scores."""
    prints = {}
    for spk, vecs in embeddings.items():
        if len(vecs) > enroll_n:
            m = np.mean(vecs[:enroll_n], axis=0)
            prints[spk] = m / np.linalg.norm(m)
    tgt, oth = [], []
    for spk, p in prints.items():
        for other, vecs in embeddings.items():
            tests = vecs[enroll_n:] if other in prints else vecs
            for v in tests:
                (tgt if other == spk else oth).append(float(p @ np.asarray(v)))
    return tgt, oth


# ---- timelines ----------------------------------------------------------
def to_frames(segments, total_s: float, hop: float = HOP_S) -> np.ndarray:
    n = int(np.ceil(total_s / hop))
    f = np.zeros(n, bool)
    for a, b in segments:
        f[int(round(a / hop)):int(round(b / hop))] = True
    return f


def der(ref: dict, hyp: dict, total_s: float, hop: float = HOP_S) -> dict:
    """Frame-based diarization error rate with the best speaker mapping.
    ref/hyp: speaker -> [(start, end)]. Overlap counted per speaker."""
    rs, hs = sorted(ref), sorted(hyp)
    R = np.array([to_frames(ref[s], total_s, hop) for s in rs]) if rs else np.zeros((0, 1), bool)
    H = np.array([to_frames(hyp[s], total_s, hop) for s in hs]) if hs else np.zeros((0, 1), bool)
    n = max(R.shape[1], H.shape[1])
    R = np.pad(R, ((0, 0), (0, n - R.shape[1])))
    H = np.pad(H, ((0, 0), (0, n - H.shape[1])))
    nref, nhyp = R.sum(0), H.sum(0)
    if len(hs) > 8 or len(rs) > 8:
        raise ValueError("DER mapping supports at most 8 speakers")
    best = (-1, ())
    k = min(len(rs), len(hs))
    for hsel in itertools.permutations(range(len(hs)), k):
        agree = sum(int((R[i] & H[j]).sum()) for i, j in enumerate(hsel))
        if agree > best[0]:
            best = (agree, hsel)
    correct = sum((R[i] & H[j]) for i, j in enumerate(best[1])) if k else np.zeros(n)
    miss = np.maximum(nref - nhyp, 0).sum()
    fa = np.maximum(nhyp - nref, 0).sum()
    conf = (np.minimum(nref, nhyp) - correct).sum()
    total = nref.sum()
    rate = lambda x: float(x / total) if total else None
    return {"der": rate(miss + fa + conf), "miss": rate(miss), "false_alarm": rate(fa),
            "confusion": rate(conf), "ref_speech_s": float(total * hop)}


def gate_metrics(passed, target_segments, other_segments, total_s: float, hop: float = HOP_S) -> dict:
    """passed: [(start,end)] the gated output keeps. target/other: ground-truth
    segments. Solo = speaking while nobody else does."""
    P = to_frames(passed, total_s, hop)
    T = to_frames(target_segments, total_s, hop)
    O = to_frames(other_segments, total_s, hop)
    n = min(len(P), len(T), len(O))
    P, T, O = P[:n], T[:n], O[:n]
    t_solo, o_solo, both = T & ~O, O & ~T, T & O
    div = lambda a, b: float(a / b) if b else None
    return {
        "target_solo_s": float(t_solo.sum() * hop), "other_solo_s": float(o_solo.sum() * hop),
        "overlap_s": float(both.sum() * hop),
        "target_retention": div((P & t_solo).sum(), t_solo.sum()),          # target solo speech kept
        "wrong_person_rate": div((P & o_solo).sum(), o_solo.sum()),         # others' solo speech leaked
        "wrong_share_of_output": div((P & o_solo).sum(), P.sum()),
        "target_speech_kept_in_overlap": div((P & both).sum(), both.sum()),
    }
