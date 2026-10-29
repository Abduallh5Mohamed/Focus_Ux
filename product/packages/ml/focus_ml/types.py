"""Contract payload types (docs/02_CONTRACTS.md), import-safe stdlib dataclasses."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from focus_ml.config import AdapterConfig


@dataclass
class FaceCandidate:
    """Face identity per contract (docs/02): ``bbox`` is (x, y, w, h) in
    ORIGINAL frame pixel coordinates, ``timestamp_ms`` is the frame position
    at the configured fps, ``frame_size`` is the original frame (w, h)."""

    face_id: str
    timestamp_ms: int
    bbox: tuple[int, int, int, int]
    frame_size: tuple[int, int]
    index: int = 0


@dataclass
class TargetSelection:
    face_id: str


@dataclass
class ExtractionResult:
    wav_path: str
    duration_ms: int
    source_offset_ms: int
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModelBundle:
    dolphin: object | None = None
    face_alignment: object | None = None
    device: str = "cuda"
    config: "AdapterConfig | None" = None
    loaded: bool = False
    # Activated legacy engine handles (same objects the adapter would otherwise
    # re-import/re-instantiate per request). None keeps the old "not loaded"
    # meaning; load_models fills these when the real backend load succeeds.
    inference: object | None = None
    detect_faces: object | None = None
