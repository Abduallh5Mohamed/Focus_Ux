"""Pure interval helpers (seconds)."""
from __future__ import annotations

from .types import Segment


def merge(segs, gap: float = 0.0) -> list[Segment]:
    out: list[Segment] = []
    for s in sorted((x for x in segs if x.end > x.start), key=lambda x: x.start):
        if out and s.start <= out[-1].end + gap:
            out[-1] = Segment(out[-1].start, max(out[-1].end, s.end))
        else:
            out.append(Segment(s.start, s.end))
    return out


def subtract(segs, cuts) -> list[Segment]:
    """``segs`` minus the union of ``cuts`` (speaker label kept)."""
    cuts = merge(cuts)
    out = []
    for s in segs:
        cur = s.start
        for c in cuts:
            if c.end <= cur or c.start >= s.end:
                continue
            if c.start > cur:
                out.append(Segment(cur, c.start, s.speaker))
            cur = max(cur, c.end)
        if cur < s.end:
            out.append(Segment(cur, s.end, s.speaker))
    return [x for x in out if x.duration > 0]


def intersect(a, b) -> list[Segment]:
    out = []
    b = merge(b)
    for s in merge(a):
        for c in b:
            lo, hi = max(s.start, c.start), min(s.end, c.end)
            if hi > lo:
                out.append(Segment(lo, hi))
    return out


def total(segs) -> float:
    return sum(s.duration for s in merge(segs))


def overlaps_from_turns(turns) -> list[Segment]:
    """Spans covered by at least two different speakers."""
    pts = sorted({t for s in turns for t in (s.start, s.end)})
    out = []
    for lo, hi in zip(pts, pts[1:]):
        active = {s.speaker for s in turns if s.start <= lo and s.end >= hi}
        if len(active) >= 2:
            out.append(Segment(lo, hi))
    return merge(out)
