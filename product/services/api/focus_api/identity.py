"""Selection identity, identical math to ``focus_ml.identity.make_face_id``.

The API deliberately re-implements the tiny canonical hashing rule instead of
importing the ML package (the API process must stay torch-free and deployable on
its own). A test asserts the exact canonical string/hash so the two sides cannot
drift silently.

Rule (docs/02 + ROUND2_INTEGRATION_DECISIONS #5):
  sha256("v=<video_id>|t=<timestamp_ms>|b=<(x,y,w,h)>|s=<(width,height)>")
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Sequence


def make_face_id(
    video_id: str,
    timestamp_ms: int,
    bbox: Sequence[int],
    frame_size: Sequence[int],
) -> str:
    canonical = (
        f"v={video_id}|t={int(timestamp_ms)}|b={tuple(bbox)}|s={tuple(frame_size)}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bbox_to_wire(bbox: Sequence[int]) -> dict[str, int]:
    """Internal (x, y, w, h) tuple -> canonical wire {x,y,width,height}."""
    x, y, width, height = (int(v) for v in bbox)
    return {"x": x, "y": y, "width": width, "height": height}


def frame_size_to_wire(frame_size: Sequence[int]) -> dict[str, int]:
    width, height = (int(v) for v in frame_size)
    return {"width": width, "height": height}


def ordered_unique(items: Iterable) -> list:
    seen = set()
    out = []
    for item in items:
        key = getattr(item, "face_id", item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
