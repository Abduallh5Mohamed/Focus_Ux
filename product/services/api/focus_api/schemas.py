"""Pydantic request models (responses are shaped explicitly to match the wire)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=64)
    # audio_only engine: the enrollment replaces the face. Lip engines: face_id.
    face_id: str | None = Field(default=None, min_length=1, max_length=128)
    enrollment_id: str | None = Field(default=None, min_length=1, max_length=64)
    client_request_id: str = Field(min_length=1, max_length=128)


class SuggestionRequest(BaseModel):
    face_id: str = Field(min_length=1, max_length=128)


class EnrollmentRequest(BaseModel):
    face_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=16)
    voice_id: str | None = Field(default=None, max_length=32)
    start_ms: int | None = None
    end_ms: int | None = None


class ExportRequest(BaseModel):
    voice_level: float | None = None
    others_level: float | None = None
    noise_reduction: str | None = None
