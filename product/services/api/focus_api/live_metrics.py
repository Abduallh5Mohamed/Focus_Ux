"""Pure metric summary and gate decision for the experimental live mode.

Numbers come only from what was measured. Anything unmeasured stays ``None`` and
blocks the gate; nothing is estimated or filled in.
"""
from __future__ import annotations

from statistics import median
from typing import Optional, Sequence

RTF_TARGET = 0.8
P95_TARGET_S = 3.0
MIN_SESSION_S = 60.0


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    pos = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[pos]


def summarize(
    *,
    chunks: Sequence[dict],
    depth_samples: Sequence[int],
    duplicates_ingested: int,
    playback: Optional[dict],
    overload_seq: Optional[int],
) -> dict:
    """``chunks`` rows: seq, state, duration_ms, processing_s, server_latency_s."""
    ready = [c for c in chunks if c["state"] == "ready"]
    audio_s = sum(c["duration_ms"] for c in ready) / 1000
    proc_s = sum(c["processing_s"] or 0 for c in ready)
    session_s = sum(c["duration_ms"] for c in chunks) / 1000
    server_lat = [c["server_latency_s"] for c in ready if c.get("server_latency_s") is not None]
    out = {
        "session_s": round(session_s, 3),
        "chunks_total": len(chunks),
        "chunks_ready": len(ready),
        "chunks_missing": sum(1 for c in chunks if c["state"] == "missing"),
        "chunks_unusable": sum(
            1 for c in chunks
            if c["state"] in ("target_lost", "uncertain", "failed", "undecodable")
        ),
        "chunks_duplicated": duplicates_ingested,
        "rtf": round(proc_s / audio_s, 4) if audio_s > 0 else None,
        "max_queue_depth": max(depth_samples, default=0),
        "overload_at_seq": overload_seq,
        "server_ready_latency_s": {
            "median": round(median(server_lat), 3) if server_lat else None,
            "p95": round(percentile(server_lat, 0.95), 3) if server_lat else None,
            "note": "from chunk fully received to isolated audio ready; excludes capture window and playback",
        },
        "capture_to_play_s": None,
        "playback": None,
    }
    if playback:
        rows = [r for r in playback.get("chunks", []) if r.get("audible_wall_ms") is not None]
        lat = [(r["audible_wall_ms"] - r["capture_wall_ms"]) / 1000 for r in rows]
        plays = {}
        for r in playback.get("chunks", []):
            plays[r["seq"]] = plays.get(r["seq"], 0) + (1 if r.get("audible_wall_ms") is not None else 0)
        out["capture_to_play_s"] = {
            "n": len(lat),
            "median": round(median(lat), 3) if lat else None,
            "p95": round(percentile(lat, 0.95), 3) if lat else None,
            "max": round(max(lat), 3) if lat else None,
        }
        out["playback"] = {
            "underruns": int(playback.get("underruns", 0)),
            "rebuffers": int(playback.get("rebuffers", 0)),
            "duplicate_plays": sum(1 for n in plays.values() if n > 1),
        }
    return out


def evaluate_gate(summary: dict, *, quality_checked: bool = False) -> dict:
    """H18 gate (docs/04_REALTIME_GATE.md). Passing enables the *experimental* flag only."""
    reasons: list[str] = []
    if summary["session_s"] < MIN_SESSION_S:
        reasons.append(f"session shorter than {MIN_SESSION_S:.0f}s")
    rtf = summary["rtf"]
    if rtf is None:
        reasons.append("RTF not measured")
    elif rtf > RTF_TARGET:
        reasons.append(f"RTF {rtf} > {RTF_TARGET}")
    if summary["overload_at_seq"] is not None:
        reasons.append("queue overloaded; session fell back to record-then-process")
    if summary["chunks_missing"] or summary["chunks_unusable"]:
        reasons.append("chunks were missing or unusable")
    lat = summary["capture_to_play_s"]
    if not lat or lat["p95"] is None:
        reasons.append("capture-to-play not measured in a browser")
    elif lat["p95"] > P95_TARGET_S:
        reasons.append(f"capture-to-play p95 {lat['p95']}s > {P95_TARGET_S}s")
    if not quality_checked:
        reasons.append("quality comparison against the upload path not done")
    return {
        "decision": "enable_experimental" if not reasons else "internal_only",
        "reasons": reasons,
    }
