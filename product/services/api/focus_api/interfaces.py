"""Injected boundaries so the API never loads a model inside a request.

Two seams are defined here:

``FaceCandidateProvider``
    Receives the real API video UUID and the trusted canonical media path and
    returns plain :class:`DetectedFace` values. The real implementation (wired
    by the integration owner) wraps ``focus_ml``; tests use an explicit fake.

``ExtractionRunner``
    Matches the worker's ``FaceTargeting.extract(job, job_dir, on_progress)``
    protocol exactly, so it can be passed straight to ``SingleWorker``. It must
    write a non-empty WAV inside ``job_dir`` or raise a worker-compatible error;
    the worker refuses to mark a job READY without that artifact.

No torch/focus_ml import happens in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from services.worker.errors import ProcessingError
from services.worker.interfaces import AdapterProgress, TargetRunResult
from services.worker.models import Job


@dataclass
class DetectedFace:
    """Provider output before API-side identity hashing.

    ``bbox`` is (x, y, w, h) in canonical/original frame pixels; ``frame_size``
    is (width, height). ``video_id`` is NOT part of this value: the provider
    always receives it from the dispatcher, so identity can never fall back to a
    file basename.
    """

    bbox: tuple[int, int, int, int]
    timestamp_ms: int = 0
    frame_size: tuple[int, int] = (0, 0)
    thumbnail_bytes: Optional[bytes] = None
    thumbnail_mime: str = "image/jpeg"
    warnings: list[str] = field(default_factory=list)


class FaceCandidateProvider(Protocol):
    def detect(self, *, video_id: str, video_path: str) -> list[DetectedFace]: ...


class ExtractionRunner(Protocol):
    def extract(
        self, job: Job, job_dir: str, on_progress: AdapterProgress
    ) -> TargetRunResult: ...


class ProviderError(Exception):
    """Honest provider failure; ``code`` follows the contract error vocabulary."""

    def __init__(self, message: str, code: str = "PROCESSING_FAILED", retryable: bool = True):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retryable = retryable


class UnavailableCandidateProvider:
    """Default until the integration owner injects the real ML detector."""

    def detect(self, *, video_id: str, video_path: str) -> list[DetectedFace]:
        raise ProviderError(
            "face candidate provider is not configured", code="PROCESSING_FAILED"
        )


class UnavailableExtractionRunner:
    """Default until the integration owner injects the real ML extractor."""

    def extract(self, job: Job, job_dir: str, on_progress: AdapterProgress) -> TargetRunResult:
        raise ProcessingError(
            "extraction runner is not configured", retryable=True
        )
