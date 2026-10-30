"""Canonical audio: 16 kHz mono float32 from any WAV or video file.

Audio only: a video container is read for its audio track and nothing else.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..errors import MediaError, ProcessingError
from ..isolation_engines import _ffmpeg, read_wav
from .types import SAMPLE_RATE


# One ffmpeg decode per file per process. A stage pipeline (analyze, enroll,
# isolate) otherwise decodes the same audio up to three times. The key includes
# a content signature, so a temp file replaced by different audio never hits.
_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
CACHE_MAX_BYTES = 256 * 1024 * 1024
decode_count = 0   # real ffmpeg decodes since import (tests and profiling read this)


def _signature(path: str) -> tuple:
    st = os.stat(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if st.st_size > 131072:
            f.seek(-65536, os.SEEK_END)
            h.update(f.read(65536))
    return (os.path.abspath(path), st.st_size, st.st_mtime_ns, h.hexdigest())


def clear_decode_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def load_canonical(path: str) -> np.ndarray:
    """Cached decode. The returned array is read-only and shared; copy before editing."""
    if not os.path.isfile(path):
        raise MediaError("media file not found", detail=path)
    key = _signature(path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None:
            _CACHE.move_to_end(key)
            return hit
    samples = _decode(path)
    samples.setflags(write=False)
    with _CACHE_LOCK:
        _CACHE[key] = samples
        while len(_CACHE) > 1 and sum(a.nbytes for a in _CACHE.values()) > CACHE_MAX_BYTES:
            _CACHE.popitem(last=False)
    return samples


def prefetch_decoded(paths):
    """Yield (path, samples), decoding the NEXT file on a CPU thread while the
    caller's GPU work runs on the current one. Order and results are identical
    to calling load_canonical in a loop."""
    paths = list(paths)
    if not paths:
        return
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(load_canonical, paths[0])
        for i, path in enumerate(paths):
            samples = pending.result()
            if i + 1 < len(paths):
                pending = pool.submit(load_canonical, paths[i + 1])
            yield path, samples


def _decode(path: str) -> np.ndarray:
    global decode_count
    decode_count += 1
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
