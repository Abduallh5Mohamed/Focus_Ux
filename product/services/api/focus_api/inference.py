"""API integration: canonical media, persisted face identity, real providers."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

from services.worker import errors as worker_errors
from services.worker.interfaces import TargetRunResult

from .identity import make_face_id
from .interfaces import DetectedFace, ProviderError
from .media_probe import probe_video

ENGINE_WARNING = "engine: "  # marker stored with the job's audio warnings


def decode_faces(items):
    if not isinstance(items, list) or len(items) > 20:
        raise ProviderError("invalid detector result", retryable=False)
    faces = []
    for item in items:
        bbox, size = item["bbox"], item["frame_size"]
        if (
            len(bbox) != 4 or len(size) != 2
            or any(type(v) is not int for v in (*bbox, *size))
            or min(*size, bbox[2], bbox[3]) <= 0 or min(bbox[:2]) < 0
            or bbox[0] + bbox[2] > size[0] or bbox[1] + bbox[3] > size[1]
            or type(item["timestamp_ms"]) is not int or item["timestamp_ms"] != 0
        ):
            raise ProviderError("invalid first-frame face geometry", retryable=False)
        thumbnail = base64.b64decode(item["thumbnail"], validate=True)
        if not thumbnail.startswith(b"\xff\xd8") or len(thumbnail) > 64 * 1024:
            raise ProviderError("invalid detector thumbnail", retryable=False)
        faces.append(DetectedFace(
            bbox=tuple(bbox), frame_size=tuple(size), timestamp_ms=0,
            thumbnail_bytes=thumbnail,
        ))
    return faces


class InferenceProviders:
    """One instance used by both dispatcher seams, preserving serialization."""
    def __init__(self, settings, repo, *, bridge=None, engine=None):
        self.settings, self.repo = settings, repo
        self.bridge, self.engine = bridge, engine

    def _canonical(self, video_id, source):
        from focus_ml.config import AdapterConfig
        from focus_ml.normalize import normalize_input

        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            raise ProviderError("media was deleted", retryable=False)
        target = self.settings.media_dir / f"{video_id}.canonical.mp4"
        if video.canonical_path == str(target) and target.is_file():
            return str(target)
        # Never normalize in the model checkout or overwrite the user's upload.
        with tempfile.TemporaryDirectory(dir=self.settings.tmp_dir) as tmp:
            normalized = normalize_input(
                source, tmp, AdapterConfig(
                    max_video_seconds=self.settings.max_video_ms / 1000,
                    max_upload_mb=self.settings.max_upload_mb,
                ),
            )
            if abs(normalized.duration_ms - video.duration_ms) > 80:
                raise ProviderError("normalization changed the source timeline", retryable=False)
            info = probe_video(normalized.video_path)
            if abs(info.duration_ms - video.duration_ms) > 80:
                raise ProviderError("canonical video changed the source timeline", retryable=False)
            if Path(normalized.video_path).stat().st_size > self.settings.max_upload_bytes:
                raise ProviderError("normalized media exceeds the transfer limit", code="LIMIT_EXCEEDED")
            os.replace(normalized.video_path, target)
        if not self.repo.set_canonical(
            video_id, str(target), info.duration_ms, info.width, info.height
        ):
            target.unlink(missing_ok=True)
            raise ProviderError("media was deleted", retryable=False)
        return str(target)

    def detect(self, *, video_id, video_path):
        try:
            if self.bridge:
                self.bridge.ensure_ready()
            canonical = self._canonical(video_id, video_path)
            raw = (
                self.bridge.call(kind="detect", video_id=video_id, video_path=canonical)
                if self.bridge else self.engine.detect(video_id, canonical)
            )
            faces = decode_faces(raw)
            video = self.repo.get_video(video_id)
            if video is None or video.deleted:
                raise ProviderError("media was deleted", retryable=False)
            if any(face.frame_size != (video.width, video.height) for face in faces):
                raise ProviderError("detector geometry differs from canonical media", retryable=False)
            return faces
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                "real face detection failed; check the model runtime",
                code=getattr(exc, "code", "PROCESSING_FAILED"),
                retryable=getattr(exc, "retryable", True),
            ) from exc

    def extract(self, job, job_dir, on_progress):
        try:
            video = self.repo.get_video(job.video_id)
            face = self.repo.get_face(job.video_id, job.face_id)
            if video is None or video.deleted or face is None:
                raise worker_errors.FaceNotFoundError()
            expected = make_face_id(job.video_id, face.timestamp_ms, face.bbox, face.frame_size)
            if expected != job.face_id or job.video_path != video.canonical_path:
                raise worker_errors.FaceNotFoundError("selected face does not match canonical media")
            if self.bridge:
                data, duration, engine = self.bridge.call(
                    kind="extract", video_id=job.video_id,
                    video_path=job.video_path, face_id=job.face_id,
                )
                on_progress("separating", 1.0)
                path = Path(job_dir) / "isolated.wav"
                path.write_bytes(data)
                return TargetRunResult(
                    str(path), duration, source_offset_ms=0,
                    warnings=[ENGINE_WARNING + engine,
                              "real inference returned by the operator's connected computer"],
                )
            result = self.engine.extract(
                job.video_id, job.video_path, job.face_id, job_dir, on_progress
            )
            from .remote_inference import MAX_AUDIO_BYTES, validate_wav
            output = Path(result.wav_path)
            if result.source_offset_ms != 0 or output.stat().st_size > MAX_AUDIO_BYTES:
                raise worker_errors.ProcessingError("invalid or shifted audio result")
            duration = validate_wav(output.read_bytes(), video.duration_ms)
            if abs(duration - result.duration_ms) > 1:
                raise worker_errors.ProcessingError("audio metadata disagrees with actual samples")
            fields = {k: v for k, v in vars(result).items() if k not in ("engine", "details")}
            fields["warnings"] = [ENGINE_WARNING + getattr(result, "engine", "dolphin"),
                                  *fields["warnings"]]
            return TargetRunResult(**fields)
        except worker_errors.WorkerError:
            raise
        except Exception as exc:
            code = getattr(exc, "code", "PROCESSING_FAILED")
            error_type = next(
                (cls for cls in (
                    worker_errors.MediaError, worker_errors.NoAudioError,
                    worker_errors.LimitExceededError, worker_errors.FaceNotFoundError,
                    worker_errors.TargetLostError, worker_errors.GpuBusyError,
                ) if cls.code == code),
                worker_errors.ProcessingError,
            )
            # No raw model exceptions, filenames or local paths in API errors.
            raise error_type(
                "real speaker extraction failed; check the inference computer",
                retryable=getattr(exc, "retryable", True),
            ) from exc


def build_inference(settings, repo):
    if settings.inference_mode == "unavailable":
        return None, None
    if settings.inference_mode == "remote":
        from .remote_inference import RemoteBridge
        bridge = RemoteBridge(settings.worker_token or "", repo)
        return InferenceProviders(settings, repo, bridge=bridge), bridge
    if settings.inference_mode == "local":
        from focus_ml.config import AdapterConfig
        from focus_ml.runtime import LocalEngine
        return InferenceProviders(
            settings, repo, engine=LocalEngine(AdapterConfig.from_env())
        ), None
    raise ValueError("FOCUS_INFERENCE_MODE must be unavailable, local or remote")
