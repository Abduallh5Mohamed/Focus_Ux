"""Pydantic request models (responses are shaped explicitly to match the wire)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CreateJobRequest(BaseModel):
    video_id: str = Field(min_length=1, max_length=64)
    face_id: str = Field(min_length=1, max_length=128)
    client_request_id: str = Field(min_length=1, max_length=128)


class ExportRequest(BaseModel):
    voice_level: float | None = None
    others_level: float | None = None
    noise_reduction: str | None = None
