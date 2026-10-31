"""Speaker embedders behind one interface. Both return L2-normalised vectors.

* ``pyannote``  - the embedding model bundled in the community-1 pipeline.
* ``ecapa``     - SpeechBrain ECAPA-TDNN (spkrec-ecapa-voxceleb, Apache-2.0).
Voice characteristics only: no speech recognition anywhere.
"""
from __future__ import annotations

from typing import Protocol

import numpy as np

from ..errors import ModelUnavailableError
from .gpu import fp16_if_supported, release_gpu, resolve_device
from .preprocess import slice_samples
from .types import SAMPLE_RATE
from .weights import DIARIZER_REPO, ECAPA_REPO, SETUP_HINT, activate_site, require_weights

MIN_EMBED_S = 0.5
MAX_CHUNK_S = 6.0
EMBEDDERS = ("pyannote", "ecapa")


class Embedder(Protocol):
    name: str

    def load(self) -> None: ...
    def embed(self, samples: np.ndarray) -> np.ndarray: ...
    def unload(self) -> None: ...


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(-1)
    n = np.linalg.norm(v)
    if n == 0:
        raise ValueError("embedding has zero length")
    return v / n


def _need_torch():
    activate_site()
    try:
        import torch
        return torch
    except ImportError as exc:
        raise ModelUnavailableError(
            "the voice packages are not installed; " + SETUP_HINT, detail=str(exc)) from exc


class EcapaEmbedder:
    name = "ecapa"

    def __init__(self, device: str = "auto", home=None):
        self.device, self.home, self._model = resolve_device(device), home, None

    def load(self) -> None:
        if self._model is not None:
            return
        src = require_weights(ECAPA_REPO, self.home)
        _need_torch()
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
        self._model = EncoderClassifier.from_hparams(
            source=src, savedir=str(src / ".sb_run"), run_opts={"device": self.device},
            local_strategy=LocalStrategy.COPY,
            overrides={"pretrained_path": str(src)})   # never fetch from the Hub
        self._model.eval()

    def embed(self, samples: np.ndarray) -> np.ndarray:
        torch = _need_torch()
        self.load()
        wav = torch.from_numpy(np.asarray(samples, dtype=np.float32)).unsqueeze(0).to(self.device)
        with torch.inference_mode(), fp16_if_supported(self.device):
            out = self._model.encode_batch(wav)
        return _unit(out.float().cpu().numpy())

    def unload(self) -> None:
        self._model = None
        release_gpu()


class PyannoteEmbedder:
    name = "pyannote"

    def __init__(self, device: str = "auto", home=None):
        self.device, self.home, self._pipe = resolve_device(device), home, None

    def load(self) -> None:
        if self._pipe is None:
            from .diarizer import load_pyannote_pipeline
            self._pipe = load_pyannote_pipeline(self.device, self.home)

    def embed(self, samples: np.ndarray) -> np.ndarray:
        torch = _need_torch()
        self.load()
        wav = torch.from_numpy(np.asarray(samples, dtype=np.float32)).reshape(1, 1, -1).to(self.device)
        with torch.inference_mode(), fp16_if_supported(self.device):
            out = self._pipe._embedding(wav)
        return _unit(np.asarray(out.detach().cpu().numpy() if hasattr(out, "detach") else out))

    def unload(self) -> None:
        self._pipe = None
        release_gpu()


def build_embedder(name: str, device: str = "auto", home=None) -> Embedder:
    if name == "ecapa":
        return EcapaEmbedder(device, home)
    if name == "pyannote":
        return PyannoteEmbedder(device, home)
    raise ValueError(f"unknown embedder {name!r}; choose one of {EMBEDDERS}")


def embed_segments(embedder: Embedder, samples, segs, sr: int = SAMPLE_RATE,
                   min_s: float = MIN_EMBED_S, max_chunk_s: float = MAX_CHUNK_S):
    """Duration-weighted mean embedding over segments (long ones are chunked).
    Returns (unit vector or None when nothing was long enough, seconds used)."""
    acc, used = None, 0.0
    for seg in segs:
        n = max(1, int(np.ceil(seg.duration / max_chunk_s)))
        step = seg.duration / n
        for i in range(n):
            a, b = seg.start + i * step, seg.start + (i + 1) * step
            if b - a < min_s:
                continue
            e = embedder.embed(slice_samples(samples, type(seg)(a, b), sr)) * (b - a)
            acc = e if acc is None else acc + e
            used += b - a
    return (None if acc is None else _unit(acc)), used
