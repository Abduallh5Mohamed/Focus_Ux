"""Pure fps/audio alignment helpers, documented as ported from the legacy
``_separate`` stage (legacy_snapshot/tools/focus_runner.py lines 192-194)."""
from __future__ import annotations

FRAME_FPS: int = 25
SAMPLE_RATE: int = 16000


def frames_to_ms(frame_index: int, fps: int = FRAME_FPS) -> int:
    return int(round(frame_index * 1000.0 / fps))


def ms_to_frame_index(timestamp_ms: int, fps: int = FRAME_FPS) -> int:
    return int(round(timestamp_ms * fps / 1000.0))


def audio_window_to_roi(
    start_sample: int,
    end_sample: int,
    sample_rate: int = SAMPLE_RATE,
    fps: int = FRAME_FPS,
    roi_len: int = 0,
) -> tuple[int, int]:
    """Map an audio sample window to face-frame ROI indices exactly like the
    legacy mapping (``sf_ = int(start / sr * 25)``; ``ef = min(int(end / sr * 25),
    len(mr))``), with non-negative clamps."""
    start_frame = int(start_sample / sample_rate * fps)
    end_frame = min(int(end_sample / sample_rate * fps), roi_len)
    return max(0, start_frame), max(0, end_frame)


def normalize_timestamps_ms(values: list[int]) -> list[int]:
    """Clamp negatives to 0 and enforce monotonic non-decreasing order."""
    normalized: list[int] = []
    running_high = 0
    for value in values:
        clamped = max(0, int(value))
        monotonic = max(clamped, running_high)
        normalized.append(monotonic)
        running_high = monotonic
    return normalized


def duration_ms_from_samples(n_samples: int, sample_rate: int = SAMPLE_RATE) -> int:
    return int(round(n_samples / sample_rate * 1000.0))
