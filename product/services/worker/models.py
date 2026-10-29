"""Job state model for the FOCUS worker, aligned with docs/02_CONTRACTS.md.

Statuses, stages, audio/transcript independence and the unified error payload
follow the contract. This module is stdlib-only and holds no torch/adapter
objects; adapters communicate through plain data results.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStage(str, Enum):
    VALIDATING = "validating"
    PREPARING = "preparing"
    TRACKING = "tracking"
    SEPARATING = "separating"
    TRANSCRIBING = "transcribing"
    READY = "ready"


class AudioStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class TranscriptStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class ErrorPayload:
    code: str
    message: str
    retryable: bool = False


@dataclass
class TranscriptSegment:
    id: int
    start_ms: int
    end_ms: int
    text: str


@dataclass
class Job:
    job_id: str
    video_id: str
    face_id: Optional[str] = None
    client_request_id: Optional[str] = None
    video_path: Optional[str] = None
    job_dir: Optional[str] = None
    status: JobStatus = JobStatus.QUEUED
    stage: JobStage = JobStage.VALIDATING
    audio_status: AudioStatus = AudioStatus.PENDING
    transcript_status: TranscriptStatus = TranscriptStatus.PENDING
    wav_path: Optional[str] = None
    duration_ms: Optional[int] = None
    source_offset_ms: int = 0
    audio_warnings: list[str] = field(default_factory=list)
    # Voice-follow periods (focus_ml.voice_follow.Period.as_dict()); empty until
    # an approved voiceprint model is integrated.
    follow_periods: list[dict] = field(default_factory=list)
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    error: Optional[ErrorPayload] = None
    queue_position: int = 0

    def copied(self) -> "Job":
        clone = copy.copy(self)
        clone.audio_warnings = list(self.audio_warnings)
        clone.follow_periods = [dict(p) for p in self.follow_periods]
        clone.transcript_segments = list(self.transcript_segments)
        if self.error is not None:
            clone.error = ErrorPayload(**vars(self.error))
        return clone

    def snapshot(self) -> dict:
        """Contract-shaped view of the job (docs/02_CONTRACTS.md "حالة الطلب")."""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "stage": self.stage.value,
            "selected_face_id": self.face_id,
            "audio_status": self.audio_status.value,
            "transcript_status": self.transcript_status.value,
            "queue_position": self.queue_position,
            "error": None
            if self.error is None
            else {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
            },
            # Server paths are never exposed; audio is served via GET /jobs/{id}/audio
            # (docs/02 HTTP contract). result is non-null only for completed jobs.
            "result": None
            if self.status is not JobStatus.COMPLETED
            else {
                "duration_ms": self.duration_ms,
                "source_offset_ms": self.source_offset_ms,
                "transcript_status": self.transcript_status.value,
                **({"follow_periods": self.follow_periods} if self.follow_periods else {}),
            },
        }
