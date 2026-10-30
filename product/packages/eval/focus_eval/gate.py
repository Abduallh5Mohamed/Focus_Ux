"""Adoption gate for a speed optimisation: quality must hold AND speed must hit the target on every clip."""
from __future__ import annotations

from .compare import Thresholds, compare_reports

DEFAULT_RTF_TARGET = 0.8


def _scored_clips(report: dict) -> set[str]:
    return {r["clip_id"] for r in report["rows"] if r["audio_status"] == "ok"}


def decide(base: dict, cand: dict, th: Thresholds | None = None, rtf_target: float = DEFAULT_RTF_TARGET) -> dict:
    """verdict: adopt | reject | inconclusive.

    - quality: ``compare_reports`` must pass (SI-SDRi drop over the threshold on
      ANY target, a newly wrong person, lost/truncated/dropped-out audio, or a
      CER increase all reject with a scorable baseline; differing datasets,
      outdated evaluation policies, incomplete baseline coverage or nothing
      scored are inconclusive);
    - speed: every clip in the candidate report needs its own bench entry with
      no failed chunk and RTF <= target, and must be faster than the baseline's
      entry for that clip when the baseline has one. A clip without a bench
      entry makes the verdict inconclusive.
    """
    cmp = compare_reports(base, cand, th)
    reasons: list[str] = []
    cb = cand.get("bench_by_clip") or {}
    bb = base.get("bench_by_clip") or {}
    clips = sorted({r["clip_id"] for r in cand["rows"]})
    if cmp["status"] == "inconclusive":
        verdict = "inconclusive"
        reasons += cmp["inconclusive_reasons"]
    else:
        verdict = "adopt"
        if cmp["status"] == "regression":
            verdict = "reject"
            reasons += [f"quality: {r['kind']} {r.get('clip_id', 'overall')}/{r.get('speaker_id', '')}".rstrip("/")
                        for r in cmp["regressions"]]
        missing = [c for c in clips if (cb.get(c) or {}).get("rtf") is None and not (cb.get(c) or {}).get("n_failed")]
        if missing:
            if verdict == "adopt":
                verdict = "inconclusive"
            reasons.append("no speed measurement for clip(s): " + ", ".join(missing)
                           + " (run bench_chunks on the GPU machine for each)")
        for c in clips:
            entry = cb.get(c)
            if not entry:
                continue
            if entry.get("n_failed"):
                verdict = "reject"
                reasons.append(f"speed: clip {c}: {entry['n_failed']} chunk(s) failed")
            elif entry.get("rtf") is not None:
                if entry["rtf"] > rtf_target:
                    verdict = "reject"
                    reasons.append(f"speed: clip {c}: RTF {entry['rtf']} is above the target {rtf_target}")
                base_rtf = (bb.get(c) or {}).get("rtf")
                if base_rtf is not None and entry["rtf"] >= base_rtf:
                    verdict = "reject"
                    reasons.append(f"speed: clip {c}: RTF {entry['rtf']} is not faster than baseline {base_rtf}")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "rtf": {
            "baseline": {c: (bb.get(c) or {}).get("rtf") for c in clips},
            "candidate": {c: (cb.get(c) or {}).get("rtf") for c in clips},
            "target": rtf_target,
        },
        "quality": cmp,
    }
