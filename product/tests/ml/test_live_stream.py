"""Scheduler tests with a fake engine: they prove windowing/ordering, not isolation quality."""
import numpy as np
import pytest

from focus_ml.live_stream import LiveStreamSession, StreamConfig
from fake_stream_backend import FakeBackend, pcm

SR = 16000


def feed(session, seconds, tone=True, step_s=0.2, start_s=0.0):
    parts = []
    t = np.arange(int(seconds * SR)) + int(start_s * SR)
    sig = 0.4 * np.sin(2 * np.pi * 220 * t / SR) if tone else np.zeros(len(t))
    for a in range(0, len(t), int(step_s * SR)):
        chunk = sig[a:a + int(step_s * SR)]
        session.push_audio(int(t[a]), pcm(chunk))
        for f in range(int(step_s * 25)):
            session.push_frame((t[a] / SR + f / 25) * 1000, b"j")
        parts += session.step()
    return parts, sig


def test_config_rejects_unfittable_crossfade():
    with pytest.raises(ValueError):
        StreamConfig(lookahead_s=0.01, crossfade_ms=50)


def test_parts_are_contiguous_ordered_and_cover_the_stream():
    b = FakeBackend()
    s = LiveStreamSession(b)
    s.select(0, b"j", [0, 0, 1, 1])
    parts, sig = feed(s, 6.0)
    parts += s.flush()
    assert parts[0].start_sample == 0
    for prev, cur in zip(parts, parts[1:]):
        assert cur.start_sample == prev.start_sample + prev.samples
    assert sum(p.samples for p in parts) == len(sig)
    assert {p.state for p in parts} == {"ready"}
    assert all(w[0] <= 4 * SR + 640 for w in b.windows)  # sliding window, never the whole stream
    out = np.frombuffer(b"".join(p.pcm for p in parts), dtype="<i2") / 32768
    assert np.allclose(out, sig * 0.5, atol=2e-3)  # crossfade of equal estimates is transparent
    assert s.stats.as_dict()["audio_gap_samples"] == 0


def test_emits_only_after_lookahead_and_tracking_lag():
    b = FakeBackend()
    s = LiveStreamSession(b)
    s.select(0, b"j", [0, 0, 1, 1])
    parts, _ = feed(s, 0.6)  # hop 0.5 + lookahead 0.25 not yet available
    assert parts == []
    parts, _ = feed(s, 0.3, start_s=0.6)
    assert len(parts) == 1 and parts[0].samples == SR // 2


def test_gap_and_duplicate_audio_are_counted_not_hidden():
    s = LiveStreamSession(FakeBackend())
    s.select(0, b"j", [0, 0, 1, 1])
    s.push_audio(0, pcm(np.ones(1000) * 0.1))
    s.push_audio(500, pcm(np.ones(1000) * 0.1))   # overlaps 500
    s.push_audio(3000, pcm(np.ones(100) * 0.1))   # leaves a 1500 gap
    st = s.stats
    assert (st.audio_duplicate_samples, st.audio_gap_samples) == (500, 1500)


def test_lost_target_is_explicit_and_never_isolated():
    b = FakeBackend(lost_from=50)  # lost from 2.0 s
    s = LiveStreamSession(b)
    s.select(0, b"j", [0, 0, 1, 1])
    parts, _ = feed(s, 5.0)
    states = [p.state for p in parts]
    assert states[0] == "ready" and states[-1] == "target_lost"
    assert all(not p.pcm for p in parts if p.state != "ready")


def test_engine_failure_is_a_failed_part():
    b = FakeBackend()
    b.isolate = lambda *a: (_ for _ in ()).throw(RuntimeError("oom"))
    s = LiveStreamSession(b)
    s.select(0, b"j", [0, 0, 1, 1])
    parts, _ = feed(s, 2.0)
    assert parts and parts[0].state == "failed" and parts[0].error == "RuntimeError"


def test_listening_starts_at_selection_and_target_cannot_change():
    b = FakeBackend()
    s = LiveStreamSession(b)
    s.push_audio(0, pcm(np.zeros(SR)))
    s.select(25, b"j", [0, 0, 1, 1])
    with pytest.raises(RuntimeError):
        s.select(30, b"j", [0, 0, 1, 1])
    feed(s, 3.0, start_s=1.0)
    parts = s.flush()
    assert parts[0].start_sample >= SR
