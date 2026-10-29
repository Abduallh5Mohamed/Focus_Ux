"""Single-concurrency FOCUS worker engine.

Executes one queued job end to end with stage callbacks, independent
audio/transcript state, honest failure transitions and cancellation between
stages. Persistence is injected (JobRepository); GPU/ML work is injected
(FaceTargeting); ASR is injected (TranscriptProvider). This module imports no
torch, no focus_ml, no sqlite.

Contract rule honored here: final status is completed as long as audio is
ready, even when transcript_status=failed (docs/02_CONTRACTS.md).

Claim ownership (docs/02 "Job lifecycle"): the worker performs the
queued -> processing claim itself; dispatchers hand over QUEUED job ids.

Restart semantics: a job left PROCESSING in the repository by a dead worker is
recovered by recover_interrupted() -> failed with PROCESSING_FAILED retryable.
No torch objects are ever stored on Job.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from .errors import (
    FaceNotFoundError,
    LimitExceededError,
    MediaError,
    ProcessingError,
    TranscriptUnavailableError,
    WorkerError,
)
from .interfaces import (
    AdapterProgress,
    FaceTargeting,
    JobRepository,
    StageListener,
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


# Live-session chunk jobs carry this client_request_id prefix. Their transcript is
# produced once, after recording ends, on the whole recording (docs/04).
LIVE_CHUNK_PREFIX = "live:"


class _Cancelled(Exception):
    """Internal control flow between stages; final state is cancelled, not an error payload."""


class SingleWorker:
    def __init__(
        self,
        *,
        repo: JobRepository,
        targeting: FaceTargeting,
        layout: Optional[WorkerLayout] = None,
        transcriber: Optional[TranscriptProvider] = None,
        on_stage: Optional[StageListener] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        max_upload_mb: int = 50,
    ):
        self.repo = repo
        self.targeting = targeting
        self.layout = layout
        self.transcriber = transcriber
        self._on_stage = on_stage
        self._is_cancelled = is_cancelled
        self.max_upload_mb = max_upload_mb
        self._listener_failures = 0

    def process(self, job_id: str) -> Job:
        job = self.repo.get(job_id)
        if job.status is not JobStatus.QUEUED:
            return job.copied()
        self._claim(job)
        wav_ready = False
        try:
            self._check_cancel()
            self._validate(job)
            self._begin(job, JobStage.PREPARING)
            job_dir = self._ensure_job_dir(job)
            self._begin(job, JobStage.TRACKING)
            wav = self.targeting.extract(
                job, job_dir, on_progress=self._adapter_progress(job)
            )
            self._apply_audio_result(job, wav)
            self._verify_audio_artifact(job, job_dir)
            wav_ready = True
            self._persist(job)
            try:
                if (job.client_request_id or "").startswith(LIVE_CHUNK_PREFIX):
                    pass  # no per-chunk transcription; transcript_status stays pending
                else:
                    self._transcribe(job)
            except _Cancelled:
                raise
            except WorkerError as werr:
                self._fail_transcript(job, werr.payload(), getattr(werr, "reason", None))
            except Exception:
                self._fail_transcript(
                    job, ProcessingError("transcription failed", retryable=False).payload()
                )
        except _Cancelled:
            self._finish_cancelled(job)
            return job.copied()
        except WorkerError as werr:
            if not wav_ready:
                job.audio_status = AudioStatus.FAILED
            self._finish_failed(job, werr)
            return job.copied()
        except Exception:
            if not wav_ready:
                job.audio_status = AudioStatus.FAILED
            self._finish_failed(job, ProcessingError("processing failed", retryable=False))
            return job.copied()
        job.status = JobStatus.COMPLETED
        job.stage = JobStage.READY
        self._persist(job)
        self._emit(job)
        return job.copied()

    def transcribe_completed(self, job_id: str) -> Job:
        """Transcribe a job whose audio is already READY (final live transcript)."""
        job = self.repo.get(job_id)
        if job.audio_status is not AudioStatus.READY or not job.wav_path:
            raise ProcessingError("audio is not ready for transcription", retryable=False)
        try:
            self._transcribe(job)
        except WorkerError as werr:
            self._fail_transcript(job, werr.payload(), getattr(werr, "reason", None))
        except Exception:
            self._fail_transcript(
                job, ProcessingError("transcription failed", retryable=False).payload()
            )
        job.stage = JobStage.READY
        self._persist(job)
        self._emit(job)
        return job.copied()

    def request_cancel(self, job_id: str) -> bool:
        """Effectual for queued jobs; running jobs cancel only between stages."""
        job = self.repo.get(job_id)
        if job.status is JobStatus.QUEUED:
            job.status = JobStatus.CANCELLED
            self.repo.save(job)
            self._emit(job)
            return True
        return False

    def recover_interrupted(self) -> list[str]:
        """After a worker restart, no job may remain PROCESSING forever (contract)."""
        recovered = []
        for job in self.repo.all():
            if job.status is JobStatus.PROCESSING:
                if job.audio_status is not AudioStatus.READY:
                    job.audio_status = AudioStatus.FAILED
                if job.transcript_status is TranscriptStatus.PROCESSING:
                    job.transcript_status = TranscriptStatus.FAILED
                job.status = JobStatus.FAILED
                job.error = ErrorPayload(
                    "PROCESSING_FAILED", "worker restarted during processing", True
                )
                self.repo.save(job)
                self._emit(job)
                recovered.append(job.job_id)
        return recovered

    # -- stages -------------------------------------------------------------
    def _claim(self, job: Job) -> None:
        job.status = JobStatus.PROCESSING
        job.queue_position = 0
        self._reset_run_state(job)
        self._begin(job, JobStage.VALIDATING)

    @staticmethod
    def _reset_run_state(job: Job) -> None:
        """A requeued retry starts from a clean run state so a later COMPLETED
        job can never carry stale error, statuses or artifacts (docs/02: error on
        the contract example is null on success)."""
        job.audio_status = AudioStatus.PENDING
        job.transcript_status = TranscriptStatus.PENDING
        job.wav_path = None
        job.duration_ms = None
        job.source_offset_ms = 0
        job.transcript_segments = []
        job.audio_warnings = []
        job.error = None

    def _validate(self, job: Job) -> None:
        if not job.video_path:
            raise MediaError("missing media path for job")
        if not os.path.isabs(job.video_path):
            raise MediaError("media path is not absolute")
        if not os.path.isfile(job.video_path):
            raise MediaError("media file not found")
        if os.path.getsize(job.video_path) > self.max_upload_mb * 1024 * 1024:
            raise LimitExceededError("media exceeds configured upload size limit")
        if not job.face_id:
            raise FaceNotFoundError("no face selection recorded for job")

    def _ensure_job_dir(self, job: Job) -> str:
        job_dir = self.layout.job_dir(job) if self.layout is not None else job.job_dir
        if not job_dir:
            raise ProcessingError("no job directory could be resolved")
        os.makedirs(job_dir, exist_ok=True)
        job.job_dir = job_dir
        return job_dir

    def _adapter_progress(self, job: Job) -> AdapterProgress:
        def on_progress(stage: str, fraction: float) -> None:
            try:
                stage_enum = JobStage(stage)
            except ValueError:
                return
            try:
                self._begin(job, stage_enum, persist=False)
            except Exception:
                self._listener_failures += 1

        return on_progress

    def _verify_audio_artifact(self, job: Job, job_dir: str) -> None:
        """A job may never be recorded READY/COMPLETED without a real artifact
        (AGENTS.md: no fake inference success). wav_path must be an existing
        non-empty file inside the job directory the worker owns."""
        wav_path = job.wav_path
        if not wav_path or not os.path.isabs(wav_path):
            raise ProcessingError("audio output artifact missing", retryable=False)
        if not os.path.isfile(wav_path) or os.path.getsize(wav_path) <= 0:
            raise ProcessingError("audio output artifact missing", retryable=False)
        root = os.path.normcase(os.path.abspath(job_dir) + os.sep)
        if not os.path.normcase(os.path.abspath(wav_path)).startswith(root):
            raise ProcessingError("audio output artifact missing", retryable=False)

    def _apply_audio_result(self, job: Job, result) -> None:
        job.wav_path = result.wav_path
        job.duration_ms = result.duration_ms
        job.source_offset_ms = result.source_offset_ms
        job.audio_warnings.extend(result.warnings)
        job.audio_status = AudioStatus.READY

    def _transcribe(self, job: Job) -> None:
        self._check_cancel()
        if self.transcriber is None:
            raise TranscriptUnavailableError()
        job.transcript_status = TranscriptStatus.PROCESSING
        self._begin(job, JobStage.TRANSCRIBING)
        raw = self.transcriber.transcribe(job.wav_path or "")
        job.transcript_segments = [self._to_segment(i, seg) for i, seg in enumerate(raw)]
        job.transcript_status = TranscriptStatus.READY

    @staticmethod
    def _to_segment(index: int, seg) -> TranscriptSegment:
        if isinstance(seg, dict):
            start = int(seg["start_ms"])
            end = int(seg["end_ms"])
            if start < 0 or end < start:
                raise ProcessingError("invalid transcript segment timing", retryable=False)
            return TranscriptSegment(
                id=int(seg.get("id", index)),
                start_ms=start,
                end_ms=end,
                text=str(seg.get("text", "")),
            )
        if seg.start_ms < 0 or seg.end_ms < seg.start_ms:
            raise ProcessingError("invalid transcript segment timing", retryable=False)
        return seg

    def _check_cancel(self) -> None:
        if self._is_cancelled is not None and self._is_cancelled():
            raise _Cancelled()

    def _begin(self, job: Job, stage: JobStage, *, persist: bool = True) -> None:
        job.stage = stage
        if persist:
            self._persist(job)
        self._emit(job)

    def _fail_transcript(
        self, job: Job, payload: tuple[str, str, bool], reason: Optional[str] = None
    ) -> None:
        code, _message, _retryable = payload
        job.transcript_status = TranscriptStatus.FAILED
        job.transcript_segments = []
        job.audio_warnings.append(f"transcript failed: {reason or code}")
        self._persist(job)
        self._emit(job)

    def _finish_failed(self, job: Job, werr: WorkerError) -> None:
        code, message, retryable = werr.payload()
        job.status = JobStatus.FAILED
        job.error = ErrorPayload(code, message, retryable)
        self._persist(job)
        self._emit(job)

    def _finish_cancelled(self, job: Job) -> None:
        job.status = JobStatus.CANCELLED
        self._persist(job)
        self._emit(job)

    def _persist(self, job: Job) -> None:
        self.repo.save(job)

    def _emit(self, job: Job) -> None:
        if self._on_stage is not None:
            try:
                self._on_stage(job.copied())
            except Exception:
                self._listener_failures += 1
