"""Light box tracker for the adaptive mode: normalized template matching.

Moves the target box by matching its previous crop inside a search window of
the next frame (downscaled grayscale). No weights, no downloads. Confidence is
the peak normalized correlation. It tracks translation only; scale changes
are handled by the periodic full detection. NOT validated on real footage yet.
"""
from __future__ import annotations

from typing import Optional, Sequence

_SCALE = 0.5  # work at half resolution for speed
_SEARCH_PAD = 0.5  # search window = box expanded by this fraction per side


def template_box_tracker(prev_frame, frame, box: Sequence[float]):
    """Return (new_box, confidence) or (None, 0.0) when the box leaves the frame."""
    import cv2  # lazy execution-time import

    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    bw, bh = x2 - x1, y2 - y1
    if bw < 8 or bh < 8:
        return None, 0.0
    cx1, cy1, cx2, cy2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    if cx2 - cx1 < 8 or cy2 - cy1 < 8:
        return None, 0.0
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    cur_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    template = prev_gray[cy1:cy2, cx1:cx2]
    padx, pady = int(bw * _SEARCH_PAD), int(bh * _SEARCH_PAD)
    sx1, sy1 = max(0, cx1 - padx), max(0, cy1 - pady)
    sx2, sy2 = min(width, cx2 + padx), min(height, cy2 + pady)
    search = cur_gray[sy1:sy2, sx1:sx2]
    small_t = cv2.resize(template, None, fx=_SCALE, fy=_SCALE)
    small_s = cv2.resize(search, None, fx=_SCALE, fy=_SCALE)
    if small_s.shape[0] < small_t.shape[0] or small_s.shape[1] < small_t.shape[1]:
        return None, 0.0
    result = cv2.matchTemplate(small_s, small_t, cv2.TM_CCOEFF_NORMED)
    _, peak, _, loc = cv2.minMaxLoc(result)
    dx = int(round(loc[0] / _SCALE)) + sx1 - cx1
    dy = int(round(loc[1] / _SCALE)) + sy1 - cy1
    new_box = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
    return new_box, float(max(0.0, peak))
