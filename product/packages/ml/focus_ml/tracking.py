"""Pure IoU tracking port of the legacy detectface/_detect_track matching
(legacy_snapshot/tools/focus_runner.py lines 146-170 and
legacy_snapshot/Dolphin/Inference.py ``face2head``/``bb_intersection_over_union``).

No torch/cv2 here: detection itself is engine-side; this module only matches
boxes across frames with the legacy semantics.
"""
from __future__ import annotations

from typing import Optional, Sequence

DETECT_EVERY: int = 8
FACE_BOX_SCALE: float = 1.5


def bb_intersection_over_union(box_a: Sequence[float], box_b: Sequence[float]) -> float:
    """Legacy logic on corner boxes (x1,y1,x2,y2) including the +1 terms.
    Zero-area (degenerate, non-positive extent) boxes yield 0.0 instead of the
    legacy +1 quirks producing a spurious 1.0 or ZeroDivisionError."""
    if (
        box_a[2] - box_a[0] <= 0
        or box_a[3] - box_a[1] <= 0
        or box_b[2] - box_b[0] <= 0
        or box_b[3] - box_b[1] <= 0
    ):
        return 0.0
    x_a = max(box_a[0], box_b[0])
    y_a = max(box_a[1], box_b[1])
    x_b = min(box_a[2], box_b[2])
    y_b = min(box_a[3], box_b[3])
    inter_area = max(0, x_b - x_a + 1) * max(0, y_b - y_a + 1)
    box_a_area = (box_a[2] - box_a[0] + 1) * (box_a[3] - box_a[1] + 1)
    box_b_area = (box_b[2] - box_b[0] + 1) * (box_b[3] - box_b[1] + 1)
    denominator = float(box_a_area + box_b_area - inter_area)
    if denominator == 0.0:
        return 0.0
    return inter_area / denominator


def character_to_face(
    box: Sequence[float], scale: float = FACE_BOX_SCALE
) -> tuple[float, float, float, float]:
    """Center-preserving square expansion of a (x, y, w, h) box, converted to
    corners the way legacy ``Inference.face2head`` does: the input is converted
    to corners (x1,y1,x2,y2) first, then ``square = int(max(w, h) * scale)`` is
    centered on the midpoint.

    NOTE: numerical equivalence against the legacy engine is UNVERIFIED pending
    GPU validation (docs/01 gap #5: legacy expansion may leave frame bounds;
    nothing is padded or clipped silently here).
    """
    x, y = float(box[0]), float(box[1])
    width, height = float(box[2]), float(box[3])
    x2, y2 = x + width, y + height
    width_center = (x2 + x) / 2
    height_center = (y2 + y) / 2
    square_width = int(max(width, height) * scale)
    return (
        width_center - square_width / 2,
        height_center - square_width / 2,
        width_center + square_width / 2,
        height_center + square_width / 2,
    )


def match_detections(
    previous_boxes: Sequence[Optional[Sequence[float]]],
    detected: Sequence[Sequence[float]],
    threshold: float = 0.0,
) -> list[Optional[Sequence[float]]]:
    """Per-speaker IoU matching with legacy semantics: each detected box goes
    to the best-scoring unmatched speaker (matched speakers are skipped with
    score -1, so one detection can never map to two speakers); an unmatched
    speaker holds its last box. A speaker with no previous box cannot be
    matched and stays None until initialization."""
    n_speakers = len(previous_boxes)
    matched = set()
    speaker_boxes: list[Optional[Sequence[float]]] = [None] * n_speakers
    for box in detected:
        ious = []
        for speaker in range(n_speakers):
            if speaker in matched or previous_boxes[speaker] is None:
                ious.append(-1.0)
            else:
                ious.append(bb_intersection_over_union(box, previous_boxes[speaker]))
        if ious and max(ious) > threshold:
            best = ious.index(max(ious))
            speaker_boxes[best] = box
            matched.add(best)
    return [
        speaker_boxes[speaker] if speaker_boxes[speaker] is not None else previous_boxes[speaker]
        for speaker in range(n_speakers)
    ]
