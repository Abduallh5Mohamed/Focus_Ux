"""Exception hierarchy aligned with docs/02_CONTRACTS.md error codes.

Payload/care rule: ``message`` is always user-safe (no system paths, no tool
stderr); raw diagnostics (paths, backend stderr, module names) live only in
``detail`` and are NEVER included in ``as_dict()``.
"""
from __future__ import annotations


class MlError(Exception):
    """Base error carrying the contract error shape: code, message, retryable.

    ``detail`` holds machine diagnostics for logs only; it is deliberately
    excluded from the payload produced by ``as_dict()``."""

    code: str = "PROCESSING_FAILED"

    def __init__(self, message: str, retryable: bool = False, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.detail = detail

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


class MediaError(MlError):
    code = "INVALID_MEDIA"


class LimitError(MlError):
    code = "LIMIT_EXCEEDED"


class NoAudioError(MlError):
    code = "NO_AUDIO"


class FaceNotFoundError(MlError):
    code = "FACE_NOT_FOUND"


class TargetLostError(MlError):
    code = "TARGET_LOST"

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message, retryable=True, detail=detail)


class GpuBusyError(MlError):
    code = "GPU_BUSY"

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message, retryable=True, detail=detail)


class ProcessingError(MlError):
    """Retriable by default: one shared per-code retryability vocabulary across
    packages (PROCESSING_FAILED is retryable=True everywhere, matching the
    worker package's default)."""

    def __init__(self, message: str, retryable: bool = True, detail: str = ""):
        super().__init__(message, retryable=retryable, detail=detail)


class ModelUnavailableError(ProcessingError):
    """Raised honestly when the real legacy Dolphin/torch backend cannot be
    loaded (missing torch, missing engine modules, missing model source path,
    no CUDA device). Never used to mask a fabricated successful extraction."""
