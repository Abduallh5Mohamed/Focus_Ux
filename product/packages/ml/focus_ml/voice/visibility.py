"""When is the chosen face on screen? Used only while the user enrolls a voice.

The face is followed from its first-frame box by detector continuity: at each
sample the detection that overlaps the last known box best (IoU or centre
distance) is the same face; no detection means the face is not visible. The
sampling is sparse (default 2 per second), frames are read one by one, and the
result is only a list of visible time spans. It is a hint for ranking voices
and is never used to extract audio.

A speaking-face (lip) score was NOT added: it has not been measured as useful
(docs/VOICE_PIPELINE_LOG.md), so the suggestion uses on-screen time only.
"""
from __future__ import annotations

from typing import Callable, Iterable

Box = tuple[float, float, float, float]  # x, y, w, h


def iou(a: Box, b: Box) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw, ih = min(ax2, bx2) - max(a[0], b[0]), min(ay2, by2) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _same_face(last: Box, cand: Box, min_iou: float) -> bool:
    if iou(last, cand) >= min_iou:
        return True
    lcx, lcy = last[0] + last[2] / 2, last[1] + last[3] / 2
    ccx, ccy = cand[0] + cand[2] / 2, cand[1] + cand[3] / 2
    return abs(lcx - ccx) <= last[2] and abs(lcy - ccy) <= last[3] and \
        0.5 <= cand[2] / max(last[2], 1e-6) <= 2.0


def track_visibility(samples: Iterable[tuple[int, object]], detect: Callable[[object], list[Box]],
                     first_box: Box, *, min_iou: float = 0.3, max_gap_ms: int = 1500,
                     step_ms: int = 500) -> list[dict]:
    """``samples`` yields (timestamp_ms, frame). Returns merged visible spans."""
    last, spans = first_box, []
    for ts, frame in samples:
        match = None
        best = 0.0
        for box in detect(frame):
            if _same_face(last, box, min_iou):
                score = iou(last, box)
                if match is None or score >= best:
                    match, best = box, score
        if match is None:
            continue
        last = match
        start, end = ts, ts + step_ms
        if spans and start - spans[-1]["end_ms"] <= max_gap_ms - step_ms:
            spans[-1]["end_ms"] = end
        else:
            spans.append({"start_ms": start, "end_ms": end})
    return spans


def read_samples(video_path: str, step_ms: int = 500):
    """Yield (timestamp_ms, BGR frame) every ``step_ms`` without keeping frames."""
    import cv2
    capture = cv2.VideoCapture(video_path)
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        stride = max(1, round(fps * step_ms / 1000))
        index = 0
        while True:
            ok = capture.grab()
            if not ok:
                return
            if index % stride == 0:
                ok, frame = capture.retrieve()
                if ok and frame is not None:
                    yield int(round(index * 1000 / fps)), frame
            index += 1
    finally:
        capture.release()


def clamp_spans(spans: list[dict], duration_ms: int) -> list[dict]:
    return [{"start_ms": s["start_ms"], "end_ms": min(s["end_ms"], duration_ms)}
            for s in spans if s["start_ms"] < duration_ms]
