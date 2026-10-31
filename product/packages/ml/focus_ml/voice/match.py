"""Target / other / uncertain classification of speech regions.

Cosine similarity to the voiceprint, two thresholds:
  score >= target_threshold  -> target
  score <= other_threshold   -> other
  between                    -> uncertain (never given to the target).
Overlapping speech and fragments too short to measure are uncertain, too.
Defaults come from calibration on the evaluation set (see docs/VOICE_PIPELINE.md);
they are overridable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .embedder import MIN_EMBED_S, Embedder, embed_segments
from .segments import subtract
from .types import OTHER, TARGET, UNCERTAIN, Diarization, LabelledRegion, Segment, Voiceprint

# (target, other) cosine thresholds per embedder. PROVISIONAL: calibrated on the
# NON-Egyptian LibriSpeech synthetic set (mixes 01-05, clean; see docs/VOICE_PIPELINE_LOG.md).
# Recalibrate on the Egyptian recordings before relying on them:
#   python -m focus_eval voice-calibrate --mixes M --run R
DEFAULT_THRESHOLDS = {
    "ecapa": (0.4081, 0.3581),
    "pyannote": (0.4393, 0.3893),
}


@dataclass
class MatchConfig:
    target_threshold: float = 0.4081
    other_threshold: float = 0.3581
    min_region_s: float = MIN_EMBED_S
    max_chunk_s: float = 3.0

    def __post_init__(self):
        if self.other_threshold > self.target_threshold:
            raise ValueError("other_threshold must not exceed target_threshold")

    @classmethod
    def for_embedder(cls, name: str) -> "MatchConfig":
        t, o = DEFAULT_THRESHOLDS[name]
        return cls(target_threshold=t, other_threshold=o)


def classify_score(score: float, cfg: MatchConfig) -> str:
    if score >= cfg.target_threshold:
        return TARGET
    if score <= cfg.other_threshold:
        return OTHER
    return UNCERTAIN


def cosine(a, b) -> float:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def split_regions(diar: Diarization, max_chunk_s: float) -> list[Segment]:
    """Solo speech split into chunks of at most ``max_chunk_s`` (overlap excluded)."""
    out = []
    for solo in subtract(diar.turns, diar.overlaps):
        n = max(1, int(np.ceil(solo.duration / max_chunk_s)))
        step = solo.duration / n
        out += [Segment(solo.start + i * step, solo.start + (i + 1) * step, solo.speaker)
                for i in range(n)]
    return out


def classify_regions(samples, diar: Diarization, voiceprint: Voiceprint, embedder: Embedder,
                     cfg: MatchConfig | None = None) -> list[LabelledRegion]:
    cfg = cfg or MatchConfig.for_embedder(embedder.name)
    if voiceprint.embedder != embedder.name:
        raise ValueError(f"voiceprint was made with {voiceprint.embedder!r}, "
                         f"not {embedder.name!r}; enroll again with this embedder")
    regions = [LabelledRegion(o.start, o.end, UNCERTAIN, None, None, "overlap") for o in diar.overlaps]
    for seg in split_regions(diar, cfg.max_chunk_s):
        if seg.duration < cfg.min_region_s:
            regions.append(LabelledRegion(seg.start, seg.end, UNCERTAIN, seg.speaker, None, "too_short"))
            continue
        vec, _ = embed_segments(embedder, samples, [seg], min_s=cfg.min_region_s)
        score = cosine(voiceprint.vector, vec)
        label = classify_score(score, cfg)
        regions.append(LabelledRegion(seg.start, seg.end, label, seg.speaker, score, "voice_match"))
    return sorted(regions, key=lambda r: (r.start, r.end))
