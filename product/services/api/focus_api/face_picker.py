"""Lightweight visual candidates; no face-to-voice identity is inferred."""
import os
from pathlib import Path

from .interfaces import DetectedFace, ProviderError


def detect_picker_faces(video_path):
    import cv2

    cascade_path = Path(os.environ.get('FOCUS_FACE_CASCADE') or
                        (Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'))
    if not cascade_path.is_file():
        raise ProviderError('The local face cascade is unavailable', retryable=False)
    detector = cv2.CascadeClassifier(str(cascade_path))
    if detector.empty():
        raise ProviderError('The local face cascade could not be loaded', retryable=False)
    cap = cv2.VideoCapture(str(video_path))
    best = None
    try:
        if not cap.isOpened():
            raise ProviderError('Video frames could not be opened', retryable=False)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # Pick one representative frame with the most simultaneous faces.
        # Never merge identities across shots using position alone.
        indices = sorted({int(i * max(0, count - 1) / 11) for i in range(12)})
        for index in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            if not ok:
                continue
            height, width = frame.shape[:2]
            scale = min(1.0, 960 / max(width, height))
            small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            boxes = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
            rank = (len(boxes), sum(int(w) * int(h) for _, _, w, h in boxes))
            if len(boxes) and (best is None or rank > best[0]):
                best = (rank, frame.copy(), boxes, scale, max(0, int(cap.get(cv2.CAP_PROP_POS_MSEC))))
    finally:
        cap.release()
    if best is None:
        return []
    _, frame, boxes, scale, timestamp = best
    height, width = frame.shape[:2]
    faces = []
    for raw in sorted(boxes, key=lambda b: int(b[0]))[:20]:
        x, y, w, h = (int(round(int(v) / scale)) for v in raw)
        w, h = min(w, width - x), min(h, height - y)
        crop = frame[max(0, y-h//5):min(height, y+h+h//5),
                     max(0, x-w//5):min(width, x+w+w//5)]
        crop = cv2.resize(crop, (192, 192))
        ok, encoded = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            faces.append(DetectedFace(bbox=(x, y, w, h), frame_size=(width, height),
                                     timestamp_ms=timestamp, thumbnail_bytes=encoded.tobytes()))
    return faces
