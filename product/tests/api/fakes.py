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


def _vp(embedder="ecapa", seconds=9.0, **source):
    return {"format": "focus-voiceprint/1", "vector": [0.1 * (i + 1) for i in range(8)],
            "embedder": embedder, "dim": 8, "duration_s": seconds, "source": source or {"kind": "x"},
            "warnings": []}


def make_analysis(duration_ms: int = 12000):
    import base64
    clip = base64.b64encode(make_wav_bytes(3000)).decode()
    turns = [{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"},
             {"start": 5.0, "end": 12.0, "speaker": "SPEAKER_01"},
             {"start": 12.0, "end": 12.5, "speaker": "SPEAKER_02"}]
    speakers = []
    for i, (name, usable) in enumerate((("SPEAKER_00", True), ("SPEAKER_01", True), ("SPEAKER_02", False))):
        speakers.append({
            "speaker": name, "speech_s": 5.0, "clean_s": 5.0 if usable else 0.5,
            "overlap_fraction": 0.0, "usable": usable,
            "refusal": None if usable else "Only 0.5 s of clean speech was found.",
            "warnings": [] if usable else [], "sample": {"start": 1.0, "end": 4.0} if usable else None,
            "sample_wav_b64": clip if usable else None,
            "voiceprint": _vp(source_speaker=name) if usable else None})
    return {"duration_ms": duration_ms, "embedder": "ecapa", "warnings": [], "speakers": speakers,
            "diarization": {"speakers": [s["speaker"] for s in speakers], "turns": turns,
                            "overlaps": [], "speech": [{"start": 0.0, "end": 12.5, "speaker": None}]}}


class FakeAudioProvider(FakeCandidateProvider):
    """Face detector plus the audio-only provider surface; no models involved."""

    def __init__(self, *, visible=None, visibility_error=None, analysis=None, refuse=None):
        super().__init__()
        self.visible = [{"start_ms": 5000, "end_ms": 12000}] if visible is None else visible
        self.visibility_error, self.refuse = visibility_error, refuse
        self.analysis = analysis
        self.calls_analyze = 0
        self.enroll_calls: list[dict] = []

    def analyze(self, *, video_id, video_path=None):
        self.calls_analyze += 1
        return self.analysis or make_analysis()

    def visibility(self, *, video_id, face):
        if self.visibility_error:
            raise self.visibility_error
        return list(self.visible)

    def enroll_range(self, *, video_id, diarization, start_ms, end_ms):
        self.enroll_calls.append({"mode": "range", "start_ms": start_ms, "end_ms": end_ms})
        if self.refuse:
            return {"refused": self.refuse}
        return {"voiceprint": _vp(kind="time_range"), "warnings": ["short sample"]}

    def enroll_file(self, *, video_id, wav_path):
        import os
        self.enroll_calls.append({"mode": "file", "existed": os.path.isfile(wav_path)})
        if self.refuse:
            return {"refused": self.refuse}
        return {"voiceprint": _vp(kind="voice_file"), "warnings": []}


class FakeAudioOnlyRunner(FakeExtractionRunner):
    """Records the job it received and returns target / uncertain periods."""

    def extract(self, job, job_dir, on_progress):
        result = super().extract(job, job_dir, on_progress)
        result.follow_periods = [
            {"start_ms": 0, "end_ms": 400, "state": "voice_follow", "reason": "voice_match",
             "output_allowed": True},
            {"start_ms": 400, "end_ms": 700, "state": "uncertain", "reason": "uncertain_voice",
             "output_allowed": False}]
        return result
