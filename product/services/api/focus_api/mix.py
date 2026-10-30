"""Voice-mix math and rendering (stages E and F of the product plan).

Works only on the isolated WAV every engine already returns plus the original
audio of the stored video. Nothing here needs a GPU or the worker.

Pipeline
--------
1. Decode the original audio and the isolated WAV with ffmpeg to mono float32
   at one working rate (``WORK_RATE``).
2. Align the isolated voice to the original: apply the job's
   ``source_offset_ms`` (isolated sample 0 sits at original time ``offset``),
   then refine with a bounded cross-correlation search (``MAX_LAG_MS``).
3. Level match by least squares: ``gain = <o, i> / <i, i>``.
4. ``others = original - gain * voice``. This is only meaningful when the
   isolated audio really is a component of the original, so a reliability
   check (correlation, coverage, non-silence) decides whether the "other
   voices" track may be used at all. Unreliable => unavailable, never guessed.
5. ``mix = voice_level * voice + others_level * others``, optional plain
   high-pass / low-pass filtering (Butterworth magnitude response, 2nd order;
   NOT an AI model), then a look-ahead peak limiter.
"""
from __future__ import annotations

import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

WORK_RATE = 48_000
MAX_LAG_MS = 200.0
MIN_CORRELATION = 0.3
MIN_COVERAGE = 0.9
MIN_VOICE_RMS = 1e-4
LIMITER_CEILING = 0.98  # about -0.18 dBFS
LIMITER_LOOKAHEAD_MS = 5.0
DECODE_TIMEOUT_S = 60.0

NOISE_MODES = ("off", "light", "strong")
# (high-pass Hz, low-pass Hz or None). Same corner frequencies are used by the
# browser preview (BiquadFilterNode, Q = 1/sqrt(2)).
NOISE_FILTERS: dict[str, tuple[float | None, float | None]] = {
    "off": (None, None),
    "light": (100.0, None),
    "strong": (150.0, 6000.0),
}
VOICE_LEVEL_MAX = 2.0
OTHERS_LEVEL_MAX = 1.0


