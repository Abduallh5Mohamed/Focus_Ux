"""Explicit test doubles. They live only under tests/api (AGENTS.md rule).

The API itself has no fake-success path: the default provider/runner raise
honestly, and these fakes are injected by tests.
"""
from __future__ import annotations

import io
import os
import wave

from services.api.focus_api.interfaces import DetectedFace, ProviderError
from services.worker.interfaces import TargetRunResult


def make_wav_bytes(duration_ms: int = 1000, sample_rate: int = 16000) -> bytes:
    frames = int(sample_rate * duration_ms / 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


DEFAULT_FACES = [
    DetectedFace(
        bbox=(10, 20, 30, 40),
        timestamp_ms=0,
        frame_size=(640, 360),
        thumbnail_bytes=b"\xff\xd8\xff\xe0FAKE-JPEG-ONE\xff\xd9",
        thumbnail_mime="image/jpeg",
    ),
    DetectedFace(
        bbox=(100, 50, 60, 70),
        timestamp_ms=0,
        frame_size=(640, 360),
        thumbnail_bytes=b"\xff\xd8\xff\xe0FAKE-JPEG-TWO\xff\xd9",
        thumbnail_mime="image/jpeg",
    ),
]


class FakeCandidateProvider:
    def __init__(self, faces=None, raise_with: Exception | None = None):
        self.faces = list(faces) if faces is not None else list(DEFAULT_FACES)
        self.raise_with = raise_with
        self.calls: list[dict] = []

    def detect(self, *, video_id: str, video_path: str):
        self.calls.append({"video_id": video_id, "video_path": video_path})
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.faces)


class FakeExtractionRunner:
    def __init__(
        self,
        *,
        duration_ms: int = 1000,
        artifact: bool = True,
        raise_with: Exception | None = None,
        stages=("tracking", "separating"),
    ):
        self.duration_ms = duration_ms
        self.artifact = artifact
        self.raise_with = raise_with
        self.stages = tuple(stages)
        self.calls: list[dict] = []

    def extract(self, job, job_dir, on_progress):
        self.calls.append(
            {
                "job_id": job.job_id,
                "video_id": job.video_id,
                "video_path": job.video_path,
                "face_id": job.face_id,
                "job_dir": job_dir,
            }
        )
        for stage in self.stages:
            on_progress(stage, 0.5)
        if self.raise_with is not None:
            raise self.raise_with
        os.makedirs(job_dir, exist_ok=True)
        wav_path = os.path.join(job_dir, "target_extract.wav")
        if self.artifact:
            with open(wav_path, "wb") as handle:
                handle.write(make_wav_bytes(self.duration_ms))
        return TargetRunResult(
            wav_path=wav_path,
            duration_ms=self.duration_ms,
            source_offset_ms=0,
            timings={"separate_wall_s": 0.01},
            warnings=[],
        )


class FakeTranscriber:
    def __init__(self, segments=None, raise_with: Exception | None = None):
        self.segments = (
            list(segments)
            if segments is not None
            else [
                {"id": 7, "start_ms": 0, "end_ms": 500, "text": "first"},
                {"start_ms": 500, "end_ms": 900, "text": "second"},
            ]
        )
        self.raise_with = raise_with
        self.calls: list[str] = []

    def transcribe(self, wav_path, on_progress=None):
        self.calls.append(wav_path)
        if self.raise_with is not None:
            raise self.raise_with
        return list(self.segments)


def provider_failure(message: str = "detector exploded") -> FakeCandidateProvider:
    return FakeCandidateProvider(raise_with=ProviderError(message, code="FACE_NOT_FOUND", retryable=False))
