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

from .config import LIP_ENGINE_MAX_VIDEO_MS, VOICE_FILE_MAX_BYTES, VOICE_FILE_MAX_MS, Settings
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
from .mix import MixError, MixSettings
from .mix_service import MixService
from .media_probe import ProbeError, probe_video
from .storage import VIDEO_EXTENSIONS, Storage

logger = logging.getLogger("focus_api.service")

_CHUNK = 1024 * 1024
MIN_ENROLL_MS = 4000   # matches the enrollment rule: at least 4 s of one voice
MAX_RANGE_MS = 60_000
_TRANSCRIPT_WARNING = "transcript failed:"
_TRANSCRIPT_REASONS = {
    "not_configured": "transcription is not configured on this server",
    "model_unavailable": "the transcription model is not available",
    "out_of_memory": "transcription ran out of GPU memory",
    "timeout": "transcription timed out",
    "worker_offline": "the inference computer was offline during transcription",
    "failed": "transcript is unavailable for this job",
}


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
        self.mixer = MixService(settings.ffmpeg_path)

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
        total = 0
        with self.storage.own_temp_upload() as temp_path:
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
                        f"video exceeds the {self.settings.max_video_ms / 1000:g}s limit "
                        f"({self.settings.limit_source})"
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
                        logger.warning(
                            "Failed-upload cleanup failed for %s; retained for stale-upload cleanup",
                            temp_path,
                            exc_info=True,
                        )

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
        if self.settings.audio_only:
            self.repo.set_analysis(video_id, "pending")  # analysed beside face detection
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
        self, *, video_id: str, face_id: Optional[str], client_request_id: str, session_id: str,
        enrollment_id: Optional[str] = None,
    ) -> tuple[str, bool]:
        video = self._owned_video(video_id, session_id)
        if self.settings.audio_only:
            if not enrollment_id:
                raise ApiError("ENROLLMENT_REQUIRED", "confirm a voice before starting the job",
                               status_code=409)
            enrollment = self.repo.get_enrollment(enrollment_id)
            if enrollment is None or enrollment["video_id"] != video_id:
                raise ApiError("ENROLLMENT_REQUIRED", "voice enrollment not found", status_code=409)
            if enrollment["status"] != "ready":
                raise ApiError("ENROLLMENT_REQUIRED", "voice enrollment is not ready", status_code=409)
            # The face only identifies the user's choice; it never reaches extraction.
            face_id = enrollment["face_id"]
        else:
            enrollment_id = None
            if not face_id:
                raise ApiError("INVALID_REQUEST", "face_id is required", status_code=422)
            if video.duration_ms > LIP_ENGINE_MAX_VIDEO_MS:
                raise limit_exceeded(
                    f"the {self.settings.isolation_engine} engine supports clips up to "
                    f"{LIP_ENGINE_MAX_VIDEO_MS // 1000}s")
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
            enrollment_id=enrollment_id,
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
            engine = next((w[len("engine: "):] for w in job.audio_warnings
                           if w.startswith("engine: ")), None)
            if engine:
                result["engine"] = engine
            if job.audio_warnings:
                result["warnings"] = [w for w in job.audio_warnings
                                      if not w.startswith("engine: ")]
            if job.enrollment_id:
                result["follow_periods"] = [dict(p) for p in job.follow_periods]
        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "stage": job.stage.value,
            "selected_face_id": job.face_id,
            "audio_status": job.audio_status.value,
            "transcript_status": job.transcript_status.value,
            "queue_position": queue_position,
            # The audio-only flow runs no speech recognition (the feature stays for other engines).
            "transcript_enabled": not job.enrollment_id,
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
            reason = "failed"
            for warning in reversed(job.audio_warnings):
                if warning.startswith(_TRANSCRIPT_WARNING):
                    found = warning[len(_TRANSCRIPT_WARNING):].strip()
                    reason = found if found in _TRANSCRIPT_REASONS else "failed"
                    break
            error = {
                "code": "PROCESSING_FAILED",
                "message": _TRANSCRIPT_REASONS[reason],
                "retryable": reason != "model_unavailable",
                "reason": reason,
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

    # -- voice mix -----------------------------------------------------------
    def _mix_inputs(self, job_id: str, session_id: str):
        job, video = self._owned_job(job_id, session_id)
        wav, _mime = self.audio_file(job_id, session_id)
        raw = video.canonical_path or video.original_path
        path = Path(raw or "")
        if not raw or not path.is_file() or not self.storage.is_managed(path):
            raise not_found("video media is unavailable")
        return job, video, path, wav

    def _alignment(self, job_id: str, session_id: str):
        job, video, path, wav = self._mix_inputs(job_id, session_id)
        try:
            return job, video, path, wav, self.mixer.analysis(
                job_id=job_id, video_path=path, wav_path=wav,
                offset_ms=float(job.source_offset_ms or 0), duration_ms=video.duration_ms,
            )
        except MixError as exc:
            raise _mix_api_error(exc) from exc

    def mix_info(self, job_id: str, session_id: str) -> dict:
        _job, _video, _path, _wav, a = self._alignment(job_id, session_id)
        return {
            "sample_rate": 48_000,
            "others_available": a.reliable,
            "others_unavailable_reason": None if a.reliable else a.reason,
            "alignment_ms": round(a.lag_ms, 2),
            "level_gain": round(a.gain, 4),
            "correlation": round(a.correlation, 4),
            "noise_filters": {"light": {"highpass_hz": 100}, "strong": {"highpass_hz": 150, "lowpass_hz": 6000}},
        }

    def mix_track(self, job_id: str, track: str, session_id: str) -> bytes:
        from . import mix
        _job, _video, _path, _wav, a = self._alignment(job_id, session_id)
        if track == "voice":
            return mix.to_float_wav(a.voice)
        if track == "others":
            if not a.reliable:
                raise ApiError("MIX_UNRELIABLE", "the other-voices track is unreliable for this job",
                               status_code=409)
            return mix.to_float_wav(a.others)
        raise not_found("unknown mix track")

    def start_export(self, job_id: str, session_id: str, payload: dict) -> dict:
        job, video, path, wav = self._mix_inputs(job_id, session_id)
        try:
            settings = MixSettings(
                voice_level=float(payload.get("voice_level", 1.0)),
                others_level=float(payload.get("others_level", 0.0)),
                noise_reduction=str(payload.get("noise_reduction", "off")),
            )
            record = self.mixer.start_export(
                job_id=job_id, video_path=path, wav_path=wav,
                offset_ms=float(job.source_offset_ms or 0), duration_ms=video.duration_ms,
                settings=settings, export_dir=self.storage.job_dir(job_id) / "exports",
            )
        except MixError as exc:
            raise _mix_api_error(exc) from exc
        return {"export_id": record.export_id, "status": record.status}

    def _export(self, job_id: str, export_id: str, session_id: str):
        self._owned_job(job_id, session_id)
        record = self.mixer.get_export(job_id, export_id)
        if record is None:
            raise not_found("export not found")
        return record

    def export_state(self, job_id: str, export_id: str, session_id: str) -> dict:
        record = self._export(job_id, export_id, session_id)
        body: dict = {"export_id": record.export_id, "status": record.status}
        if record.status == "failed":
            body["error"] = {"code": record.error_code, "message": record.error_message,
                             "retryable": record.error_code != "EXPORT_UNSUPPORTED"}
        return body

    def export_file(self, job_id: str, export_id: str, session_id: str) -> tuple[Path, str]:
        record = self._export(job_id, export_id, session_id)
        if record.status != "ready" or record.path is None or not self.storage.is_managed(record.path):
            raise not_ready("export is not ready yet")
        return record.path, "video/mp4"

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

    # -- audio analysis, voice suggestion, enrollment ------------------------
    def config_response(self) -> dict:
        lip = not self.settings.audio_only
        return {
            "engine": self.settings.isolation_engine,
            "max_video_ms": min(self.settings.max_video_ms, LIP_ENGINE_MAX_VIDEO_MS) if lip
            else self.settings.max_video_ms,
            "max_upload_bytes": self.settings.max_upload_bytes,
            "voice_file_max_ms": VOICE_FILE_MAX_MS,
            "min_enrollment_ms": MIN_ENROLL_MS,
        }

    def _analysis_result(self, video_id: str) -> dict:
        record = self.repo.get_analysis(video_id)
        if record is None or record["status"] != "ready" or not record["result"]:
            raise not_ready("audio analysis is not ready yet")
        return record["result"]

    def analysis_response(self, video_id: str, session_id: str) -> dict:
        self._owned_video(video_id, session_id)
        record = self.repo.get_analysis(video_id)
        if record is None:
            return {"status": "failed", "voices": [], "warnings": [], "duration_ms": 0,
                    "error": {"code": "MODEL_UNAVAILABLE", "retryable": False,
                              "message": "audio analysis is not available for this video"}}
        body = {"status": record["status"], "voices": [], "warnings": [], "duration_ms": 0, "error": None}
        if record["status"] == "failed":
            body["error"] = {"code": record["error_code"] or "PROCESSING_FAILED",
                             "message": record["error_message"] or "audio analysis failed",
                             "retryable": record["retryable"]}
        result = record["result"]
        if record["status"] == "ready" and result:
            prefix = self.settings.thumbnail_url_prefix
            body["duration_ms"] = result["duration_ms"]
            body["warnings"] = result["warnings"]
            for index, sp in enumerate(result["speakers"]):
                sample = sp["sample"]
                body["voices"].append({
                    "voice_id": f"voice-{index}",
                    "speech_s": sp["speech_s"], "clean_s": sp["clean_s"],
                    "overlap_fraction": sp["overlap_fraction"],
                    "usable": sp["usable"], "refusal": sp["refusal"], "warnings": sp["warnings"],
                    "sample": None if sample is None else {
                        "start_ms": round(sample["start"] * 1000), "end_ms": round(sample["end"] * 1000)},
                    "sample_url": f"{prefix}/videos/{video_id}/analysis/voices/voice-{index}/sample"
                    if sp.get("clip") else None,
                })
        return body

    def retry_analysis(self, video_id: str, session_id: str) -> dict:
        self._owned_video(video_id, session_id)
        record = self.repo.get_analysis(video_id)
        if record is not None and record["status"] == "failed":
            self.repo.set_analysis(video_id, "pending")
            self.dispatcher.enqueue_analysis(video_id)
        return {"status": (self.repo.get_analysis(video_id) or {"status": "failed"})["status"]}

    @staticmethod
    def _voice_index(voice_id: str, count: int) -> int:
        if not voice_id.startswith("voice-") or not voice_id[6:].isdigit():
            raise not_found("voice not found")
        index = int(voice_id[6:])
        if index >= count:
            raise not_found("voice not found")
        return index

    def voice_sample_file(self, video_id: str, voice_id: str, session_id: str) -> tuple[Path, str]:
        self._owned_video(video_id, session_id)
        result = self._analysis_result(video_id)
        index = self._voice_index(voice_id, len(result["speakers"]))
        from .inference import voice_sample_path
        path = voice_sample_path(self.settings, video_id, index)
        if not result["speakers"][index].get("clip") or not path.is_file():
            raise not_found("voice sample not found")
        return path, "audio/wav"

    def request_suggestion(self, video_id: str, face_id: str, session_id: str) -> dict:
        self._owned_video(video_id, session_id)
        if self.repo.get_face(video_id, face_id) is None:
            raise face_not_found("selected face candidate is not available")
        record = self.repo.get_suggestion(video_id, face_id)
        import os
        outdated = (record is not None and record['status'] == 'ready' and
                    os.environ.get('FOCUS_TALKNET_PYTHON') and not isinstance(record['visible'], dict))
        if record is None or record["status"] == "failed" or outdated:
            self.repo.set_suggestion(video_id, face_id, "pending")
            self.dispatcher.enqueue_suggestion(video_id, face_id)
            record = {"status": "pending"}
        return {"status": record["status"]}

    def suggestion_response(self, video_id: str, face_id: str, session_id: str) -> dict:
        from .voice_suggest import SUGGESTION_NOTE, rank_voices
        self._owned_video(video_id, session_id)
        if self.repo.get_face(video_id, face_id) is None:
            raise face_not_found("selected face candidate is not available")
        record = self.repo.get_suggestion(video_id, face_id)
        analysis = self.repo.get_analysis(video_id)
        body = {"status": "pending", "candidates": [], "evidence": None, "note": SUGGESTION_NOTE,
                "error": None}
        if analysis is None or analysis["status"] == "failed":
            body["status"] = "failed"
            body["error"] = {"code": "PROCESSING_FAILED", "retryable": bool(analysis and analysis["retryable"]),
                             "message": "the voices could not be analysed for this video"}
            return body
        if analysis["status"] != "ready":
            return body
        if record is None:
            return body
        if record["status"] == "pending":
            return body
        visible = record["visible"] if record["status"] == "ready" else None
        ranked = rank_voices(analysis["result"], visible)
        body.update(status="ready", evidence=ranked["evidence"], note=ranked["note"])
        if record["status"] == "failed":
            body["notice"] = "تعذّر قياس ظهور الوجه؛ الترتيب حسب مدة الكلام فقط."
        body["candidates"] = [
            {"voice_id": f"voice-{r['index']}", "rank": r["rank"], "suggested": r["suggested"],
             "talk_s": r["talk_s"], "visible_talk_s": r["visible_talk_s"]}
            for r in ranked["candidates"]
        ]
        return body

    def _enrollment_wire(self, item: dict) -> dict:
        error = None
        if item["status"] == "failed":
            error = {"code": item["error_code"] or "PROCESSING_FAILED",
                     "message": item["error_message"] or "voice enrollment failed",
                     "retryable": item["retryable"]}
        return {"enrollment_id": item["enrollment_id"], "status": item["status"],
                "face_id": item["face_id"], "source": item["source_kind"],
                "warnings": item["warnings"], "clean_s": item["clean_s"], "error": error}

    def create_enrollment(self, video_id: str, session_id: str, payload: dict) -> dict:
        """Confirm a detected voice, or enroll a manual time range."""
        video = self._owned_video(video_id, session_id)
        face_id = payload.get("face_id")
        if not isinstance(face_id, str) or self.repo.get_face(video_id, face_id) is None:
            raise face_not_found("selected face candidate is not available")
        source = payload.get("source")
        enrollment_id = uuid.uuid4().hex
        if source == "voice":
            result = self._analysis_result(video_id)
            index = self._voice_index(str(payload.get("voice_id", "")), len(result["speakers"]))
            speaker = result["speakers"][index]
            if not speaker["usable"] or not speaker["voiceprint"]:
                raise ApiError("ENROLLMENT_REFUSED", speaker["refusal"] or "this voice sample is too short",
                               status_code=422)
            vp = dict(speaker["voiceprint"], warnings=list(speaker["warnings"]))
            self.repo.create_enrollment(
                enrollment_id, video_id, face_id, "voice", {"voice_id": f"voice-{index}"}, "ready",
                voiceprint=vp, warnings=speaker["warnings"], clean_s=speaker["clean_s"])
        elif source == "range":
            start, end = payload.get("start_ms"), payload.get("end_ms")
            if type(start) is not int or type(end) is not int or start < 0 or end <= start \
                    or end > video.duration_ms + 80:
                raise ApiError("INVALID_REQUEST", "the time range is not valid", status_code=422)
            if end - start < MIN_ENROLL_MS:
                raise ApiError("ENROLLMENT_REFUSED",
                               f"The range is too short; choose at least {MIN_ENROLL_MS // 1000} seconds "
                               "of one person speaking.", status_code=422)
            if end - start > MAX_RANGE_MS:
                raise ApiError("INVALID_REQUEST", f"the range is longer than {MAX_RANGE_MS // 1000} seconds",
                               status_code=422)
            self._analysis_result(video_id)
            self.repo.create_enrollment(enrollment_id, video_id, face_id, "range",
                                        {"start_ms": start, "end_ms": min(end, video.duration_ms)})
            self.dispatcher.enqueue_enrollment(enrollment_id)
        else:
            raise ApiError("INVALID_REQUEST", "source must be voice, range or a voice file", status_code=422)
        return self._enrollment_wire(self.repo.get_enrollment(enrollment_id))

    def create_voice_file_enrollment(self, video_id: str, session_id: str, face_id: str,
                                     stream: BinaryIO) -> dict:
        """A separate recording of the person; kept only until enrollment finishes."""
        import wave
        from .inference import extract_audio_wav
        from .interfaces import ProviderError
        self._owned_video(video_id, session_id)
        if self.repo.get_face(video_id, face_id) is None:
            raise face_not_found("selected face candidate is not available")
        enrollment_id = uuid.uuid4().hex
        target = self.settings.media_dir / f"{video_id}.voice-{enrollment_id}.wav"
        total = 0
        with self.storage.own_temp_upload() as raw_path:
            try:
                with open(raw_path, "wb") as out:
                    while chunk := stream.read(_CHUNK):
                        total += len(chunk)
                        if total > VOICE_FILE_MAX_BYTES:
                            raise limit_exceeded(
                                f"the voice recording exceeds {VOICE_FILE_MAX_BYTES // (1024 * 1024)} MB")
                        out.write(chunk)
                if total <= 0:
                    raise invalid_media("the voice recording is empty")
                try:
                    extract_audio_wav(self.settings.ffmpeg_path, raw_path, str(target))
                except ProviderError as exc:
                    raise invalid_media("the voice recording could not be read as audio") from exc
                with wave.open(str(target), "rb") as audio:
                    duration_ms = round(audio.getnframes() * 1000 / audio.getframerate())
                if duration_ms < MIN_ENROLL_MS:
                    raise ApiError("ENROLLMENT_REFUSED",
                                   f"The recording is too short; use at least {MIN_ENROLL_MS // 1000} "
                                   "seconds of one person speaking.", status_code=422)
                if duration_ms > VOICE_FILE_MAX_MS:
                    raise limit_exceeded(f"the voice recording is longer than {VOICE_FILE_MAX_MS // 1000}s")
                if not self.repo.create_enrollment(enrollment_id, video_id, face_id, "file",
                                                   {"duration_ms": duration_ms}):
                    raise not_found("video not found")
            except Exception:
                target.unlink(missing_ok=True)
                raise
        self.dispatcher.enqueue_enrollment(enrollment_id)
        return self._enrollment_wire(self.repo.get_enrollment(enrollment_id))

    def enrollment_response(self, video_id: str, enrollment_id: str, session_id: str) -> dict:
        self._owned_video(video_id, session_id)
        item = self.repo.get_enrollment(enrollment_id)
        if item is None or item["video_id"] != video_id:
            raise not_found("enrollment not found")
        return self._enrollment_wire(item)

    # -- deletion ------------------------------------------------------------
    def delete_video(self, video_id: str, session_id: str) -> dict:
        video = self._owned_video(video_id, session_id, allow_deleted=True)
        if video.deleted:
            # A previous attempt may have failed after revoking access. The
            # queue deduplicates in-flight requests; a later DELETE retries.
            self.dispatcher.enqueue_cleanup(video_id)
            return {"deletion_pending": True}
        self.repo.mark_video_deleted(video_id)
        # Stop renders first so directory removal never races an open file.
        self.mixer.cancel_jobs([j.job_id for j in self.repo.jobs_for_video(video_id)])
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


def _mix_api_error(exc: MixError) -> ApiError:
    status = {"INVALID_REQUEST": 400, "NO_AUDIO": 409, "MIX_UNRELIABLE": 409,
              "EXPORT_UNSUPPORTED": 422}.get(exc.code, 500)
    return ApiError(exc.code, exc.message, status_code=status,
                    retryable=exc.code in ("PROCESSING_FAILED",))
