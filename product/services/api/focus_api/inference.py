"""API integration: canonical media, persisted face identity, real providers."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from services.worker import errors as worker_errors
from services.worker.interfaces import TargetRunResult

from .identity import make_face_id
from .interfaces import DetectedFace, ProviderError
from .media_probe import probe_video

ENGINE_WARNING = "engine: "  # marker stored with the job's audio warnings
ROUTING_PREFIX = "routing: "  # JSON overlap-routing summary stored the same way


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


def extract_audio_wav(ffmpeg: str, source: str, target: str, duration_ms: int | None = None) -> None:
    """16 kHz mono PCM16 track of any media file. Video, if any, is dropped here:
    everything the audio-only engine receives is derived from this file."""
    command = [ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source), "-vn", "-map", "0:a:0",
               "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
    if duration_ms:
        command += ["-af", "apad", "-t", f"{duration_ms / 1000:.3f}"]
    tmp = f"{target}.part.wav"
    try:
        result = subprocess.run(command + [tmp], capture_output=True, timeout=300)
        if result.returncode != 0 or not os.path.isfile(tmp):
            raise ProviderError("the video has no usable audio track", code="NO_AUDIO", retryable=False)
        os.replace(tmp, target)
    except subprocess.SubprocessError as exc:
        raise ProviderError("audio extraction failed", retryable=True) from exc
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def voice_sample_path(settings, video_id: str, index: int) -> Path:
    return settings.media_dir / f"{video_id}.sample{index}.wav"


class InferenceProviders:
    """One instance used by both dispatcher seams, preserving serialization."""
    def __init__(self, settings, repo, *, bridge=None, engine=None):
        self.settings, self.repo = settings, repo
        self.bridge, self.engine = bridge, engine
        self._canon_lock = threading.Lock()  # detection and analysis start together

    def _canonical(self, video_id, source):
        with self._canon_lock:
            return self._canonical_locked(video_id, source)

    def _canonical_locked(self, video_id, source):
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

    # -- audio-only engine ---------------------------------------------------
    def _live_video(self, video_id):
        video = self.repo.get_video(video_id)
        if video is None or video.deleted:
            raise ProviderError("media was deleted", retryable=False)
        return video

    def audio_path(self, video_id, source=None) -> str:
        """The video's audio track, extracted once and reused by every audio task."""
        video = self._live_video(video_id)
        target = self.settings.media_dir / f"{video_id}.audio.wav"
        if target.is_file():
            return str(target)
        canonical = self._canonical(video_id, source or video.canonical_path or video.original_path)
        extract_audio_wav(self.settings.ffmpeg_path, canonical, str(target), video.duration_ms)
        if not self.repo.get_video(video_id) or self.repo.get_video(video_id).deleted:
            target.unlink(missing_ok=True)
            raise ProviderError("media was deleted", retryable=False)
        return str(target)

    def _wrap(self, what, fn):
        try:
            return fn()
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"{what} failed; check the model runtime",
                code=getattr(exc, "code", "PROCESSING_FAILED"),
                retryable=getattr(exc, "retryable", True),
            ) from exc

    def analyze(self, *, video_id, video_path=None):
        """Diarization + voiceprints + sample clips for one video (audio only)."""
        from .remote_inference import validate_analysis

        def run():
            video = self._live_video(video_id)
            audio = self.audio_path(video_id, video_path)
            raw = (self.bridge.call(kind="analyze", video_id=video_id, video_path=audio,
                                    timeout_s=900.0)
                   if self.bridge else self.engine.analyze_audio(audio))
            return validate_analysis(raw, video.duration_ms)
        return self._wrap("audio analysis", run)

    def enroll_range(self, *, video_id, diarization, start_ms, end_ms):
        return self._enroll(video_id, {"mode": "range", "start_ms": start_ms, "end_ms": end_ms,
                                       "diarization": diarization}, None)

    def enroll_file(self, *, video_id, wav_path):
        return self._enroll(video_id, {"mode": "file"}, wav_path)

    def _enroll(self, video_id, payload, wav_path):
        from .remote_inference import validate_enrollment

        def run():
            self._live_video(video_id)
            audio = wav_path or self.audio_path(video_id)
            if self.bridge:
                raw = self.bridge.call(kind="enroll", video_id=video_id, video_path=audio,
                                       payload=payload, timeout_s=600.0)
            else:
                from focus_ml.voice.errors import EnrollmentError
                try:
                    if payload["mode"] == "range":
                        raw = self.engine.enroll_audio_range(
                            audio, payload["diarization"], payload["start_ms"] / 1000,
                            payload["end_ms"] / 1000)
                    else:
                        raw = self.engine.enroll_audio_file(audio)
                except EnrollmentError as exc:
                    raw = {"refused": str(getattr(exc, "message", exc))}
            return validate_enrollment(raw)
        return self._wrap("voice enrollment", run)

    def visibility(self, *, video_id, face):
        """On-screen spans of the chosen face. Enrollment-time hint only."""
        from .remote_inference import validate_visibility

        def run():
            video = self._live_video(video_id)
            canonical = self._canonical(video_id, video.canonical_path or video.original_path)
            payload = {"bbox": list(face.bbox), "frame_size": list(face.frame_size)}
            if self.bridge:
                raw = self.bridge.call(kind="visibility", video_id=video_id, video_path=canonical,
                                       face_id=face.face_id, payload=payload, timeout_s=600.0)
            else:
                raw = {"visible": self.engine.face_visibility(canonical, face.bbox, face.frame_size)}
            return validate_visibility(raw, video.duration_ms)
        return self._wrap("face visibility", run)

    def _extract_audio_only(self, job, job_dir, on_progress):
        """Audio + enrollment only. Nothing from the video reaches this call."""
        from .remote_inference import validate_regions
        enrollment = self.repo.get_enrollment(job.enrollment_id or "")
        analysis = self.repo.get_analysis(job.video_id)
        video = self.repo.get_video(job.video_id)
        if video is None or video.deleted or not enrollment or enrollment["status"] != "ready" \
                or enrollment["video_id"] != job.video_id or not analysis or not analysis["result"]:
            raise worker_errors.ProcessingError("the voice enrollment is no longer available",
                                                retryable=False)
        audio = self.audio_path(job.video_id)
        diarization = analysis["result"]["diarization"]
        voiceprint = dict(enrollment["voiceprint"])
        # Clean reference audio for target-conditioned overlap models (uploaded voice
        # files only; other enrollments rebuild it from the recording). Audio, no video.
        reference_b64 = voiceprint.pop("reference_wav_b64", None)
        on_progress("matching", 0.0)
        if self.bridge:
            payload = {"voiceprint": voiceprint, "diarization": diarization}
            if reference_b64:
                payload["reference_wav_b64"] = reference_b64
            data, duration, engine, regions, *rest = self.bridge.call(
                kind="isolate", video_id=job.video_id, video_path=audio,
                payload=payload,
                timeout_s=max(1800.0, video.duration_ms / 1000 * 10))
            path = Path(job_dir) / "isolated.wav"
            path.write_bytes(data)
            routing = rest[0] if rest else None
        else:
            reference = None
            if reference_b64:
                from .remote_inference import decode_reference
                reference = decode_reference(reference_b64)
            result = self.engine.isolate_audio(audio, voiceprint, diarization, job_dir, on_progress,
                                               **({"reference_audio": reference} if reference is not None else {}))
            routing = result.details.get("routing_summary")
            from focus_ml.voice.engine import regions_to_wire
            from .remote_inference import validate_wav
            path = Path(result.wav_path)
            duration = validate_wav(path.read_bytes(), video.duration_ms, self.settings.max_audio_s)
            engine = "audio_only"
            regions = validate_regions({"regions": regions_to_wire(result.details["regions"])},
                                       video.duration_ms)
        on_progress("separating", 1.0)
        periods = [
            {"start_ms": r["start_ms"], "end_ms": r["end_ms"],
             "state": "voice_follow" if r["label"] == "target" else "uncertain",
             "reason": "voice_match" if r["label"] == "target" else "uncertain_voice",
             "output_allowed": r["label"] == "target"}
            for r in regions
        ]
        warnings = [ENGINE_WARNING + engine]
        if routing:
            warnings.append(ROUTING_PREFIX + json.dumps(routing, separators=(",", ":")))
        if not any(r["label"] == "target" for r in regions):
            warnings.append("The enrolled voice was not found in the audio; the result is silent.")
        return TargetRunResult(str(path), duration, source_offset_ms=0, warnings=warnings,
                               follow_periods=periods)

    def extract(self, job, job_dir, on_progress):
        if job.enrollment_id:
            try:
                return self._extract_audio_only(job, job_dir, on_progress)
            except worker_errors.WorkerError:
                raise
            except ProviderError as exc:
                error_type = next((c for c in (
                    worker_errors.NoAudioError, worker_errors.LimitExceededError,
                    worker_errors.GpuBusyError) if c.code == exc.code), worker_errors.ProcessingError)
                raise error_type(exc.message, retryable=exc.retryable) from exc
            except Exception as exc:
                raise worker_errors.ProcessingError(
                    "voice isolation failed; check the inference computer",
                    retryable=getattr(exc, "retryable", True)) from exc
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
        bridge = RemoteBridge(settings.worker_token or "", repo, max_audio_s=settings.max_audio_s)
        return InferenceProviders(settings, repo, bridge=bridge), bridge
    if settings.inference_mode == "local":
        from focus_ml.config import AdapterConfig
        from focus_ml.runtime import LocalEngine
        import os
        env = dict(os.environ)
        # audio_only is an API-level engine; the lip adapter keeps a lip engine for
        # face detection and never runs it for enrollment jobs.
        if env.get("FOCUS_ISOLATION_ENGINE", "").strip() == "audio_only":
            env["FOCUS_ISOLATION_ENGINE"] = "dolphin"
        return InferenceProviders(
            settings, repo, engine=LocalEngine(AdapterConfig.from_env(env))
        ), None
    raise ValueError("FOCUS_INFERENCE_MODE must be unavailable, local or remote")
