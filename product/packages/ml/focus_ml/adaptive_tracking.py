"""Adaptive face tracking for the target speaker (pure logic, no torch/cv2).

Reference cadence runs the full detector every ``detect_every`` frames and the
landmarker on every frame. This tracker instead runs a *light* box tracker
between full detections and re-runs the full detector only when needed:

- first frame, or the light tracker's confidence drops below ``min_confidence``
  or it returns no box;
- ``max_interval`` frames passed since the last full detection (stable face);
- ``edge_interval`` frames passed when the box touches the frame edge. Legacy
  measurements showed a head cut off at the top of the frame breaks when
  detection is thinned out, so those clips keep (near) reference cadence;
- while the target is uncertain or lost (re-detect every frame).

Identity guard: a full detection is accepted only if it overlaps the predicted
target box (IoU >= ``identity_iou_min``) and clearly beats the runner-up
(``ambiguity_margin``). Otherwise the last box is held and an "uncertain"
event is recorded; after ``max_hold_frames`` held frames a "lost" event is
recorded. The tracker never jumps to a distant face silently.

Detector and light tracker are injected callables, so unit tests use fake
boxes. Nothing here has been measured on a GPU; see docs/DEV1_ML.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from focus_ml.timing import frames_to_ms
from focus_ml.tracking import bb_intersection_over_union

Box = Sequence[float]
Detector = Callable[[object], list]
LightTracker = Callable[[object, object, Box], tuple[Optional[Box], float]]

MODE_FULL, MODE_LIGHT, MODE_HOLD = "full", "light", "hold"
STATE_TRACKING, STATE_UNCERTAIN, STATE_LOST = "tracking", "uncertain", "lost"


@dataclass(frozen=True)
class AdaptiveConfig:
    min_confidence: float = 0.6
    max_interval: int = 32
    edge_interval: int = 8
    edge_margin: float = 2.0
    identity_iou_min: float = 0.3
    ambiguity_margin: float = 0.1
    max_hold_frames: int = 12
    fps: int = 25

    def __post_init__(self):
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        if not 0.0 <= self.identity_iou_min <= 1.0:
            raise ValueError("identity_iou_min must be within [0, 1]")
        for name in ("max_interval", "edge_interval", "max_hold_frames", "fps"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")


@dataclass
class StepResult:
    frame_index: int
    box: Box
    mode: str
    state: str


def touches_edge(box: Box, frame_size: tuple[int, int], margin: float) -> bool:
    """True when the box reaches or leaves the frame (head cut at an edge)."""
    width, height = frame_size
    return (
        box[0] <= margin
        or box[1] <= margin
        or box[2] >= width - margin
        or box[3] >= height - margin
    )


class AdaptiveFaceTracker:
    def __init__(
        self,
        config: AdaptiveConfig,
        frame_size: tuple[int, int],
        detect: Detector,
        track: LightTracker,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.cfg = config
        self.frame_size = frame_size
        self._detect = detect
        self._track = track
        self._clock = clock
        self._box: Optional[Box] = None
        self._prev_frame = None
        self._since_detect = 0
        self._confidence = 0.0
        self._hold = 0
        self._state = STATE_TRACKING
        self._last_index = -1
        self._open_loss: Optional[dict] = None
        self.events: list[dict] = []
        self.loss_intervals: list[dict] = []
        self.counts = {"full_detects": 0, "light_tracks": 0, "hold_frames": 0}
        self.times = {"detect_s": 0.0, "track_s": 0.0}

    # ----- public API -----
    def start(self, frame, target_box: Box) -> StepResult:
        """Frame 0: the target box comes from first-frame candidate selection."""
        self._box = tuple(target_box)
        self._prev_frame = frame
        self._since_detect = 0
        self._confidence = 1.0
        self._last_index = 0
        return StepResult(0, self._box, MODE_FULL, STATE_TRACKING)

    def step(self, index: int, frame) -> StepResult:
        if self._box is None:
            raise RuntimeError("start() must be called before step()")
        self._last_index = index
        self._since_detect += 1
        mode = MODE_HOLD
        need_full = self._need_full_detect()
        if not need_full:
            started = self._clock()
            box, conf = self._track(self._prev_frame, frame, self._box)
            self.times["track_s"] += self._clock() - started
            self.counts["light_tracks"] += 1
            if box is None or conf < self.cfg.min_confidence:
                need_full = True  # same frame: re-detect immediately
            else:
                self._box, self._confidence = tuple(box), conf
                mode = MODE_LIGHT
        if need_full:
            mode = self._full_detect(index, frame)
        self._prev_frame = frame
        return StepResult(index, self._box, mode, self._state)

    def finalize(self) -> None:
        if self._open_loss is not None:
            self._close_loss(self._last_index, recovered=False)

    def report(self) -> dict:
        total = sum(self.counts.values())
        return {
            "mode": "adaptive",
            "frames": self._last_index + 1,
            **self.counts,
            "detect_s": round(self.times["detect_s"], 4),
            "track_s": round(self.times["track_s"], 4),
            "events": list(self.events),
            "loss_intervals": list(self.loss_intervals),
            "decision_total": total,
        }

    # ----- decisions -----
    def _interval(self) -> int:
        if touches_edge(self._box, self.frame_size, self.cfg.edge_margin):
            return min(self.cfg.edge_interval, self.cfg.max_interval)
        return self.cfg.max_interval

    def _need_full_detect(self) -> bool:
        if self._state != STATE_TRACKING:
            return True
        if self._confidence < self.cfg.min_confidence:
            return True
        return self._since_detect >= self._interval()

    def _full_detect(self, index: int, frame) -> str:
        started = self._clock()
        detections = self._detect(frame)
        self.times["detect_s"] += self._clock() - started
        self.counts["full_detects"] += 1
        accepted, reason = self._pick(detections)
        if accepted is not None:
            self._box = tuple(accepted)
            self._since_detect = 0
            self._confidence = 1.0
            if self._state != STATE_TRACKING:
                self._event(index, "reacquired")
                self._close_loss(index, recovered=True)
            self._hold = 0
            self._state = STATE_TRACKING
            return MODE_FULL
        # Not accepted: keep the last box, never jump.
        self._hold += 1
        self.counts["hold_frames"] += 1
        if self._open_loss is None:
            self._event(index, "uncertain", reason=reason)
            self._open_loss = {"start_frame": index, "reason": reason}
            self._state = STATE_UNCERTAIN
        if self._hold > self.cfg.max_hold_frames and self._state != STATE_LOST:
            self._event(index, "lost", reason=reason)
            self._state = STATE_LOST
        return MODE_HOLD

    def _pick(self, detections: Sequence[Box]) -> tuple[Optional[Box], str]:
        if not detections:
            return None, "no_detection"
        scored = sorted(
            ((bb_intersection_over_union(d, self._box), d) for d in detections),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_iou, best = scored[0]
        if best_iou < self.cfg.identity_iou_min:
            return None, "no_overlap_with_target"
        if len(scored) > 1 and best_iou - scored[1][0] < self.cfg.ambiguity_margin:
            return None, "ambiguous_between_faces"
        return best, ""

    # ----- bookkeeping -----
    def _event(self, index: int, kind: str, **extra) -> None:
        self.events.append(
            {"type": kind, "frame": index, "ms": frames_to_ms(index, self.cfg.fps), **extra}
        )

    def _close_loss(self, index: int, recovered: bool) -> None:
        loss = self._open_loss
        if loss is None:
            return
        self.loss_intervals.append(
            {
                "start_frame": loss["start_frame"],
                "end_frame": index,
                "start_ms": frames_to_ms(loss["start_frame"], self.cfg.fps),
                "end_ms": frames_to_ms(index, self.cfg.fps),
                "reason": loss["reason"],
                "recovered": recovered,
                "declared_lost": self._state == STATE_LOST,
            }
        )
        self._open_loss = None
