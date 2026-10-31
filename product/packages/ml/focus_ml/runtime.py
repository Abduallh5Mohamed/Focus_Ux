"""Real, offline-only engine shared by local API and outbound Windows worker.

Imports remain light until initialize(). Original code, caches and weights are
read-only; all clip artifacts belong to the caller's temporary directory.
"""
from __future__ import annotations

import base64
import os
import socket
from contextlib import contextmanager
from pathlib import Path

from .adapter import LegacyDolphinAdapter
from .config import AdapterConfig
from .isolation_engines import build_engine
from .errors import FaceNotFoundError, MediaError, ModelUnavailableError
from .face_detector import DetectionOnlyBackend


@contextmanager
def offline_inference():
    """Fail rather than let third-party detector/landmarker fetch missing weights.

    Use only in the single-threaded inference process. Bridge HTTP happens
    outside this scope. HF's offline flag alone does not cover torch/landmarks.
    """
    old_connect, old_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def denied(*_args, **_kwargs):
        raise ModelUnavailableError("a required model asset is missing; downloads are disabled")

    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = old_connect, old_connect_ex


class LocalEngine:
    def __init__(self, config: AdapterConfig):
        self.config = config
        self.adapter = LegacyDolphinAdapter(config)
        self.models = None
        self.face_detector = DetectionOnlyBackend(config)
        self.isolation = build_engine(config, self.adapter, lambda: self.models)

    def initialize(self):
        if self.models is not None:
            return
        for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            os.environ[name] = "1"
        source = Path(self.config.model_source or "")
        cache = Path(self.config.model_cache or "")
        required = (source / "Inference.py", source / "assets" / "20words_mean_face.npy")
        if not self.config.model_source or not all(p.is_file() for p in required):
            raise ModelUnavailableError("the original Dolphin source or mean-face asset is missing")
        if not self.config.model_cache or not cache.is_dir():
            raise ModelUnavailableError("the original populated model cache is missing")
        # Fail before loading the GPU if the chosen extra engine lacks weights.
        self.isolation.check_ready()
        with offline_inference():
            self.models = self.adapter.load_models(self.config)

    def _detector(self):
        """Detection-only path: no Dolphin weights, landmarks or isolation engine.

        Reuses the legacy detector of an already-initialized lip engine."""
        if self.models is not None:
            return "dolphin_legacy", self.models.detect_faces
        with offline_inference():
            backend = self.face_detector.load()
        return backend.name, backend.detect_faces

    def face_detector_status(self) -> dict:
        return self.face_detector.status()

    def detect(self, video_id: str, video_path: str) -> list[dict]:
        from .adapter import _bgr_to_rgb, _build_first_frame_candidates

        with offline_inference():
            if not os.path.isfile(video_path):
                raise MediaError("media file not found")
            detector_name, detect_faces = self._detector()
            first = self.adapter._read_first_frame(video_path)
            if first is None:
                raise MediaError("the first video frame could not be read")
            frame, frame_size = first
            detections = self.adapter._detect_frame(detect_faces, _bgr_to_rgb(frame))
            if not detections:
                raise FaceNotFoundError("no face detected on the first frame of the requested media")
            candidates, _ = _build_first_frame_candidates(detections, video_id, frame_size, self.config)
            import cv2

            results = []
            for face in candidates:
                x, y, w, h = face.bbox
                crop = frame[y:y + h, x:x + w]
                if crop.size == 0:
                    raise MediaError("detector returned an empty face crop")
                scale = min(1.0, 192 / max(w, h))
                crop = cv2.resize(crop, (max(1, round(w * scale)), max(1, round(h * scale))))
                ok, encoded = cv2.imencode(".jpg", crop)
                if not ok:
                    raise MediaError("face thumbnail could not be encoded")
                results.append({
                    "bbox": face.bbox, "frame_size": face.frame_size,
                    "timestamp_ms": face.timestamp_ms, "detector": detector_name,
                    "thumbnail": base64.b64encode(encoded.tobytes()).decode("ascii"),
                })
            return results

    def extract(self, video_id, video_path, face_id, job_dir, on_progress=None):
        self.initialize()
        with offline_inference():
            return self.isolation.run(video_id, video_path, face_id, job_dir, on_progress)

    # -- audio-only engine (no frames, faces or lips after enrollment) -------
    @property
    def audio(self):
        if getattr(self, "_audio", None) is None:
            from .voice.engine import AudioOnlyEngine
            self._audio = AudioOnlyEngine.from_env()
        return self._audio

    def analyze_audio(self, audio_path):
        with offline_inference():
            return self.audio.analyze(audio_path)

    def enroll_audio_range(self, audio_path, diarization, start_s, end_s):
        with offline_inference():
            return self.audio.enroll_range(audio_path, diarization, start_s, end_s)

    def enroll_audio_file(self, audio_path):
        with offline_inference():
            return self.audio.enroll_file(audio_path)

    def isolate_audio(self, audio_path, voiceprint, diarization, job_dir, on_progress=None):
        with offline_inference():
            return self.audio.isolate(audio_path, voiceprint, diarization, job_dir, on_progress)

    def face_visibility(self, video_path, bbox, frame_size):
        """On-screen spans of the chosen face; used only to rank voice candidates."""
        from .adapter import _bgr_to_rgb, _corners_to_xywh
        from .voice.visibility import read_samples, track_visibility

        _name, detect_faces = self._detector()

        def detect(frame):
            corners = self.adapter._detect_frame(detect_faces, _bgr_to_rgb(frame))
            return [tuple(float(v) for v in _corners_to_xywh(c, frame_size)[0]) for c in corners]

        with offline_inference():
            return track_visibility(read_samples(video_path), detect, tuple(float(v) for v in bbox))
