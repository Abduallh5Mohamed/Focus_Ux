"""Canonical audio: 16 kHz mono float32 from any WAV or video file.

Audio only: a video container is read for its audio track and nothing else.
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import numpy as np

from ..errors import MediaError, ProcessingError
from ..isolation_engines import _ffmpeg, read_wav
from .types import SAMPLE_RATE


def load_canonical(path: str) -> np.ndarray:
    if not os.path.isfile(path):
        raise MediaError("media file not found", detail=path)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "audio.wav")
        try:
            done = subprocess.run(
                [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-vn",
                 "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", out],
                capture_output=True, text=True)
        except OSError as exc:
            raise ProcessingError("audio tool unavailable", detail=str(exc)) from exc
        if done.returncode != 0 or not os.path.isfile(out):
            raise MediaError("the file has no readable audio", detail=done.stderr)
        samples, sr = read_wav(out)
    if sr != SAMPLE_RATE or len(samples) == 0:
        raise MediaError("the file has no readable audio")
    return samples.astype(np.float32)


def slice_samples(samples, seg, sr: int = SAMPLE_RATE):
    return samples[int(round(seg.start * sr)):int(round(seg.end * sr))]
