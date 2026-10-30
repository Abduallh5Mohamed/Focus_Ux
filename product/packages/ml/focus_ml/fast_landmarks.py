"""Fast face landmarks via MediaPipe Face Landmarker.

``face_alignment`` runs per frame and was the slowest stage (~50 s per 15 s
clip). This wrapper runs on the already-selected 224x224 face crop and returns
68 points in the dlib/face_alignment order, because the mouth-ROI stage reads
fixed points (33,36,39,42,45) and mouth points 48-67. Offline only: the
``.task`` model file must already exist (never downloaded).
"""
from __future__ import annotations

import os

from focus_ml.errors import ModelUnavailableError

# dlib 68 index -> MediaPipe 478-mesh index. Mouth (48-67) and the stable
# anchors (33, 36, 39, 42, 45) are exact; the rest are nearest equivalents.
MESH_TO_68 = (
    234, 93, 132, 58, 172, 136, 150, 149, 152, 378, 379, 365, 397, 288, 361, 323, 454,  # 0-16 jaw
    70, 63, 105, 66, 107, 336, 296, 334, 293, 300,  # 17-26 brows
    168, 6, 197, 195,  # 27-30 nose bridge
    98, 97, 2, 326, 327,  # 31-35 nose base (33 = nose tip anchor)
    33, 160, 158, 133, 153, 144,  # 36-41 eye (36 outer, 39 inner)
    362, 385, 387, 263, 373, 380,  # 42-47 eye (42 inner, 45 outer)
    61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91,  # 48-59 outer lip
    78, 81, 13, 311, 308, 402, 14, 178,  # 60-67 inner lip
)
assert len(MESH_TO_68) == 68


def mesh_to_68(points, width: float, height: float):
    """Convert normalised mesh points (N>=468, at least x/y) to a (68, 2) pixel
    array. Raises ValueError for an incomplete mesh."""
    import numpy as np

    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] <= max(MESH_TO_68) or pts.shape[1] < 2:
        raise ValueError("face mesh has too few points")
    xy = pts[list(MESH_TO_68), :2]
    return xy * np.array([width, height], dtype=np.float64)


class MediaPipeLandmarker:
    """Drop-in for ``face_alignment.FaceAlignment.get_landmarks``."""

    def __init__(self, model_path: str | None):
        if not model_path or not os.path.isfile(model_path):
            raise ModelUnavailableError(
                "the MediaPipe face landmarker model file is missing "
                "(set FOCUS_FACE_LANDMARKER_MODEL); downloads are disabled"
            )
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            options = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=model_path),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=1,
                min_face_detection_confidence=0.3,
                min_face_presence_confidence=0.3,
            )
            self._landmarker = vision.FaceLandmarker.create_from_options(options)
            self._mp = mp
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError(
                f"MediaPipe face landmarker could not start: {type(exc).__name__}: {exc}"
            ) from exc

    def get_landmarks(self, rgb):
        """rgb: HxWx3 uint8. Returns [array(68,2)] or None when no face."""
        import numpy as np

        height, width = rgb.shape[:2]
        image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)
        )
        result = self._landmarker.detect(image)
        if not result.face_landmarks:
            return None
        mesh = [(p.x, p.y) for p in result.face_landmarks[0]]
        return [mesh_to_68(mesh, width, height)]
