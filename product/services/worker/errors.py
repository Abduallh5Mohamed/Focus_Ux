"""Worker-side error vocabulary matching the contract codes in docs/02_CONTRACTS.md.

The ML adapter package (focus_ml.errors) defines its own exceptions with the same
code strings; integration glue (not this package) maps between them, so the
worker never imports focus_ml.
"""
from __future__ import annotations


class WorkerError(Exception):
    code = "PROCESSING_FAILED"
    message = "processing failed"
    retryable = True

    def __init__(self, message: str | None = None, *, retryable: bool | None = None):
        super().__init__(message if message is not None else self.message)
        if message is not None:
            self.message = message
        if retryable is not None:
            self.retryable = retryable

    def payload(self) -> tuple[str, str, bool]:
        return self.code, self.message, self.retryable


class MediaError(WorkerError):
    code = "INVALID_MEDIA"
    retryable = False


class LimitExceededError(WorkerError):
    code = "LIMIT_EXCEEDED"
    retryable = False


class NoAudioError(WorkerError):
    code = "NO_AUDIO"
    retryable = False


class FaceNotFoundError(WorkerError):
    code = "FACE_NOT_FOUND"
    retryable = False


class TargetLostError(WorkerError):
    code = "TARGET_LOST"
    retryable = True


class GpuBusyError(WorkerError):
    code = "GPU_BUSY"
    retryable = True


class ProcessingError(WorkerError):
    code = "PROCESSING_FAILED"
    retryable = True


class TranscriptError(ProcessingError):
    """Transcript-only failure. ``reason`` is a short stable label (not_configured,
    model_unavailable, out_of_memory, timeout, worker_offline, failed) that the API
    surfaces so the UI can tell the user what happened; audio is unaffected."""

    reason = "failed"

    def __init__(self, message: str | None = None, *, reason: str | None = None,
                 retryable: bool | None = None):
        super().__init__(message, retryable=retryable)
        if reason is not None:
            self.reason = reason


class TranscriptUnavailableError(TranscriptError):
    reason = "not_configured"

    def __init__(self):
        super().__init__("transcript provider not configured", retryable=True)
