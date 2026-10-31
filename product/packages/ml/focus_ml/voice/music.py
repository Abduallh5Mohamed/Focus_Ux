"""Optional music separation (Demucs) as a pre-cleaner for the voice mask.

Why this exists
---------------
The mask baselines (``GatedBaseline`` / ``DuckedBaseline``) only decide *when*
audio passes; they cannot take a music bed out from under the voice. On a real
job that bed was still there at full level under every spoken word. A DSP-only
attempt (REPET / median filtering across time) removed 0.2-0.5 dB on that same
file, so it was rejected on evidence and is not wired in
(``runtime/analysis/repet.py``).

Demucs' ``vocals`` stem is a trained separator and is the only thing in this
repository that can actually remove the bed. It is OPT-IN:

    FOCUS_VOICE_EXTRACTOR=music
    FOCUS_DEMUCS_PYTHON=<path to the demucs environment python>
    FOCUS_DEMUCS_DIR=<weights dir>          (default <project>/model-assets/demucs)

Rules kept from the rest of the codebase
---------------------------------------
* No import-time side effects and no torch in the product environment: the
  separator shells out to ``product/tools/demucs_separate.py``.
* Nothing is downloaded at run time. Missing weights raise
  ``ModelUnavailableError`` pointing at ``product/tools/demucs_setup.py``.
* If the separator fails, the extraction fails. It never silently falls back
  to the mask, so a result can never be mistaken for music-free audio when it
  is not.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from ..errors import ModelUnavailableError, ProcessingError
from ..isolation_engines import fit_samples, read_wav
from .extractor import DuckedBaseline, target_mask
from .types import SAMPLE_RATE

SETUP_HINT = ("run product/tools/demucs_setup.py once inside the Demucs environment "
              "and pass --download to fetch the weights")
DEFAULT_MODEL = "htdemucs"


def project_root() -> Path:
    """Repository root (…/focus_ml/voice/music.py -> parents[5])."""
    return Path(__file__).resolve().parents[5]


def demucs_dir(env=None) -> Path:
    source = os.environ if env is None else env
    return Path(source.get("FOCUS_DEMUCS_DIR") or (project_root() / "model-assets" / "demucs"))


def demucs_python(env=None) -> str | None:
    source = os.environ if env is None else env
    return source.get("FOCUS_DEMUCS_PYTHON") or None


def _write_pcm16(path: str, samples, rate: int) -> None:
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


class DemucsSeparator:
    """Mono vocals estimate for a mono 16 kHz signal, via a subprocess."""

    name = "demucs"

    def __init__(self, python: str | None = None, model: str = DEFAULT_MODEL,
                 device: str | None = None, timeout_s: float = 1800.0, env=None):
        source = os.environ if env is None else env
        self.python = python or demucs_python(source)
        self.model = model or source.get("FOCUS_DEMUCS_MODEL") or DEFAULT_MODEL
        self.device = device or source.get("FOCUS_DEMUCS_DEVICE") or "cpu"
        self.timeout_s = timeout_s
        self.root = project_root()

    # -- readiness ---------------------------------------------------------
    def check_ready(self) -> None:
        if not self.python or not Path(self.python).is_file():
            raise ModelUnavailableError(
                "the music separator is not installed on this computer; " + SETUP_HINT,
                retryable=False, detail=f"FOCUS_DEMUCS_PYTHON={self.python!r}")
        script = self.root / "product" / "tools" / "demucs_separate.py"
        if not script.is_file():
            raise ModelUnavailableError(
                "the music separator runner is missing from this checkout",
                retryable=False, detail=str(script))

    # -- work --------------------------------------------------------------
    def separate(self, samples, rate: int = SAMPLE_RATE):
        """Returns the vocals estimate at ``rate`` with the input's length."""
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.check_ready()
        script = self.root / "product" / "tools" / "demucs_separate.py"
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "mix.wav")
            dst = os.path.join(tmp, "vocals.wav")
            _write_pcm16(src, x, rate)
            command = [self.python, str(script), src, dst,
                       "--model", self.model, "--device", self.device]
            try:
                done = subprocess.run(command, capture_output=True, text=True,
                                      timeout=self.timeout_s)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ProcessingError("the music separator could not run",
                                      retryable=True, detail=str(exc)) from exc
            if done.returncode != 0 or not os.path.isfile(dst):
                tail = (done.stderr or "").strip()[-600:]
                if done.returncode == 4:
                    raise ModelUnavailableError(
                        "the music separator weights are missing; " + SETUP_HINT,
                        retryable=False, detail=tail)
                raise ProcessingError("the music separator failed",
                                      retryable=True, detail=tail)
            vocals, sr = read_wav(dst)
        return fit_samples(vocals, sr, rate, len(x))


class MusicSuppressedBaseline:
    """Voice without the bed inside target speech, ducked bed elsewhere.

    ``out = gate * vocals + (1 - gate) * floor * (mix - vocals)``

    ``gate`` is 1 inside a target region and 0 outside (with the usual ramps).
    Inside, the result is the Demucs vocals stem, so the bed is gone. Outside,
    the result is the estimated accompaniment ducked to ``floor`` - the
    timeline stays continuous instead of going silent or pumping.
    """

    name = "music_suppressed"

    def __init__(self, floor_db: float = -12.0, fade_ms: float = 30.0,
                 bridge_ms: float = 250.0, separator=None):
        self.ducked = DuckedBaseline(floor_db=floor_db, fade_ms=fade_ms, bridge_ms=bridge_ms)
        self.separator = separator or DemucsSeparator()

    def params(self) -> dict:
        return {**self.ducked.params(), "separator": getattr(self.separator, "name", "custom"),
                "model": getattr(self.separator, "model", None)}

    def check_ready(self) -> None:
        if hasattr(self.separator, "check_ready"):
            self.separator.check_ready()

    def extract(self, samples, regions):
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        vocals = np.asarray(self.separator.separate(x), dtype=np.float32)
        if len(vocals) != len(x):
            vocals = fit_samples(vocals, SAMPLE_RATE, SAMPLE_RATE, len(x))
        accompaniment = x - vocals
        gate = target_mask(len(x), regions, fade_ms=self.ducked.fade_ms, floor=0.0,
                           bridge_ms=self.ducked.bridge_ms)
        out = gate * vocals + (1.0 - gate) * self.ducked.floor * accompaniment
        return fit_samples(out, SAMPLE_RATE, SAMPLE_RATE, len(x))


def build_music_extractor(env=None):
    """Factory used by ``extractor.build_extractor`` for ``music``."""
    source = os.environ if env is None else env
    from .extractor import _env_float, DEFAULT_BRIDGE_MS, DEFAULT_FADE_MS, DEFAULT_FLOOR_DB

    return MusicSuppressedBaseline(
        floor_db=_env_float(source, "FOCUS_VOICE_FLOOR_DB", DEFAULT_FLOOR_DB),
        fade_ms=_env_float(source, "FOCUS_VOICE_FADE_MS", DEFAULT_FADE_MS),
        bridge_ms=_env_float(source, "FOCUS_VOICE_BRIDGE_MS", DEFAULT_BRIDGE_MS),
        separator=DemucsSeparator(env=source),
    )
