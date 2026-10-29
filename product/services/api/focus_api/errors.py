"""Unified API error shape: ``{"error": {code, message, retryable}}``.

Codes follow docs/02_CONTRACTS.md. Messages are user-safe: no system paths,
no tool stderr, no tracebacks.
"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Raised by the service layer; rendered by the FastAPI exception handler."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.headers = headers or {}

    def payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


def unauthorized(message: str = "a valid session bearer token is required") -> ApiError:
    return ApiError("UNAUTHORIZED", message, status_code=401, retryable=False)


def not_found(message: str = "resource not found") -> ApiError:
    return ApiError("NOT_FOUND", message, status_code=404, retryable=False)


def invalid_request(message: str) -> ApiError:
    return ApiError("INVALID_REQUEST", message, status_code=400, retryable=False)


def invalid_media(message: str) -> ApiError:
    return ApiError("INVALID_MEDIA", message, status_code=400, retryable=False)


def limit_exceeded(message: str) -> ApiError:
    return ApiError("LIMIT_EXCEEDED", message, status_code=413, retryable=False)


def face_not_found(message: str = "face candidate not found") -> ApiError:
    return ApiError("FACE_NOT_FOUND", message, status_code=404, retryable=False)


def not_ready(message: str) -> ApiError:
    return ApiError("PROCESSING_FAILED", message, status_code=409, retryable=True)


def no_audio(message: str = "no audio is available for this job") -> ApiError:
    return ApiError("NO_AUDIO", message, status_code=409, retryable=False)
