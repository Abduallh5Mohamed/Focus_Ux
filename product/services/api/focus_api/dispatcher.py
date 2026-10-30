"""Single OS-locked dispatcher for face candidates, jobs and cleanup.

Serialization model (ROUND2_INTEGRATION_DECISIONS #4):
  * exactly one process owns the lock and one thread executes work;
  * API requests only enqueue ids; they never run a detector or extractor;
  * for jobs, the dispatcher calls ``SingleWorker.process(job_id)``; the WORKER
    performs the QUEUED -> PROCESSING claim through the repository CAS;
  * a failed claim (:class:`ClaimConflict`) is surfaced/logged and skipped, not
    retried into duplicate execution.

Crash recovery:
  * startup acquires the OS lock first. If acquisition fails, a live dispatcher
    exists, so this process does NOT call ``recover_interrupted()`` and does not
    touch PROCESSING jobs;
  * the lock holder then asks the worker to recover interrupted PROCESSING jobs
    (failed + PROCESSING_FAILED retryable per services/worker/worker.py) and
    re-enqueues pending faces / queued jobs in creation order;
  * filesystem cleanup failures allow degraded startup under the same lock.
    Failed tombstones stay private and retain paths for retry on the next
    startup or repeated deletion request; unrelated cleanup and work continue.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from services.worker.interfaces import TargetRunResult
from services.worker.models import Job

from .config import Settings
from .db import ClaimConflict, ClaimConflict as _ClaimConflict  # noqa: F401
from .db import FaceRecord, SqliteRepository, VideoRecord
from .identity import make_face_id, ordered_unique
from .interfaces import DetectedFace, ExtractionRunner, FaceCandidateProvider
from .lock import DispatcherLock
from .storage import Storage

logger = logging.getLogger("focus_api.dispatcher")

_FACES = "faces"
_JOB = "job"
_CLEANUP = "cleanup"
_LIVE = "live"
_ANALYSIS = "analysis"
_SUGGEST = "suggest"
_ENROLL = "enroll"


class Dispatcher:
    def __init__(
        self,
        *,
        settings: Settings,
        storage: Storage,
        repo: SqliteRepository,
        worker,
        candidate_provider: FaceCandidateProvider,
        extraction_runner: ExtractionRunner,
        lock: DispatcherLock | None = None,
    ):
        self.settings = settings
        self.storage = storage
        self.repo = repo
        self.worker = worker
        self.candidate_provider = candidate_provider
        self.extraction_runner = extraction_runner
        self.lock = lock or DispatcherLock(settings.lock_file)

        self._queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._seen: set[tuple[str, str]] = set()
        self._seen_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = threading.Event()
        self.lock_acquired = False
        # Set by the live-session manager; runs on the dispatcher thread so live
        # chunks share the single-worker serialization with every other task.
        self.live_handler = None
        self.live_maintenance = None
        self.recovered: list[str] = []

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return True
        if not self.lock.acquire():
            logger.warning(
                "dispatcher lock %s is held by another process; staying read-only",
                self.settings.lock_file,
            )
            return False
        self.lock_acquired = True
        try:
            # Only the lock holder may recover. This must happen before the
            # thread starts consuming the queue.
            self.recovered = list(self.worker.recover_interrupted())
            self._cleanup_deleted_videos()
            for video_id, _created in self.repo.pending_face_videos():
                self.enqueue_faces(video_id)
            for video_id in self.repo.pending_analysis_videos():
                self.enqueue_analysis(video_id)
            for video_id, face_id in self.repo.pending_suggestions():
                self.enqueue_suggestion(video_id, face_id)
            for enrollment_id in self.repo.pending_enrollments():
                self.enqueue_enrollment(enrollment_id)
            for job_id, _created in self.repo.queued_jobs():
                self.enqueue_job(job_id)
            self._thread = threading.Thread(
                target=self._run, name="focus-api-dispatcher", daemon=True
            )
            self._thread.start()
            return True
        except Exception:
            self.lock.release()
            self.lock_acquired = False
            raise

    def stop(self, timeout: float = 5.0) -> None:
        """Stop before releasing ownership, or raise while retaining it.

        A timeout does not cancel in-flight work. Callers must keep the
        repository open and retry stop() after the worker finishes.
        """
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
            if thread.is_alive():
                raise TimeoutError(
                    "dispatcher shutdown timed out; worker is still running, "
                    "ownership retained"
                )
        self._thread = None
        if self.lock_acquired:
            self.lock.release()
            self.lock_acquired = False

    # -- enqueue -------------------------------------------------------------
    def enqueue_faces(self, video_id: str) -> None:
        self._put(_FACES, video_id)

    def enqueue_job(self, job_id: str) -> None:
        self._put(_JOB, job_id)

    def enqueue_cleanup(self, video_id: str) -> None:
        self._put(_CLEANUP, video_id)

    def enqueue_analysis(self, video_id: str) -> None:
        self._put(_ANALYSIS, video_id)

    def enqueue_suggestion(self, video_id: str, face_id: str) -> None:
        self._put(_SUGGEST, f"{video_id}:{face_id}")

    def enqueue_enrollment(self, enrollment_id: str) -> None:
        self._put(_ENROLL, enrollment_id)

    def enqueue_live(self, ident: str) -> None:
        self._put(_LIVE, ident)

    def _put(self, kind: str, ident: str) -> None:
        key = (kind, ident)
        with self._seen_lock:
            if key in self._seen:
                return
            self._seen.add(key)
        self._queue.put(key)

    # -- execution -----------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            # Run between tasks, never alongside inference or after releasing
            # ownership. Also runs on an empty queue (no client needed).
            if self.lock_acquired and self.live_maintenance is not None:
                try:
                    self.live_maintenance()
                except Exception:
                    logger.exception("live session maintenance failed; will retry")
            try:
                kind, ident = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._busy.set()
            try:
                self.process_one(kind, ident)
            except Exception:
                logger.exception("dispatcher task failed: %s %s", kind, ident)
            finally:
                with self._seen_lock:
                    self._seen.discard((kind, ident))
                self._busy.clear()
                self._queue.task_done()

    def process_one(self, kind: str, ident: str) -> None:
        if kind == _FACES:
            self._process_faces(ident)
        elif kind == _JOB:
            self._process_job(ident)
        elif kind == _CLEANUP:
            self._process_cleanup(ident)
        elif kind == _ANALYSIS:
            self._process_analysis(ident)
        elif kind == _SUGGEST:
            self._process_suggestion(*ident.split(":", 1))
        elif kind == _ENROLL:
            self._process_enrollment(ident)
        elif kind == _LIVE and self.live_handler is not None:
            self.live_handler(ident)

    def _process_job(self, job_id: str) -> None:
        try:
            self.worker.process(job_id)
        except ClaimConflict:
            logger.info("claim conflict for job %s; another worker owns it", job_id)
        except Exception:
            logger.exception("job %s failed outside worker error handling", job_id)

    def _process_faces(self, video_id: str) -> None:
        """Face detection; with the audio-only engine the audio analysis runs in
        parallel and is cached per video for enrollment and extraction."""
        analysis = None
        if self.settings.audio_only:
            analysis = threading.Thread(
                target=self._safe_analysis, args=(video_id,), name="focus-audio-analysis", daemon=True)
            analysis.start()
        try:
            self._detect_faces(video_id)
        finally:
            if analysis is not None:
                analysis.join()

    def _safe_analysis(self, video_id: str) -> None:
        try:
            self._process_analysis(video_id)
        except Exception:
            logger.exception("audio analysis crashed for %s", video_id)

    def _process_analysis(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            return
        current = self.repo.get_analysis(video_id)
        if current and current["status"] == "ready":
            return
        analyze = getattr(self.candidate_provider, "analyze", None)
        if analyze is None:
            self.repo.set_analysis(
                video_id, "failed", error_code="MODEL_UNAVAILABLE", retryable=False,
                error_message="audio analysis is not configured on this server")
            return
        self.repo.set_analysis(video_id, "pending")
        source = video.canonical_path or video.original_path
        written: list[Path] = []
        try:
            result = analyze(video_id=video_id, video_path=source)
            stored = dict(result)
            stored["speakers"] = []
            for index, speaker in enumerate(result["speakers"]):
                item = {k: v for k, v in speaker.items() if k != "sample_wav_b64"}
                item["clip"] = False
                if speaker.get("sample_wav_b64"):
                    import base64
                    from .inference import voice_sample_path
                    path = voice_sample_path(self.settings, video_id, index)
                    path.write_bytes(base64.b64decode(speaker["sample_wav_b64"]))
                    written.append(path)
                    item["clip"] = True
                stored["speakers"].append(item)
            if not self.repo.set_analysis(video_id, "ready", result=stored):
                raise RuntimeError("media was deleted")
        except Exception as exc:
            for path in written:
                path.unlink(missing_ok=True)
            message = getattr(exc, "message", None)
            if not isinstance(message, str) or not message:
                message = "audio analysis failed"
            logger.warning("audio analysis failed for %s: %s", video_id, message)
            self.repo.set_analysis(
                video_id, "failed", error_code=str(getattr(exc, "code", "PROCESSING_FAILED")),
                error_message=message, retryable=bool(getattr(exc, "retryable", True)))

    def _process_suggestion(self, video_id: str, face_id: str) -> None:
        face = self.repo.get_face(video_id, face_id)
        video = self.repo.get_video(video_id)
        if face is None or video is None or video.deleted:
            return
        visibility = getattr(self.candidate_provider, "visibility", None)
        try:
            if visibility is None:
                raise RuntimeError("face visibility is not configured")
            visible = visibility(video_id=video_id, face=face)
            self.repo.set_suggestion(video_id, face_id, "ready", visible=visible)
        except Exception as exc:
            message = getattr(exc, "message", None)
            if not isinstance(message, str) or not message:
                message = "could not measure when the face is on screen"
            self.repo.set_suggestion(
                video_id, face_id, "failed", error_code=str(getattr(exc, "code", "PROCESSING_FAILED")),
                error_message=message, retryable=bool(getattr(exc, "retryable", True)))

    def _process_enrollment(self, enrollment_id: str) -> None:
        item = self.repo.get_enrollment(enrollment_id)
        if item is None or item["status"] != "pending":
            return
        video_id, source = item["video_id"], item["source"]
        voice_file = self.settings.media_dir / f"{video_id}.voice-{enrollment_id}.wav"
        try:
            video = self.repo.get_video(video_id)
            analysis = self.repo.get_analysis(video_id)
            if video is None or video.deleted:
                return
            if item["source_kind"] == "range":
                if not analysis or analysis["status"] != "ready":
                    raise RuntimeError("audio analysis is not ready")
                result = self.candidate_provider.enroll_range(
                    video_id=video_id, diarization=analysis["result"]["diarization"],
                    start_ms=source["start_ms"], end_ms=source["end_ms"])
            else:
                result = self.candidate_provider.enroll_file(video_id=video_id, wav_path=str(voice_file))
            if "refused" in result:
                self.repo.finish_enrollment(
                    enrollment_id, "failed", error_code="ENROLLMENT_REFUSED",
                    error_message=result["refused"], retryable=False)
                return
            vp = result["voiceprint"]
            if result.get("reference_wav_b64"):   # clean reference audio of an uploaded voice file
                vp = dict(vp, reference_wav_b64=result["reference_wav_b64"])
            ok = self.repo.finish_enrollment(
                enrollment_id, "ready", voiceprint=vp, warnings=result["warnings"],
                clean_s=vp["duration_s"])
            current = self.repo.get_video(video_id)
            if ok and (current is None or current.deleted):
                self.repo.delete_voice_data(video_id)
        except Exception as exc:
            message = getattr(exc, "message", None)
            if not isinstance(message, str) or not message:
                message = "voice enrollment failed"
            self.repo.finish_enrollment(
                enrollment_id, "failed", error_code=str(getattr(exc, "code", "PROCESSING_FAILED")),
                error_message=message, retryable=bool(getattr(exc, "retryable", True)))
        finally:
            voice_file.unlink(missing_ok=True)  # a separate recording is never kept

    def _detect_faces(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            return
        source = video.canonical_path or video.original_path
        if not source or not Path(source).is_file():
            self.repo.set_faces_status(
                video_id,
                "failed",
                error_code="PROCESSING_FAILED",
                error_message="canonical media is unavailable",
                retryable=True,
            )
            return
        self.repo.set_faces_status(video_id, "pending")
        try:
            detected = list(
                self.candidate_provider.detect(video_id=video.video_id, video_path=source)
            )
            faces = self._persist_candidates(video, detected)
            self.repo.replace_faces(video.video_id, faces)
            self.repo.set_faces_status(video.video_id, "ready")
        except Exception as exc:  # provider errors are reported honestly
            message = getattr(exc, "message", None)
            code = getattr(exc, "code", "PROCESSING_FAILED")
            retryable = bool(getattr(exc, "retryable", True))
            if not isinstance(message, str) or not message:
                message = "face detection failed"
            logger.warning("face detection failed for %s: %s", video_id, message)
            self.repo.set_faces_status(
                video_id,
                "failed",
                error_code=str(code),
                error_message=message,
                retryable=retryable,
            )

    def _persist_candidates(
        self, video: VideoRecord, detected: list[DetectedFace]
    ) -> list[FaceRecord]:
        faces: list[FaceRecord] = []
        for item in detected:
            bbox = tuple(int(v) for v in item.bbox)
            if len(bbox) != 4 or bbox[2] < 0 or bbox[3] < 0:
                raise ValueError("provider returned an invalid bbox")
            frame_size = tuple(int(v) for v in item.frame_size)
            if len(frame_size) != 2 or frame_size[0] <= 0 or frame_size[1] <= 0:
                frame_size = (int(video.width), int(video.height))
            if frame_size[0] <= 0 or frame_size[1] <= 0:
                raise ValueError("provider returned an invalid frame size")
            face_id = make_face_id(
                video.video_id, int(item.timestamp_ms), bbox, frame_size
            )
            thumb_path = None
            thumb_mime = None
            if item.thumbnail_bytes:
                thumb_mime = item.thumbnail_mime or "image/jpeg"
                path = self.storage.thumbnail_path(video.video_id, face_id, thumb_mime)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(item.thumbnail_bytes)
                thumb_path = str(path)
            faces.append(
                FaceRecord(
                    video_id=video.video_id,
                    face_id=face_id,
                    timestamp_ms=int(item.timestamp_ms),
                    bbox=bbox,
                    frame_size=frame_size,
                    thumbnail_path=thumb_path,
                    thumbnail_mime=thumb_mime,
                )
            )
        # Identical canonical tuple => identical face_id. Deduplicate without
        # depending on detector ordering.
        return ordered_unique(faces)

    def _process_cleanup(self, video_id: str) -> None:
        video = self.repo.get_video(video_id)
        if video is None or not video.deleted:
            return
        for job in self.repo.jobs_for_video(video_id):
            self.storage.remove_job_dir(job.job_id)
        self.storage.remove_media(video_id)
        # Storage raises on incomplete deletion (including partial rmtree).
        # Retain the tombstone and paths until every removal has succeeded.
        self.repo.clear_media_paths(video_id)

    def _cleanup_deleted_videos(self) -> None:
        for video in self.repo.all_videos():
            if video.deleted:
                try:
                    self._process_cleanup(video.video_id)
                except OSError:
                    # Only filesystem failures permit degraded startup. Do not
                    # hide repository/programming errors or release ownership.
                    logger.exception(
                        "startup cleanup failed for video %s; tombstone and paths "
                        "retained for retry; continuing in degraded mode",
                        video.video_id,
                    )

    # -- deterministic test helper ------------------------------------------
    def drain(self, timeout: float = 30.0) -> int:
        """Process everything currently queued, synchronously.

        Only valid when the background thread is not running (tests use
        ``start_dispatcher=False``). This keeps the async pipeline explicit:
        requests enqueue, the dispatcher executes later.
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("drain() cannot run while the dispatcher thread is live")
        processed = 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                kind, ident = self._queue.get_nowait()
            except queue.Empty:
                return processed
            try:
                self.process_one(kind, ident)
                processed += 1
            except Exception:
                logger.exception("dispatcher task failed: %s %s", kind, ident)
            finally:
                with self._seen_lock:
                    self._seen.discard((kind, ident))
                self._queue.task_done()
        raise TimeoutError("dispatcher did not drain before the timeout")

    def wait_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty() and not self._busy.is_set():
                return True
            time.sleep(0.01)
        return False
