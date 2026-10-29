"""Adaptive tracker decisions with fake boxes (test-only shapes)."""
import pytest

from focus_ml.adaptive_tracking import AdaptiveConfig, AdaptiveFaceTracker
from focus_ml.config import AdapterConfig

FRAME = (640, 480)
CENTER = (200.0, 100.0, 300.0, 220.0)  # interior box, does not touch an edge


class Fakes:
    def __init__(self, detections=None, track=None):
        self.detections = detections or (lambda i: [CENTER])
        self.track_fn = track or (lambda box, i: (box, 0.95))
        self.frame = 0
        self.detect_calls = []
        self.track_calls = 0

    def detect(self, frame):
        self.detect_calls.append(frame)
        return self.detections(frame)

    def track(self, prev, frame, box):
        self.track_calls += 1
        return self.track_fn(box, frame)


def make(fakes, **cfg):
    t = AdaptiveFaceTracker(AdaptiveConfig(**cfg), FRAME, fakes.detect, fakes.track)
    t.start(0, CENTER)
    return t


def run(t, n):
    return [t.step(i, i) for i in range(1, n)]


def test_stable_face_uses_light_tracking_between_sparse_detections():
    f = Fakes()
    t = make(f, max_interval=10)
    steps = run(t, 31)
    rep = t.report()
    assert rep["full_detects"] == 3            # frames 10, 20, 30
    assert rep["light_tracks"] == 27
    assert [s.mode for s in steps].count("full") == 3
    assert rep["events"] == [] and rep["loss_intervals"] == []


def test_edge_touching_box_keeps_reference_like_cadence():
    edge_box = (200.0, -20.0, 300.0, 100.0)  # head cut at the top of the frame
    f = Fakes(detections=lambda i: [edge_box], track=lambda box, i: (box, 0.95))
    t = AdaptiveFaceTracker(AdaptiveConfig(max_interval=32, edge_interval=8), FRAME, f.detect, f.track)
    t.start(0, edge_box)
    run(t, 33)
    assert t.report()["full_detects"] == 4     # every 8 frames, not every 32


def test_low_confidence_redetects_on_the_same_frame():
    f = Fakes(track=lambda box, i: (box, 0.2 if i == 5 else 0.95))
    t = make(f, max_interval=100)
    steps = run(t, 8)
    assert steps[4].mode == "full" and steps[4].frame_index == 5
    assert t.report()["full_detects"] == 1


def test_light_tracker_returning_no_box_triggers_full_detect():
    f = Fakes(track=lambda box, i: (None, 0.0))
    t = make(f, max_interval=100)
    assert run(t, 4)[0].mode == "full"


def test_identity_never_jumps_to_a_distant_face():
    other = (450.0, 100.0, 550.0, 220.0)
    f = Fakes(detections=lambda i: [other], track=lambda box, i: (box, 0.95))
    t = make(f, max_interval=4, max_hold_frames=3)
    steps = run(t, 20)
    assert all(tuple(s.box) == CENTER for s in steps)       # last known box held
    rep = t.report()
    kinds = [e["type"] for e in rep["events"]]
    assert kinds[0] == "uncertain" and "lost" in kinds
    assert rep["events"][0]["reason"] == "no_overlap_with_target"
    assert rep["events"][0]["ms"] == 160                    # frame 4 at 25 fps


def test_ambiguous_overlapping_faces_are_not_silently_chosen():
    a = (200.0, 100.0, 300.0, 220.0)
    b = (205.0, 100.0, 305.0, 220.0)                       # nearly the same overlap
    f = Fakes(detections=lambda i: [a, b])
    t = make(f, max_interval=3, ambiguity_margin=0.2)
    run(t, 5)
    assert t.report()["events"][0]["reason"] == "ambiguous_between_faces"


def test_reacquire_closes_loss_interval_with_timing():
    state = {"visible": False}
    f = Fakes(detections=lambda i: [CENTER] if (i < 4 or i >= 12) else [],
              track=lambda box, i: (box, 0.95))
    t = make(f, max_interval=4, max_hold_frames=3)
    run(t, 16)
    t.finalize()
    rep = t.report()
    kinds = [e["type"] for e in rep["events"]]
    assert kinds == ["uncertain", "lost", "reacquired"]
    interval = rep["loss_intervals"][0]
    assert interval["recovered"] and interval["declared_lost"]
    assert interval["start_frame"] == 4 and interval["end_frame"] == 12
    assert (interval["start_ms"], interval["end_ms"]) == (160, 480)


def test_unrecovered_loss_is_closed_at_finalize():
    f = Fakes(detections=lambda i: [])
    t = make(f, max_interval=2, max_hold_frames=2)
    run(t, 10)
    t.finalize()
    iv = t.report()["loss_intervals"][0]
    assert iv["recovered"] is False and iv["end_frame"] == 9


def test_stage_timings_use_the_injected_clock():
    ticks = iter(range(0, 1000))
    f = Fakes()
    t = AdaptiveFaceTracker(AdaptiveConfig(max_interval=5), FRAME, f.detect, f.track,
                            clock=lambda: float(next(ticks)))
    t.start(0, CENTER)
    run(t, 11)
    rep = t.report()
    assert rep["detect_s"] == rep["full_detects"] and rep["track_s"] == rep["light_tracks"]


def test_config_validation_and_default_mode_stays_reference():
    assert AdapterConfig().tracking_mode == "reference"
    assert AdapterConfig.from_env({}).tracking_mode == "reference"
    assert AdapterConfig.from_env({"FOCUS_TRACKING_MODE": "adaptive"}).tracking_mode == "adaptive"
    with pytest.raises(ValueError):
        AdapterConfig(tracking_mode="turbo")
    with pytest.raises(ValueError):
        AdaptiveConfig(max_interval=0)
