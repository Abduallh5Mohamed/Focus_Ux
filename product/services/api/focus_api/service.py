"""Business operations behind the HTTP routes.

The service is deliberately synchronous: FastAPI runs these functions in its
thread pool, and the SQLite repository serializes writes. Async GPU work is only
ever *enqueued* on the dispatcher here.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import BinaryIO, Optional

from services.worker.models import AudioStatus, Job, JobStage, JobStatus, TranscriptStatus

from .config import Settings
from .db import FaceRecord, JobNotFound, SqliteRepository, VideoRecord
from .dispatcher import Dispatcher
from .errors import (
    ApiError,
    face_not_found,
    invalid_media,
    limit_exceeded,
    no_audio,
    not_found,
    not_ready,
    unauthorized,
)
from .identity import bbox_to_wire, frame_size_to_wire
from .media_probe import ProbeError, probe_video
from .storage import VIDEO_EXTENSIONS, Storage

logger = logging.getLogger("focus_api.service")

_CHUNK = 1024 * 1024


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApiService:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        repo: SqliteRepository,
        dispatcher: Dispatcher,
    ):
        self.settings = settings
        self.storage = storage
        self.repo = repo
        self.dispatcher = dispatcher

    # -- sessions ------------------------------------------------------------
    def new_session(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        session_id = uuid.uuid4().hex
        self.repo.create_session(_hash_token(token), session_id)
        return token, session_id

    def authenticate(self, token: Optional[str]) -> str:
        if not token:
            raise unauthorized()
        session_id = self.repo.get_session_id(_hash_token(token))
        if not session_id:
            raise unauthorized("session token is not recognised")
        return session_id

    # -- uploads -------------------------------------------------------------
    def upload(
        self,
        *,
        stream: BinaryIO,
        content_type: Optional[str],
        token: Optional[str],
    ) -> tuple[dict, Optional[str]]:
        """Store a bounded upload and enqueue face detection.

        Returns ``(response_body, new_session_token_or_none)``.
        """
        new_token: Optional[str] = None
        if token:
            session_id = self.authenticate(token)
        else:
            new_token, session_id = self.new_session()

        claimed = (content_type or "").split(";")[0].strip().lower()
        if claimed and claimed not in ("application/octet-stream",) and not claimed.startswith("video/"):
            raise invalid_media("the uploaded file is not a video")

        video_id = uuid.uuid4().hex
        temp_path = self.storage.new_temp_path()
        total = 0
        try:
            with open(temp_path, "wb") as out:
                while True:
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise limit_exceeded(
                            f"upload exceeds the {self.settings.max_upload_bytes // (1024 * 1024)} MB limit"
                        )
                    out.write(chunk)
            if total <= 0:
                raise invalid_media("the uploaded file is empty")
            try:
                probe = probe_video(temp_path)
            except ProbeError as exc:
                if exc.code == "LIMIT_EXCEEDED":
                    raise limit_exceeded(exc.message) from exc
                raise invalid_media(exc.message) from exc
            if probe.duration_ms > self.settings.max_video_ms:
                raise limit_exceeded(
                    f"video exceeds the {self.settings.max_video_ms / 1000:g}s limit"
                )
            extension = VIDEO_EXTENSIONS.get(probe.mime_type)
            if extension is None:
                raise invalid_media("unsupported video container")
            final_path = self.storage.media_path(video_id, extension)
            os.replace(temp_path, final_path)
            temp_path = None  # type: ignore[assignment]
        finally:
            if temp_path is not None and Path(temp_path).exists():
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass

        now = time.time()
        video = VideoRecord(
            video_id=video_id,
            session_id=session_id,
            original_path=str(final_path),
            # For this milestone the stored upload is the canonical media used
            # by both detection and extraction (identity decision #5).
            canonical_path=str(final_path),
            mime_type=probe.mime_type,
            size_bytes=total,
            duration_ms=probe.duration_ms,
            width=probe.width,
            height=probe.height,
            fps=probe.fps,
            faces_status="pending",
            faces_error_code=None,
            faces_error_message=None,
            faces_error_retryable=False,
            created_at=now,
            deleted_at=None,
        )
        self.repo.create_video(video)
        self.dispatcher.enqueue_faces(video_id)

        metadata = {
            "duration_ms": probe.duration_ms,
            "width": probe.width,
            "height": probe.height,
            "mime_type": probe.mime_type,
            "size_bytes": total,
        }
        if probe.fps is not None:
            metadata["fps"] = probe.fps
        body = {
            "video_id": video_id,
            "metadata": metadata,
            "faces_status": "pending",
        }
        if new_token:
            body["session_token"] = new_token
        return body, new_token

    # -- ownership helpers ---------------------------------------------------
    def _owned_video(self, video_id: str, session_id: str, *, allow_deleted: bool = False) -> VideoRecord:
        video = self.repo.get_video(video_id)
        if video is None or video.session_id != session_id:
            raise not_found("video not found")
        if video.deleted and not allow_deleted:
            raise not_found("video not found")
        return video

    def _owned_job(self, job_id: str, session_id: str) -> tuple[Job, VideoRecord]:
        job = self.repo.find_job(job_id)
        if job is None:
            raise not_found("job not found")
        video = self.repo.get_video(job.video_id)
        if video is None or video.session_id != session_id or video.deleted:
            raise not_found("job not found")
        return job, video

    # -- faces ---------------------------------------------------------------
    def faces_response(self, video_id: str, session_id: str) -> dict:
        video = self._owned_video(video_id, session_id)
        faces = self.repo.get_faces(video_id)
        items = [self._face_wire(video_id, face) for face in faces]
        error = None
        if video.faces_status == "failed" and video.faces_error_code:
            error = {
                "code": video.faces_error_code,
                "message": video.faces_error_message or "face detection failed",
                "retryable": video.faces_error_retryable,
            }
        return {"status": video.faces_status, "faces": items, "error": error}

    def _face_wire(self, video_id: str, face: FaceRecord) -> dict:
        prefix = self.settings.thumbnail_url_prefix
        return {
            "face_id": face.face_id,
            "thumbnail_url": f"{prefix}/videos/{video_id}/faces/{face.face_id}/thumbnail",
            "bbox": bbox_to_wire(face.bbox),
            "timestamp_ms": face.timestamp_ms,
            "frame_size": frame_size_to_wire(face.frame_size),
        }

    # -- jobs ----------------------------------------------------------------
    def create_job(
        self, *, video_id: str, face_id: str, client_request_id: str, session_id: str
    ) -> tuple[str, bool]:
        video = self._owned_video(video_id, session_id)
        existing = self.repo.find_job_id(video_id, face_id, client_request_id)
        if existing is not None:
            return existing, False
        if self.repo.get_face(video_id, face_id) is None:
            raise face_not_found("selected face candidate is not available")

        job_id = uuid.uuid4().hex
        job = Job(
            job_id=job_id,
            video_id=video_id,
            face_id=face_id,
            client_request_id=client_request_id,
            video_path=video.canonical_path or video.original_path,
            job_dir=str(self.storage.job_dir(job_id)),
            status=JobStatus.QUEUED,
            stage=JobStage.VALIDATING,
            audio_status=AudioStatus.PENDING,
            transcript_status=TranscriptStatus.PENDING,
            queue_position=len(self.repo.queued_jobs()),
        )
        inserted = self.repo.create_job(job)
        if not inserted:
            # Lost an insertion race: return the winner for idempotency.
            winner = self.repo.find_job_id(video_id, face_id, client_request_id)
            if winner is not None:
                return winner, False
            raise ApiError(
                "PROCESSING_FAILED",
                "job could not be created",
                status_code=500,
                retryable=True,
            )
        self.dispatcher.enqueue_job(job_id)
        return job_id, True

    def job_state(self, job_id: str, session_id: str) -> dict:
        job, _video = self._owned_job(job_id, session_id)
        queue_position = (
            self.repo.queued_position(job.job_id) if job.status is JobStatus.QUEUED else 0
        )
        result = None
        if job.status is JobStatus.COMPLETED:
            result = {
                "duration_ms": job.duration_ms,
                "source_offset_ms": job.source_offset_ms,
            }
            if job.audio_warnings:
                result["warnings"] = list(job.audio_warnings)
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "stage": job.stage.value,
            "selected_face_id": job.face_id,
            "audio_status": job.audio_status.value,
            "transcript_status": job.transcript_status.value,
            "queue_position": queue_position,
            "error": self._error_wire(job),
            "result": result,
        }

    @staticmethod
    def _error_wire(job: Job) -> Optional[dict]:
        if job.error is None:
            return None
        return {
            "code": job.error.code,
            "message": job.error.message,
            "retryable": bool(job.error.retryable),
        }

    def transcript_response(self, job_id: str, session_id: str) -> dict:
        job, _video = self._owned_job(job_id, session_id)
        status = job.transcript_status.value
        segments: list[dict] = []
        error = None
        if job.transcript_status is TranscriptStatus.READY:
            segments = [
                {
                    # Wire type is string; worker stores an int segment id.
                    "id": str(segment.id),
                    "start_ms": int(segment.start_ms),
                    "end_ms": int(segment.end_ms),
                    "text": segment.text,
                }
                for segment in job.transcript_segments
            ]
        elif job.transcript_status is TranscriptStatus.FAILED:
            # Missing ASR is an honest failure; audio stays usable and no text
            # is fabricated (decision #7).
            error = {
                "code": "PROCESSING_FAILED",
                "message": "transcript is unavailable for this job",
                "retryable": True,
            }
        return {"status": status, "segments": segments, "error": error}

    # -- protected media -----------------------------------------------------
    def audio_file(self, job_id: str, session_id: str) -> tuple[Path, str]:
        job, _video = self._owned_job(job_id, session_id)
        if job.audio_status is AudioStatus.FAILED:
            raise no_audio("audio separation failed for this job")
        if job.audio_status is not AudioStatus.READY:
            raise not_ready("audio is not ready yet")
        path = Path(job.wav_path or "")
        if not job.wav_path or not path.is_file() or not self.storage.is_managed(path):
            raise no_audio("audio artifact is unavailable")
        return path, _sniff_wav_mime(path)

    def original_file(self, video_id: str, session_id: str) -> tuple[Path, str]:
        video = self._owned_video(video_id, session_id)
        raw = video.canonical_path or video.original_path
        if not raw:
            raise not_found("video media is unavailable")
        path = Path(raw)
        if not path.is_file() or not self.storage.is_managed(path):
            raise not_found("video media is unavailable")
        return path, video.mime_type

    def thumbnail_file(self, video_id: str, face_id: str, session_id: str) -> tuple[Path, str]:
        self._owned_video(video_id, session_id)
        face = self.repo.get_face(video_id, face_id)
        if face is None or not face.thumbnail_path:
            raise not_found("thumbnail not found")
        path = Path(face.thumbnail_path)
        if not path.is_file() or not self.storage.is_managed(path):
            raise not_found("thumbnail not found")
        return path, face.thumbnail_mime or "image/jpeg"

    # -- deletion ------------------------------------------------------------
    def delete_video(self, video_id: str, session_id: str) -> dict:
        video = self._owned_video(video_id, session_id, allow_deleted=True)
        if video.deleted:
            # A previous attempt may have failed after revoking access. The
            # queue deduplicates in-flight requests; a later DELETE retries.
            self.dispatcher.enqueue_cleanup(video_id)
            return {"deletion_pending": True}
        self.repo.mark_video_deleted(video_id)
        queued = self.repo.cancel_queued_for_video(video_id)
        if queued:
            logger.info("cancelled %d queued job(s) for deleted video %s", len(queued), video_id)
        self.dispatcher.enqueue_cleanup(video_id)
        return {"deletion_pending": True}


def _sniff_wav_mime(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            header = handle.read(12)
    except OSError:
        return "audio/wav"
    if header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    return "application/octet-stream"
