"""Voice-follow logic: continue the chosen speaker by voiceprint when the face
is hidden. Pure CPU logic; the speaker-embedding model and the
voiceprint-conditioned separator are INJECTED (``SpeakerEmbedder``) because
no such models are approved/downloaded yet (see docs/05_VOICE_FOLLOW.md).

Privacy: the voiceprint lives only in memory for one job; ``discard()`` wipes it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence

VISUAL = "visual"
VOICE_FOLLOW = "voice_follow"
UNCERTAIN = "uncertain"
CONFLICT = "conflict"


class SpeakerEmbedder(Protocol):
    def embed(self, wav_path: str, start_ms: int, end_ms: int) -> Sequence[float]: ...


@dataclass
class VoiceFollowConfig:
    min_enroll_ms: int = 4000          # accepted clear-speech time required (3-5 s)
    min_lip_motion: float = 0.5        # 0..1 lip-movement score for enrollment
    min_quality: float = 0.6           # 0..1 clarity (e.g. SNR-derived) for enrollment
    follow_threshold: float = 0.6      # cosine >= this: same speaker (face hidden)
    conflict_threshold: float = 0.4    # face visible and cosine < this: conflict


@dataclass
class Observation:
    start_ms: int
    end_ms: int
    face_visible: bool
    embedding: Optional[Sequence[float]] = None  # embedding of the isolated output
    lip_motion: float = 0.0
    quality: float = 0.0


@dataclass
class Period:
    start_ms: int
    end_ms: int
    state: str
    reason: str
    similarity: Optional[float] = None
    output_allowed: bool = True   # False: audio must be muted, never another speaker's voice

    def as_dict(self) -> dict:
        return {
            "start_ms": self.start_ms, "end_ms": self.end_ms, "state": self.state,
            "reason": self.reason, "similarity": self.similarity,
            "output_allowed": self.output_allowed,
        }


def _norm(vec: Sequence[float]) -> list[float]:
    n = math.sqrt(sum(v * v for v in vec))
    return [v / n for v in vec] if n > 0 else [0.0] * len(vec)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("embedding dimensions differ")
    return sum(x * y for x, y in zip(_norm(a), _norm(b)))


@dataclass
class VoiceprintEnroller:
    config: VoiceFollowConfig = field(default_factory=VoiceFollowConfig)
    _sum: Optional[list[float]] = None
    _accepted_ms: int = 0
    _rejected_ms: int = 0

    def add(self, obs: Observation) -> bool:
        """Accept only face-visible, lip-moving, clear segments."""
        cfg = self.config
        duration = max(0, obs.end_ms - obs.start_ms)
        ok = (
            obs.face_visible and obs.embedding is not None and duration > 0
            and obs.lip_motion >= cfg.min_lip_motion and obs.quality >= cfg.min_quality
        )
        if not ok:
            self._rejected_ms += duration
            return False
        emb = _norm(obs.embedding)
        if self._sum is None:
            self._sum = [0.0] * len(emb)
        elif len(emb) != len(self._sum):
            raise ValueError("embedding dimensions differ")
        self._sum = [s + e * duration for s, e in zip(self._sum, emb)]
        self._accepted_ms += duration
        return True

    @property
    def accepted_ms(self) -> int:
        return self._accepted_ms

    @property
    def ready(self) -> bool:
        return self._sum is not None and self._accepted_ms >= self.config.min_enroll_ms

    def voiceprint(self) -> Optional[list[float]]:
        """None until enough clear speech was collected (never a weak print)."""
        return _norm(self._sum) if self.ready else None

    def discard(self) -> None:
        self._sum = None
        self._accepted_ms = 0
        self._rejected_ms = 0


def classify(
    observations: Sequence[Observation],
    voiceprint: Optional[Sequence[float]],
    config: VoiceFollowConfig | None = None,
) -> list[Period]:
    """Label each period; a hidden face with a weak/low-similarity match is
    'uncertain' with output muted so another speaker is never passed off as
    the chosen one. A visible face whose output disagrees with the voiceprint
    is a recorded 'conflict' (muted), never silent continuation."""
    cfg = config or VoiceFollowConfig()
    periods: list[Period] = []
    for obs in observations:
        sim = None
        if voiceprint is not None and obs.embedding is not None:
            sim = round(cosine(voiceprint, obs.embedding), 6)
        if obs.face_visible:
            if sim is not None and sim < cfg.conflict_threshold:
                p = Period(obs.start_ms, obs.end_ms, CONFLICT, "voice_mismatch_with_face", sim, False)
            else:
                p = Period(obs.start_ms, obs.end_ms, VISUAL, "face_visible", sim, True)
        elif voiceprint is None:
            p = Period(obs.start_ms, obs.end_ms, UNCERTAIN, "no_voiceprint", None, False)
        elif sim is None:
            p = Period(obs.start_ms, obs.end_ms, UNCERTAIN, "no_speech_embedding", None, False)
        elif sim >= cfg.follow_threshold:
            p = Period(obs.start_ms, obs.end_ms, VOICE_FOLLOW, "face_hidden_voice_match", sim, True)
        else:
            p = Period(obs.start_ms, obs.end_ms, UNCERTAIN, "low_similarity", sim, False)
        periods.append(p)
    return periods


def wrong_person_rate(periods: Sequence[Period], truth_is_target: Sequence[bool]) -> dict:
    """Wrong-person rate over face-hidden periods: audio emitted
    (output_allowed) while the ground truth says it is NOT the target."""
    if len(periods) != len(truth_is_target):
        raise ValueError("periods and truth must align")
    hidden = [(p, t) for p, t in zip(periods, truth_is_target)
              if p.state in (VOICE_FOLLOW, UNCERTAIN)]
    wrong = sum(1 for p, t in hidden if p.output_allowed and not t)
    total_ms = sum(p.end_ms - p.start_ms for p, _ in hidden)
    wrong_ms = sum(p.end_ms - p.start_ms for p, t in hidden if p.output_allowed and not t)
    return {
        "hidden_periods": len(hidden), "wrong_periods": wrong,
        "rate": (wrong / len(hidden)) if hidden else 0.0,
        "hidden_ms": total_ms, "wrong_ms": wrong_ms,
    }
