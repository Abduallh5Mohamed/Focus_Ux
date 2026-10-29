"""Timing alignment helpers, checks against the legacy int mapping."""
import pytest

from focus_ml.timing import (
    FRAME_FPS,
    SAMPLE_RATE,
    audio_window_to_roi,
    duration_ms_from_samples,
    frames_to_ms,
    ms_to_frame_index,
    normalize_timestamps_ms,
)


def test_constants():
    assert FRAME_FPS == 25
    assert SAMPLE_RATE == 16000


def test_audio_window_to_roi_legacy_int_mapping():
    assert audio_window_to_roi(32000, 64000, sample_rate=16000, fps=25, roi_len=1000) == (50, 100)
    assert audio_window_to_roi(0, 16000, sample_rate=16000, fps=25, roi_len=1000) == (0, 25)


def test_audio_window_to_roi_end_clamped_to_roi_len():
    assert audio_window_to_roi(32000, 64000, sample_rate=16000, roi_len=75) == (50, 75)


def test_audio_window_to_roi_negative_clamps_to_zero():
    assert audio_window_to_roi(-3200, 640, sample_rate=16000, roi_len=10) == (0, 1)


def test_frames_to_ms_and_index_roundtrip():
    for index in range(0, 250):
        assert ms_to_frame_index(frames_to_ms(index)) == index
    assert frames_to_ms(0) == 0
    assert frames_to_ms(25) == 1000


def test_normalize_timestamps_ms_monotonic_and_clamped():
    assert normalize_timestamps_ms([100, -5, 50, 200, 200]) == [100, 100, 100, 200, 200]
    assert normalize_timestamps_ms([]) == []
    assert normalize_timestamps_ms([-10, -3]) == [0, 0]


def test_duration_ms_from_samples():
    assert duration_ms_from_samples(16000) == 1000
    assert duration_ms_from_samples(8001) == 500


def test_duration_ms_from_samples_non_default_sample_rate():
    assert duration_ms_from_samples(48000, 48000) == 1000
    assert duration_ms_from_samples(22050, 44100) == 500
