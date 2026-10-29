"""Injected worker dependencies: repository, targeting adapter, transcripts.

The worker depends only on these protocols and plain data types, never on
focus_ml or torch. The real adapter implementation (focus_ml from
packages/ml, and the API-owned sqlite repository) plugs in from the outside.

Claim ownership: the worker is the sole performer of the queued -> processing
claim; the API (or any queue dispatcher) hands over job ids whose repository
state is still QUEUED. If instead the DB layer claims atomically, it must not
do so before dispatching to SingleWorker.process. (docs/02 "Job lifecycle")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .models import Job

StageListener = Callable[[Job], None]
AdapterProgress = Callable[[str, float], None]

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class TargetRunResult:
    """Plain outcome of an extract_target run; mirrors ExtractionResult shape."""
    wav_path: str
    duration_ms: int
    source_offset_ms: int = 0
    timings: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class JobRepository(Protocol):
    """Persistence boundary. The real implementation is sqlite owned by API; tests use fakes."""

    def get(self, job_id: str) -> Job: ...

    def save(self, job: Job) -> None: ...

    def all(self) -> list[Job]: ...


class FaceTargeting(Protocol):
    """Adapter boundary; mirrors the packages/ml extract_target contract functions."""

    def extract(self, job: Job, job_dir: str, on_progress: AdapterProgress) -> TargetRunResult: ...


class TranscriptProvider(Protocol):
    """ASR boundary: receives a wav path, returns segments on the video timeline."""

    def transcribe(self, wav_path: str, on_progress: AdapterProgress | None = None) -> list[dict]: ...


class WorkerLayout(Protocol):
    """Maps a job to its trusted artifact directory. Real impl resolves from config."""

    def job_dir(self, job: Job) -> str: ...


@dataclass
class JobDirectoryLayout:
    """Layout keyed on job_id; job ids are operator/API-supplied, not user free-text, but the
    layout still rejects anything outside [A-Za-z0-9_-] so an id can never escape the root."""

    job_dir_root: str

    def job_dir(self, job: Job) -> str:
        import os

        if not _SAFE_JOB_ID.match(job.job_id):
            from .errors import MediaError

            raise MediaError("job id is not a safe directory name")
        return os.path.join(self.job_dir_root, job.job_id)
