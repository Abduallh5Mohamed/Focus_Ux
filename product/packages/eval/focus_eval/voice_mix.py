"""Ground-truth mixes from solo recordings (numpy only; no I/O).

Speakers take turns on a timeline; consecutive turns overlap by ``overlap_s``.
Every speaker keeps a full-length reference (their exact gained signal) so
SI-SDRi and who-spoke-when truth are real, not estimated from the mix.
"""
from __future__ import annotations

import numpy as np

SR = 16000
FRAME_S = 0.02


def plan_conversation(speakers: list[str], n_turns: int, turn_s: float, overlap_s: float) -> list[dict]:
    """Round-robin turns; turn i starts overlap_s before turn i-1 ends. With 3+
    speakers a turn can overlap the previous one only."""
    if len(speakers) < 2:
        raise ValueError("at least 2 speakers are needed")
    if not 0 <= overlap_s < turn_s:
        raise ValueError("overlap_s must be >= 0 and shorter than a turn")
    order = list(speakers)
    plan, t = [], 0.0
    for i in range(n_turns):
        spk = order[i % len(order)]
        plan.append({"speaker": spk, "start": round(t, 3), "length": turn_s})
        t += turn_s - (overlap_s if i < n_turns - 1 else 0.0)
    return plan


def activity_segments(x, sr: int = SR, rel_db: float = -35.0, min_gap_s: float = 0.3,
                      min_len_s: float = 0.2) -> list[tuple[float, float]]:
    """Speech-active spans of a clean reference by frame energy relative to its
    loudest frames (a ground-truth helper for clean signals, not a VAD model)."""
    n = int(FRAME_S * sr)
    frames = len(x) // n
    if frames == 0:
        return []
    rms = np.sqrt((np.asarray(x[:frames * n], float).reshape(frames, n) ** 2).mean(1))
    peak = np.percentile(rms, 95)
    active = rms > peak * 10 ** (rel_db / 20) if peak > 0 else np.zeros(frames, bool)
    spans, start = [], None
    for i, a in enumerate(list(active) + [False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            spans.append([start * FRAME_S, i * FRAME_S])
            start = None
    merged = []
    for s in spans:
        if merged and s[0] - merged[-1][1] <= min_gap_s:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [(a, b) for a, b in merged if b - a >= min_len_s]


def build_mix(clips: dict, plan: list[dict], gains_db: dict | None = None, noise=None,
              snr_db: float | None = None, sr: int = SR):
    """clips: speaker -> mono float signal (cut to the planned turn length).
    Returns mix, refs (speaker -> full-length signal), truth (speaker -> spans).
    refs sum to the mix (before noise); noise is added to the mix only."""
    gains_db = gains_db or {}
    total = max(int(round((p["start"] + p["length"]) * sr)) for p in plan)
    refs = {s: np.zeros(total, dtype=np.float64) for s in {p["speaker"] for p in plan}}
    cursors = {s: 0 for s in refs}
    for p in plan:
        clip = np.asarray(clips[p["speaker"]], float)
        n = int(round(p["length"] * sr))
        c = cursors[p["speaker"]]
        piece = clip[c:c + n]
        if len(piece) < n:
            raise ValueError(f"not enough audio for speaker {p['speaker']}: need {n} samples more")
        cursors[p["speaker"]] = c + n
        a = int(round(p["start"] * sr))
        refs[p["speaker"]][a:a + n] += piece * 10 ** (gains_db.get(p["speaker"], 0.0) / 20)
    mix = np.sum(list(refs.values()), axis=0)
    if noise is not None and snr_db is not None:
        nz = np.resize(np.asarray(noise, float), total)
        scale = np.sqrt((mix ** 2).mean() / max((nz ** 2).mean(), 1e-12)) / 10 ** (snr_db / 20)
        mix = mix + nz * scale
    peak = float(np.abs(mix).max())
    k = 0.9 / peak if peak > 0.9 else 1.0
    refs = {s: v * k for s, v in refs.items()}
    truth = {s: activity_segments(v, sr) for s, v in refs.items()}
    return mix * k, refs, truth
