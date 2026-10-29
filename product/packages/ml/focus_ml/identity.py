"""Selection identity: the core fix for the legacy ``db[:n_spk]`` gap.

Legacy detectface/focus_runner truncated detections to the first N speakers,
so a visitor picking the second face got the first one's audio. Here selection
matches the chosen target back to a candidate BY FACE IDENTITY, never by list
order or first-N truncation.
"""
from __future__ import annotations

import hashlib

from focus_ml.errors import FaceNotFoundError
from focus_ml.types import FaceCandidate, TargetSelection

FIRST_FRAME_LIMIT_WARNING = (
    "day-1 selection is limited to the first detected frame; a target whose "
    "timestamp_ms is beyond the first frame requires validated engine support "
    "that does not exist yet"
)


def make_face_id(
    video_id: str,
    timestamp_ms: int,
    bbox: tuple[int, int, int, int],
    frame_size: tuple[int, int],
) -> str:
    """Deterministic face_id hash over canonical repr, per contract: video +
    timestamp + bbox in ORIGINAL frame coordinates + frame size."""
    canonical = f"v={video_id}|t={int(timestamp_ms)}|b={tuple(bbox)}|s={tuple(frame_size)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def candidate_identity(candidate: FaceCandidate) -> tuple:
    """Video-independent canonical tuple used to match a chosen target back to
    a candidate."""
    return (
        int(candidate.timestamp_ms),
        tuple(candidate.bbox),
        tuple(candidate.frame_size),
        int(candidate.index),
    )


def targets_match(candidate: FaceCandidate, face_id: str) -> bool:
    """Exact face_id equality; ordering of the candidate list is irrelevant."""
    return candidate.face_id == face_id


def select_target_speaker(
    candidates: list[FaceCandidate], target: TargetSelection
) -> tuple[int, FaceCandidate]:
    """Return (speaker_slot, candidate) whose face_id equals target.face_id.

    Raises FaceNotFoundError (with the first-frame limitation message) when no
    candidate identity matches; this replaces the legacy identity-free
    ``db[:n_spk]`` truncation.
    """
    for position, candidate in enumerate(candidates):
        if targets_match(candidate, target.face_id):
            return position, candidate
    raise FaceNotFoundError(
        f"selected face_id {target.face_id!r} does not match any candidate "
        f"identity; {FIRST_FRAME_LIMIT_WARNING}"
    )
