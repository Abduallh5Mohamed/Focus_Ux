"""In-memory fakes for worker tests: repository, targeting adapter, transcriber."""
from __future__ import annotations

from services.worker.errors import WorkerError
from services.worker.interfaces import TargetRunResult
from services.worker.models import Job


class InMemoryRepository:
    def __init__(self, jobs: list[Job] | None = None):
        self._jobs: dict[str, Job] = {}
        self.save_history: list[tuple[str, str]] = []
        self.emitted: list[dict] = []
        for job in jobs or []:
            self._jobs[job.job_id] = job.copied()

    def get(self, job_id: str) -> Job:
        return self._jobs[job_id].copied()

    def save(self, job: Job) -> None:
        self._jobs[job.job_id] = job.copied()
        self.save_history.append((job.status.value, job.stage.value))

    def all(self) -> list[Job]:
        return [j.copied() for j in self._jobs.values()]


class FakeTargeting:
    """Records calls, emits contract stages via on_progress, owns a real output artifact
    (or none, when artifact=False) and returns or raises."""

    def __init__(
        self,
        result: TargetRunResult | None = None,
        raise_with: WorkerError | None = None,
        raise_other: Exception | None = None,
        emit_stages: tuple[str, ...] = ("tracking", "separating"),
        artifact: bool = True,
    ):
        self.result = result
        self.raise_with = raise_with
        self.raise_other = raise_other
        self.emit_stages = emit_stages
        self.artifact = artifact
        self.calls: list[dict] = []

    def extract(self, job, job_dir, on_progress):
        self.calls.append({"job_id": job.job_id, "job_dir": job_dir, "video_path": job.video_path, "face_id": job.face_id})
        for stage in self.emit_stages:
            on_progress(stage, 0.5)
        if self.raise_other is not None:
            raise self.raise_other
        if self.raise_with is not None:
            raise self.raise_with
        result = self.result
        if result is None:
            import os

            wav_path = os.path.join(job_dir, "out.wav")
            if self.artifact:
                with open(wav_path, "wb") as fh:
                    fh.write(b"RIFF" + b"\x00" * 64)
            result = TargetRunResult(
                wav_path=wav_path,
                duration_ms=14000,
                timings={"separate_wall_s": 0.1},
                warnings=[
                    "fps resampling to 25fps is not implemented; input must be 25fps"
                ],
            )
        return result


class FakeTranscriber:
    def __init__(self, segments: list[dict] | None = None, raise_with: WorkerError | None = None, raise_other: Exception | None = None):
        self.segments = segments or [
            {"id": 3, "start_ms": 100, "end_ms": 900, "text": "mar7aba"},
            {"start_ms": 1000, "end_ms": 2000, "text": "salam"},
        ]
        self.raise_with = raise_with
        self.raise_other = raise_other
        self.wav_paths: list[str] = []

    def transcribe(self, wav_path, on_progress=None):
        self.wav_paths.append(wav_path)
        if self.raise_other is not None:
            raise self.raise_other
        if self.raise_with is not None:
            raise self.raise_with
        return self.segments


def make_job(job_id="job-1", status=None, **kw) -> Job:
    job = Job(
        job_id=job_id,
        video_id=kw.pop("video_id", "vid-1"),
        face_id=kw.pop("face_id", "face-9"),
        video_path=kw.pop("video_path", None),
        job_dir=kw.pop("job_dir", None),
        **kw,
    )
    if status is not None:
        job.status = status
    return job
