"""FOCUS worker package: single-concurrency job engine with injected adapters.

Owns no storage, GPU code, or API surface: platforms plug in a JobRepository,
a FaceTargeting adapter (packages/ml focus_ml) and a TranscriptProvider.
"""
from .errors import (
    FaceNotFoundError,
    GpuBusyError,
    LimitExceededError,
    MediaError,
    NoAudioError,
    ProcessingError,
    TargetLostError,
    TranscriptUnavailableError,
    WorkerError,
)
from .interfaces import (
    AdapterProgress,
    FaceTargeting,
    JobDirectoryLayout,
    JobRepository,
    StageListener,
    TargetRunResult,
    TranscriptProvider,
    WorkerLayout,
)
from .models import (
    AudioStatus,
    ErrorPayload,
    Job,
    JobStage,
    JobStatus,
    TranscriptSegment,
    TranscriptStatus,
)
from .worker import SingleWorker

__all__ = [
    "SingleWorker",
    "Job",
    "JobStatus",
    "JobStage",
    "AudioStatus",
    "TranscriptStatus",
    "TranscriptSegment",
    "ErrorPayload",
    "TargetRunResult",
    "JobRepository",
    "FaceTargeting",
    "TranscriptProvider",
    "WorkerLayout",
    "JobDirectoryLayout",
    "AdapterProgress",
    "StageListener",
    "WorkerError",
    "MediaError",
    "LimitExceededError",
    "NoAudioError",
    "FaceNotFoundError",
    "TargetLostError",
    "GpuBusyError",
    "ProcessingError",
    "TranscriptUnavailableError",
]
