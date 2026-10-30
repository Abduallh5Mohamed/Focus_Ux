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
from .errors import MediaError, ModelUnavailableError


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

    def detect(self, video_id: str, video_path: str) -> list[dict]:
        self.initialize()
        with offline_inference():
            candidates = self.adapter.detect_candidates(
                video_path, self.config, video_id=video_id
            )
            import cv2

            capture = cv2.VideoCapture(video_path)
            try:
                ok, frame = capture.read()
            finally:
                capture.release()
            if not ok or frame is None:
                raise MediaError("the first video frame could not be read")
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
                    "timestamp_ms": face.timestamp_ms,
                    "thumbnail": base64.b64encode(encoded.tobytes()).decode("ascii"),
                })
            return results

    def extract(self, video_id, video_path, face_id, job_dir, on_progress=None):
        self.initialize()
        with offline_inference():
            return self.isolation.run(video_id, video_path, face_id, job_dir, on_progress)
