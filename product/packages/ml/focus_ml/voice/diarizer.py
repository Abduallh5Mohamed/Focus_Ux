"""Diarization + VAD with pyannote ``speaker-diarization-community-1``.

The pipeline gives who-spoke-when including overlapping speech; speech
regions (VAD) are the union of the turns. Results are cached per audio file
(content hash + model id) so nothing is computed twice.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

import numpy as np

from ..errors import ModelUnavailableError
from .gpu import fp16_if_supported, release_gpu, resolve_device
from .segments import merge, overlaps_from_turns
from .types import SAMPLE_RATE, Diarization, Segment
from .weights import DIARIZER_REPO, SETUP_HINT, activate_site, require_weights


class Diarizer(Protocol):
    model_id: str

    def diarize(self, samples: np.ndarray) -> Diarization: ...
    def unload(self) -> None: ...


def from_turns(turns) -> Diarization:
    turns = [Segment(float(t.start), float(t.end), str(t.speaker)) for t in turns if t.end > t.start]
    return Diarization(sorted(turns, key=lambda t: (t.start, t.end)),
                       overlaps_from_turns(turns), merge(turns))


def load_pyannote_pipeline(device: str, home=None):
    src = require_weights(DIARIZER_REPO, home)
    activate_site()
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise ModelUnavailableError(
            "the voice packages are not installed; " + SETUP_HINT, detail=str(exc)) from exc
    pipe = Pipeline.from_pretrained(str(src))
    if pipe is None:
        raise ModelUnavailableError("the diarization weights could not be loaded; " + SETUP_HINT)
    return pipe.to(torch.device(device))


class PyannoteDiarizer:
    model_id = DIARIZER_REPO

    def __init__(self, device: str = "auto", home=None, num_speakers=None):
        self.device, self.home, self.num_speakers = resolve_device(device), home, num_speakers
        self._pipe = None

    def diarize(self, samples: np.ndarray) -> Diarization:
        import torch
        if self._pipe is None:
            self._pipe = load_pyannote_pipeline(self.device, self.home)
        wav = torch.from_numpy(np.asarray(samples, dtype=np.float32)).reshape(1, -1)
        kwargs = {"num_speakers": self.num_speakers} if self.num_speakers else {}
        with torch.inference_mode(), fp16_if_supported(self.device):
            out = self._pipe({"waveform": wav, "sample_rate": SAMPLE_RATE}, **kwargs)
        annotation = getattr(out, "speaker_diarization", out)
        turns = [Segment(t.start, t.end, str(spk))
                 for t, _, spk in annotation.itertracks(yield_label=True)]
        return from_turns(turns)

    def unload(self) -> None:
        self._pipe = None
        release_gpu()


class CachedDiarizer:
    """Wraps any diarizer; one JSON per (audio hash, model id)."""

    def __init__(self, inner: Diarizer, cache_dir: str | Path):
        self.inner, self.cache_dir = inner, Path(cache_dir)
        self.model_id = inner.model_id
        self.hits = 0

    def _path(self, samples) -> Path:
        h = hashlib.sha256(np.asarray(samples, dtype=np.float32).tobytes())
        h.update(self.model_id.encode())
        return self.cache_dir / f"diarization-{h.hexdigest()[:24]}.json"

    def diarize(self, samples: np.ndarray) -> Diarization:
        p = self._path(samples)
        if p.is_file():
            self.hits += 1
            return Diarization.from_dict(json.loads(p.read_text("utf-8")))
        result = self.inner.diarize(samples)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result.as_dict()), encoding="utf-8")
        return result

    def unload(self) -> None:
        self.inner.unload()