class MixError(Exception):
    """User-safe failure; ``code`` maps to an API error."""

    def __init__(self, message: str, code: str = "PROCESSING_FAILED"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class MixSettings:
    voice_level: float = 1.0
    others_level: float = 0.25
    noise_reduction: str = "off"

    def validated(self) -> "MixSettings":
        if not (0.0 <= self.voice_level <= VOICE_LEVEL_MAX):
            raise MixError(f"voice_level must be between 0 and {VOICE_LEVEL_MAX:g}", "INVALID_REQUEST")
        if not (0.0 <= self.others_level <= OTHERS_LEVEL_MAX):
            raise MixError(f"others_level must be between 0 and {OTHERS_LEVEL_MAX:g}", "INVALID_REQUEST")
        if self.noise_reduction not in NOISE_MODES:
            raise MixError("noise_reduction must be off, light or strong", "INVALID_REQUEST")
        return self


@dataclass(frozen=True)
class Alignment:
    """Result of aligning the isolated voice to the original timeline."""

    voice: np.ndarray        # level-matched voice on the original timeline
    others: np.ndarray       # original - voice
    gain: float
    lag_ms: float            # total shift applied (offset + refinement)
    correlation: float
    coverage: float
    reliable: bool
    reason: str | None       # why unreliable (English, for logs/tests)


# -- decoding ---------------------------------------------------------------

def decode_mono(path: Path, *, ffmpeg: str = "ffmpeg", rate: int = WORK_RATE) -> np.ndarray:
    """Decode the first audio stream to mono float32. Empty array if none."""
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
        "-vn", "-map", "0:a:0?", "-af", "aresample=async=1:first_pts=0",
        "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1",
    ]
    try:
        done = subprocess.run(command, capture_output=True, timeout=DECODE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MixError("audio decoder could not run") from exc
    if done.returncode != 0:
        raise MixError("audio could not be decoded")
    usable = len(done.stdout) - len(done.stdout) % 4
    return np.frombuffer(done.stdout[:usable], dtype="<f4").astype(np.float32)


def fit_length(signal: np.ndarray, length: int) -> np.ndarray:
    if len(signal) >= length:
        return signal[:length].astype(np.float32, copy=False)
    return np.concatenate([signal, np.zeros(length - len(signal), dtype=np.float32)])


# -- alignment --------------------------------------------------------------

def _shift(signal: np.ndarray, shift: int, length: int) -> np.ndarray:
    """Place ``signal`` so that its sample 0 lands at ``shift`` (may be negative)."""
    out = np.zeros(length, dtype=np.float64)
    src_start = max(0, -shift)
    dst_start = max(0, shift)
    count = min(len(signal) - src_start, length - dst_start)
    if count > 0:
        out[dst_start:dst_start + count] = signal[src_start:src_start + count]
    return out


def _best_lag(original: np.ndarray, voice: np.ndarray, center: int, radius: int) -> int:
    """Lag in [center-radius, center+radius] maximising correlation of voice vs original."""
    n = len(original) + len(voice)
    size = 1 << (n - 1).bit_length()
    spec = np.fft.rfft(original, size) * np.conj(np.fft.rfft(voice, size))
    corr = np.fft.irfft(spec, size)  # corr[k] = sum_t original[t + k] * voice[t]
    best, best_val = center, -np.inf
    for lag in range(center - radius, center + radius + 1):
        value = corr[lag % size]
        if value > best_val:
            best, best_val = lag, value
    return best


def align(
    original: np.ndarray,
    isolated: np.ndarray,
    *,
    offset_ms: float = 0.0,
    rate: int = WORK_RATE,
    max_lag_ms: float = MAX_LAG_MS,
) -> Alignment:
    """Align, level-match and derive the residual. Never raises for bad input;
    returns ``reliable=False`` with a reason instead."""
    length = len(original)
    zeros = np.zeros(length, dtype=np.float32)

    def unreliable(reason: str, lag_ms: float = 0.0, corr: float = 0.0, cov: float = 0.0,
                   voice: np.ndarray | None = None) -> Alignment:
        # The isolated voice stays usable on its own (placed by the job offset,
        # unscaled); only the subtraction-based "others" track is withheld.
        return Alignment(zeros if voice is None else voice.astype(np.float32), zeros,
                         1.0 if voice is not None else 0.0, lag_ms, corr, cov, False, reason)

    if length == 0 or len(isolated) == 0:
        return unreliable("empty audio")
    o = original.astype(np.float64)
    v = isolated.astype(np.float64)
    if float(np.sqrt(np.mean(v * v))) < MIN_VOICE_RMS:
        return unreliable("isolated audio is silent")
    if float(np.sqrt(np.mean(o * o))) < MIN_VOICE_RMS:
        return unreliable("original audio is silent")

    center = int(round(offset_ms * rate / 1000.0))
    radius = int(round(max_lag_ms * rate / 1000.0))
    lag = _best_lag(o, v, center, radius)
    placed = _shift(v, lag, length)

    covered = np.zeros(length, dtype=bool)
    start, stop = max(0, lag), min(length, lag + len(v))
    if stop > start:
        covered[start:stop] = True
    coverage = float(covered.sum()) / float(length)

    denominator = float(np.dot(placed, placed))
    if denominator <= 0.0:
        return unreliable("isolated audio does not overlap the original", lag * 1000.0 / rate, 0.0, coverage, _shift(v, center, length))
    numerator = float(np.dot(o, placed))
    norm = float(np.sqrt(np.dot(o, o) * denominator))
    correlation = numerator / norm if norm > 0 else 0.0
    gain = numerator / denominator
    lag_ms = lag * 1000.0 / rate

    reason = None
    if coverage < MIN_COVERAGE:
        reason = "isolated audio covers too little of the original"
    elif gain <= 0.0 or correlation < MIN_CORRELATION:
        reason = "isolated audio does not match the original"
    if reason:
        return unreliable(reason, lag_ms, correlation, coverage, _shift(v, center, length))

    voice = gain * placed
    others = o - voice
    return Alignment(
        voice.astype(np.float32), others.astype(np.float32), gain, lag_ms,
        correlation, coverage, True, None,
    )


# -- filtering and limiting --------------------------------------------------

def noise_filter(signal: np.ndarray, mode: str, rate: int = WORK_RATE) -> np.ndarray:
    """Zero-phase high-pass / low-pass (2nd-order Butterworth magnitude)."""
    high, low = NOISE_FILTERS[mode]
    if high is None and low is None:
        return signal
    spectrum = np.fft.rfft(signal.astype(np.float64))
    freqs = np.fft.rfftfreq(len(signal), 1.0 / rate)
    response = np.ones_like(freqs)
    with np.errstate(divide="ignore", invalid="ignore"):
        if high is not None:
            response *= np.where(freqs > 0, 1.0 / np.sqrt(1.0 + (high / freqs) ** 4), 0.0)
        if low is not None:
            response *= 1.0 / np.sqrt(1.0 + (freqs / low) ** 4)
    return np.fft.irfft(spectrum * response, len(signal)).astype(np.float32)


def _sliding_min(values: np.ndarray, width: int) -> np.ndarray:
    """Centered minimum over ``width`` samples (edges padded with 1.0)."""
    if width <= 1:
        return values
    pad = width // 2
    padded = np.concatenate([np.ones(pad), values, np.ones(width - 1 - pad)])
    current, span = padded, 1
    while span * 2 <= width:
        current = np.minimum(current[:-span], current[span:])
        span *= 2
    if span < width:
        extra = width - span
        current = np.minimum(current[:-extra], current[extra:])
    return current[:len(values)]


def limit_peaks(
    signal: np.ndarray,
    ceiling: float = LIMITER_CEILING,
    rate: int = WORK_RATE,
    lookahead_ms: float = LIMITER_LOOKAHEAD_MS,
) -> np.ndarray:
    """Look-ahead peak limiter. Output magnitude is always <= ``ceiling``."""
    x = signal.astype(np.float64)
    if len(x) == 0:
        return signal.astype(np.float32)
    magnitude = np.abs(x)
    needed = np.minimum(1.0, ceiling / np.maximum(magnitude, 1e-12))
    if float(needed.min()) >= 1.0:
        return x.astype(np.float32)
    window = max(3, int(rate * lookahead_ms / 1000.0) | 1)
    floor = _sliding_min(needed, 2 * window - 1)
    smooth = np.convolve(
        np.pad(floor, (window // 2, window - 1 - window // 2), mode="edge"),
        np.ones(window) / window, mode="valid",
    )
    out = x * np.minimum(smooth, needed)
    # Final guarantee against float rounding.
    return np.clip(out, -ceiling, ceiling).astype(np.float32)


def render_mix(alignment: Alignment, settings: MixSettings, rate: int = WORK_RATE) -> np.ndarray:
    settings = settings.validated()
    if settings.others_level > 0 and not alignment.reliable:
        raise MixError("the other-voices track is unreliable for this job", "MIX_UNRELIABLE")
    mixed = settings.voice_level * alignment.voice
    if settings.others_level > 0:
        mixed = mixed + settings.others_level * alignment.others
    mixed = noise_filter(mixed, settings.noise_reduction, rate)
    return limit_peaks(mixed, rate=rate)


def to_float_wav(signal: np.ndarray, rate: int = WORK_RATE) -> bytes:
    """Mono IEEE-float32 WAV (format 3)."""
    data = np.asarray(signal, dtype="<f4").tobytes()
    fmt = struct.pack("<HHIIHHH", 3, 1, rate, rate * 4, 4, 32, 0)
    fact = struct.pack("<I", len(signal))
    body = (
        b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"fact" + struct.pack("<I", len(fact)) + fact
        + b"data" + struct.pack("<I", len(data)) + data
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body
