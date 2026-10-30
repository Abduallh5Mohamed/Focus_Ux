"""Sample-exact output windows with enough visual context for a codec tail.

AAC decoding can append a few audio samples after the last video frame. Such a
tail must not be sent to Dolphin with an empty/too-short mouth sequence. Borrow
the preceding window as inference context and write only the unproduced tail.
Nothing is dropped, repeated in the output timeline, or stretched.
"""
from dataclasses import dataclass

from .timing import audio_window_to_roi


@dataclass(frozen=True)
class SeparationWindow:
    output_start: int
    output_end: int
    model_start: int
    roi_start: int
    roi_end: int

    @property
    def output_offset(self) -> int:
        return self.output_start - self.model_start


def separation_windows(n_samples, window_samples, roi_len, sample_rate, fps, *, min_visual_frames=7):
    """Plan contiguous writes; undersized tails borrow context from the past.

    Seven frames is a conservative lower bound for the visual front-end. Clips
    with less context fail explicitly instead of inventing mouth frames.
    """
    if min(n_samples, window_samples, roi_len, sample_rate, fps, min_visual_frames) <= 0:
        raise ValueError("audio and mouth context must be nonempty")
    for start in range(0, n_samples, window_samples):
        end = min(start + window_samples, n_samples)
        model_start = start
        rs, re = audio_window_to_roi(start, end, sample_rate, fps, roi_len=roi_len)
        if re - rs < min_visual_frames:
            model_start = max(0, end - window_samples)
            rs, re = audio_window_to_roi(model_start, end, sample_rate, fps, roi_len=roi_len)
        if re - rs < min_visual_frames:
            raise ValueError("insufficient mouth frames for the audio window")
        yield SeparationWindow(start, end, model_start, rs, re)
