"""Detection-only face backend.

Candidate thumbnails and the face-visibility hint need a face *detector* and
nothing else. This module loads only that: the legacy ``face_detection_utils``
from the configured Dolphin source or, when it cannot be imported, OpenCV's
bundled Haar frontal-face cascade (shipped inside opencv-python; no download).

It never loads Dolphin weights, face-alignment landmarks, the isolation engine
readiness check or ``look2hear``. Lip-engine extraction keeps using the full
initialization in ``LocalEngine.initialize``.
"""
from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path

from .config import AdapterConfig
from .errors import ModelUnavailableError

LEGACY = "dolphin_legacy"
HAAR = "opencv_haar"

_PATHISH = re.compile(r"(?:[A-Za-z]:[\\/]|/)[^\s'\"]+")


def safe_reason(text: str, limit: int = 300) -> str:
    """Error text that is fit to show a user: no local paths, bounded length."""
    return _PATHISH.sub("<path>", " ".join(str(text).split()))[:limit]


class DetectionOnlyBackend:
    """Resolves one ``detect_faces(frame_rgb, threshold, allow_upscaling)`` callable."""

    def __init__(self, config: AdapterConfig, *, cv2_module=None):
        self.config = config
        self._cv2 = cv2_module
        self._lock = threading.Lock()
        self.name: str | None = None
        self.detect_faces = None
        self.last_error: str | None = None

    def status(self) -> dict:
        return {"detector": self.name, "error": self.last_error}

    def load(self):
        with self._lock:
            if self.detect_faces is not None:
                return self
            problems: list[str] = []
            try:
                self.detect_faces, self.name = self._load_legacy(), LEGACY
            except Exception as exc:
                problems.append(f"Dolphin face detector: {type(exc).__name__}: {exc}")
                try:
                    self.detect_faces, self.name = self._load_haar(), HAAR
                except Exception as exc2:
                    problems.append(f"OpenCV Haar detector: {type(exc2).__name__}: {exc2}")
            if self.detect_faces is None:
                self.last_error = safe_reason("; ".join(problems))
                raise ModelUnavailableError(
                    "no face detector could run on this computer", detail=self.last_error)
            # A fallback detector is working: keep why the preferred one was skipped.
            self.last_error = safe_reason(problems[0]) if problems else None
            return self

    def _load_legacy(self):
        source = self.config.model_source
        if not source or not os.path.isdir(source):
            raise ModelUnavailableError("model source directory is missing or unset")
        if not (Path(source) / "face_detection_utils.py").is_file() and \
                "face_detection_utils" not in sys.modules:
            raise ModelUnavailableError("face_detection_utils is missing from the model source")
        previous_cwd = os.getcwd()
        added = source not in sys.path
        if added:
            sys.path.insert(0, source)
        try:
            os.chdir(source)
            from face_detection_utils import detect_faces  # legacy detector only
        finally:
            os.chdir(previous_cwd)
            if added:
                try:
                    sys.path.remove(source)
                except ValueError:
                    pass
        return detect_faces

    def _load_haar(self):
        cv2 = self._cv2 or __import__("cv2")
        path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            raise ModelUnavailableError("the bundled Haar cascade could not be loaded")

        def detect_faces(frame_rgb, threshold=0.9, allow_upscaling=False):
            gray = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2GRAY)
            strict = threshold >= 0.9
            boxes = cascade.detectMultiScale(
                gray, scaleFactor=1.1 if strict else 1.05, minNeighbors=5 if strict else 3,
                minSize=(40, 40))
            return [[float(x), float(y), float(x + w), float(y + h), 1.0]
                    for x, y, w, h in boxes], None

        return detect_faces
