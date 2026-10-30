"""Overlap test scenarios with exact ground truth (numpy only; no I/O).

Each scenario has the target and 1 (2-person overlap) or 2 (3+-person overlap)
other speakers. The timeline is fixed so every region category exists:

  2-person: target 0-6 s, other 2-8 s, target again 9-12 s
  3-person: target 0-6 s, other1 2-8 s, other2 3-9 s, target again 10-13 s

Conditions: the target's level relative to the others (-6 / 0 / +6 dB) and
background noise at several SNRs. Regions come from the plan, i.e. they are
turn-level ground truth, not a diarizer output.
"""
from __future__ import annotations

import itertools

TARGET_REL_DB = (-6.0, 0.0, 6.0)
NOISE_SNR_DB = (None, 20.0, 10.0, 0.0)
N_OVERLAP = (2, 3)


def scenario_plan(n_overlap: int, target: str, others: list[str]) -> list[dict]:
    if n_overlap not in N_OVERLAP:
        raise ValueError("n_overlap must be 2 or 3")
    if len(others) < n_overlap - 1:
        raise ValueError(f"{n_overlap}-person overlap needs {n_overlap - 1} other speakers")
    if n_overlap == 2:
        return [{"speaker": target, "start": 0.0, "length": 6.0},
                {"speaker": others[0], "start": 2.0, "length": 6.0},
                {"speaker": target, "start": 9.0, "length": 3.0}]
    return [{"speaker": target, "start": 0.0, "length": 6.0},
            {"speaker": others[0], "start": 2.0, "length": 6.0},
            {"speaker": others[1], "start": 3.0, "length": 6.0},
            {"speaker": target, "start": 10.0, "length": 3.0}]


def regions_from_plan(plan: list[dict]) -> list[dict]:
    """Time spans with the set of speakers active in each (silence is skipped)."""
    pts = sorted({t for p in plan for t in (p["start"], p["start"] + p["length"])})
    out = []
    for lo, hi in zip(pts, pts[1:]):
        active = sorted({p["speaker"] for p in plan if p["start"] <= lo and p["start"] + p["length"] >= hi})
        if active:
            out.append({"start": lo, "end": hi, "active": active})
    return out


def condition_grid(count: int | None = None) -> list[dict]:
    """Every (n_overlap, target level, noise SNR) combination, in a fixed order;
    ``count`` keeps a varied subset."""
    grid = [{"n_overlap": n, "target_rel_db": g, "snr_db": s}
            for n, g, s in itertools.product(N_OVERLAP, TARGET_REL_DB, NOISE_SNR_DB)]
    if count is None or count >= len(grid):
        return grid
    # stride 7 is coprime with 24, so any prefix mixes sizes, levels and noise levels
    return [grid[(i * 7) % len(grid)] for i in range(count)]
