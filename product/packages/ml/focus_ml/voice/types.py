"""Shared result types for the audio-only pipeline (seconds, plain dataclasses)."""
from __future__ import annotations

from dataclasses import dataclass, field

TARGET, OTHER, UNCERTAIN = "target", "other", "uncertain"
LABELS = (TARGET, OTHER, UNCERTAIN)
VOICEPRINT_FORMAT = "focus-voiceprint/1"
SAMPLE_RATE = 16000


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "speaker": self.speaker}


@dataclass
class Diarization:
    """Who spoke when. ``turns`` may overlap in time; ``overlaps`` are the spans
    where two or more speakers are active; ``speech`` is the union (VAD)."""
    turns: list[Segment]
    overlaps: list[Segment] = field(default_factory=list)
    speech: list[Segment] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        return sorted({t.speaker for t in self.turns if t.speaker is not None})

    def as_dict(self) -> dict:
        return {"speakers": self.speakers,
                "turns": [t.as_dict() for t in self.turns],
                "overlaps": [t.as_dict() for t in self.overlaps],
                "speech": [t.as_dict() for t in self.speech]}

    @classmethod
    def from_dict(cls, d: dict) -> "Diarization":
        seg = lambda x: Segment(float(x["start"]), float(x["end"]), x.get("speaker"))
        return cls([seg(x) for x in d["turns"]], [seg(x) for x in d["overlaps"]],
                   [seg(x) for x in d["speech"]])


@dataclass
class Voiceprint:
    vector: list[float]
    embedder: str
    duration_s: float
    source: dict
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"format": VOICEPRINT_FORMAT, "embedder": self.embedder,
                "dim": len(self.vector), "duration_s": round(self.duration_s, 3),
                "source": self.source, "warnings": self.warnings, "vector": self.vector}

    @classmethod
    def from_dict(cls, d: dict) -> "Voiceprint":
        if d.get("format") != VOICEPRINT_FORMAT:
            raise ValueError(f"not a {VOICEPRINT_FORMAT} voiceprint")
        return cls(list(d["vector"]), d["embedder"], float(d["duration_s"]),
                   dict(d.get("source") or {}), list(d.get("warnings") or []))


@dataclass
class LabelledRegion:
    start: float
    end: float
    label: str
    speaker: str | None
    score: float | None
    reason: str

    def as_dict(self) -> dict:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "label": self.label,
                "speaker": self.speaker, "reason": self.reason,
                "score": None if self.score is None else round(self.score, 4)}
