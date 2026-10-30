"""Isolation engines behind one interface.

``run(video_id, video_path, face_id, job_dir, on_progress)`` returns an
``ExtractionResult`` whose ``engine`` names the engine that produced the audio.
Dolphin is wrapped unchanged; the two ClearerVoice engines reuse the existing
face tracking so the chosen face (never another person) drives the result.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Protocol

from .clearervoice_backend import (
    SS_MODEL, TSE_MODEL, ClearerVoiceBackend, require_weights,
)
from .config import ISOLATION_ENGINES, AdapterConfig
from .errors import LimitError, MediaError, ProcessingError
from .speaker_select import choose_source, mouth_openness, score_sources
from .timing import duration_ms_from_samples
from .types import EngineResult, ExtractionResult, TargetSelection

DOLPHIN, AV_MOSSFORMER2, SEPARATE_SELECT = ISOLATION_ENGINES
CROP_MARGIN = 0.15


class IsolationEngine(Protocol):
    name: str

    def check_ready(self) -> None: ...
    def run(self, video_id, video_path, face_id, job_dir, on_progress=None) -> ExtractionResult: ...


# ---------------------------------------------------------------- helpers
def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def crop_region(boxes, frame_size, margin: float = CROP_MARGIN) -> tuple[int, int, int, int]:
    """Union of the tracked face boxes, expanded and clamped; even-sized (x, y, w, h)."""
    valid = [b for b in boxes if b is not None]
    if not valid:
        raise MediaError("no tracked face region to crop")
    fw, fh = frame_size
    x1 = min(b[0] for b in valid); y1 = min(b[1] for b in valid)
    x2 = max(b[2] for b in valid); y2 = max(b[3] for b in valid)
    mx, my = (x2 - x1) * margin, (y2 - y1) * margin
    x1, y1 = max(0, int(x1 - mx)), max(0, int(y1 - my))
    x2, y2 = min(fw, int(x2 + mx)), min(fh, int(y2 + my))
    w, h = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    if w < 16 or h < 16:
        raise MediaError("tracked face region is too small to crop")
    return x1, y1, w, h


def crop_video(video_path: str, region, out_path: str) -> str:
    x, y, w, h = region
    try:
        done = subprocess.run(
            [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", video_path,
             "-vf", f"crop={w}:{h}:{x}:{y}", "-ar", "16000", "-ac", "1",
             "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", out_path],
            capture_output=True, text=True,
        )
    except OSError as exc:
        raise ProcessingError("video tool unavailable", retryable=False, detail=str(exc)) from exc
    if done.returncode != 0 or not os.path.isfile(out_path):
        raise MediaError("the face region could not be cut from the video", detail=done.stderr)
    return out_path


def read_wav(path: str):
    """Mono float32 samples and rate. soundfile when present (any WAV subtype),
    otherwise the stdlib reader for PCM16."""
    try:
        import soundfile as sf
    except ImportError:
        sf = None
    if sf is not None:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        return data.mean(axis=1), sr
    import wave
    import numpy as np
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise MediaError("only PCM16 WAV can be read without soundfile")
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
        return raw.reshape(-1, w.getnchannels()).mean(axis=1), w.getframerate()


def fit_samples(samples, sr: int, target_sr: int, n_target: int):
    """Resample (linear) to target_sr, then pad/trim to exactly n_target samples."""
    import numpy as np
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sr != target_sr and len(x):
        n_new = max(1, round(len(x) * target_sr / sr))
        x = np.interp(np.linspace(0, len(x) - 1, n_new), np.arange(len(x)), x).astype(np.float32)
    if len(x) < n_target:
        x = np.pad(x, (0, n_target - len(x)))
    return x[:n_target]


def write_wav(path: str, samples, sr: int) -> None:
    """Mono PCM16 WAV (the format the API validates)."""
    import wave
    import numpy as np
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


class AdapterTracker:
    """Face tracking via the existing Dolphin adapter (landmarks + target boxes)."""

    def __init__(self, adapter, models_getter, config: AdapterConfig):
        self.adapter, self.models_getter, self.config = adapter, models_getter, config

    def track(self, video_id, video_path, face_id) -> dict:
        a, cfg, models = self.adapter, self.config, self.models_getter()
        frames, size = a._read_frames_bgr(video_path)
        if len(frames) / cfg.fps > cfg.max_video_seconds + 1e-6:
            raise LimitError(f"video exceeds the {cfg.max_video_seconds}s limit")
        backend = a._backend_from_bundle(models, cfg)
        result = a._track_stage(
            backend, frames, video_path, TargetSelection(face_id=face_id), cfg, video_id)
        return {"boxes": result["boxes"], "landmarks": result["landmarks"],
                "warnings": list(result["warnings"]), "frame_size": size,
                "n_frames": len(frames)}

    def extract_audio(self, video_path, job_dir) -> str:
        return self.adapter._extract_audio(video_path, str(job_dir))


# ---------------------------------------------------------------- engines
class DolphinEngine:
    name = DOLPHIN

    def __init__(self, adapter, models_getter):
        self.adapter, self.models_getter = adapter, models_getter

    def check_ready(self) -> None:
        pass

    def run(self, video_id, video_path, face_id, job_dir, on_progress=None):
        result = self.adapter.extract_target(
            video_path, TargetSelection(face_id=face_id), job_dir,
            self.models_getter(), on_progress, video_id=video_id)
        return EngineResult(**vars(result), engine=DOLPHIN)


class _ClearerVoiceEngine:
    models: tuple[str, ...] = ()

    def __init__(self, tracker, backend: ClearerVoiceBackend, config: AdapterConfig):
        self.tracker, self.backend, self.config = tracker, backend, config

    def check_ready(self) -> None:
        require_weights(self.config.clearervoice_dir or self.backend.base_dir, self.models)

    def _finish(self, samples, sr, mix_wav, job_dir, timings, warnings, details, t0, on_progress):
        n = len(read_wav(mix_wav)[0])
        out = os.path.join(str(job_dir), "isolated.wav")
        fixed = fit_samples(samples, sr, self.config.sample_rate, n)
        write_wav(out, fixed, self.config.sample_rate)
        timings["total"] = round(time.perf_counter() - t0, 2)
        if on_progress:
            on_progress("separating", 1.0)
        return EngineResult(
            wav_path=out, duration_ms=duration_ms_from_samples(n, self.config.sample_rate),
            source_offset_ms=0, timings=timings, warnings=warnings,
            engine=self.name, details=details)


class AvMossFormer2Engine(_ClearerVoiceEngine):
    """Audio-visual target-speaker extraction on a crop of the chosen face."""
    name = AV_MOSSFORMER2
    models = (TSE_MODEL,)

    def run(self, video_id, video_path, face_id, job_dir, on_progress=None, cropper=crop_video):
        self.check_ready()
        t0, timings = time.perf_counter(), {}
        if on_progress:
            on_progress("tracking", 0.0)
        t = time.perf_counter()
        info = self.tracker.track(video_id, video_path, face_id)
        timings["detect_track"] = round(time.perf_counter() - t, 2)
        if on_progress:
            on_progress("tracking", 1.0)
            on_progress("separating", 0.0)
        t = time.perf_counter()
        region = crop_region(info["boxes"], info["frame_size"])
        crop = cropper(video_path, region, os.path.join(str(job_dir), "face_crop.mp4"))
        timings["crop"] = round(time.perf_counter() - t, 2)
        mix = self.tracker.extract_audio(video_path, job_dir)
        t = time.perf_counter()
        outs = self.backend.extract_target_speaker(crop, os.path.join(str(job_dir), "tse"))
        timings["tse"] = round(time.perf_counter() - t, 2)
        samples, sr = read_wav(outs[0])
        warnings = list(info["warnings"]) + [
            "AV-MossFormer2 sees only a crop around the chosen face; if another "
            "person stands inside that crop the model may follow them"]
        return self._finish(samples, sr, mix, job_dir, timings, warnings,
                            {"crop_region": list(region)}, t0, on_progress)


class SeparateSelectEngine(_ClearerVoiceEngine):
    """Separate every voice, then pick the one synced with the chosen face's lips."""
    name = SEPARATE_SELECT
    models = (SS_MODEL,)

    def run(self, video_id, video_path, face_id, job_dir, on_progress=None):
        self.check_ready()
        t0, timings = time.perf_counter(), {}
        if on_progress:
            on_progress("tracking", 0.0)
        t = time.perf_counter()
        info = self.tracker.track(video_id, video_path, face_id)
        timings["detect_track"] = round(time.perf_counter() - t, 2)
        if on_progress:
            on_progress("tracking", 1.0)
            on_progress("separating", 0.0)
        mix = self.tracker.extract_audio(video_path, job_dir)
        t = time.perf_counter()
        outs = self.backend.separate(mix, os.path.join(str(job_dir), "ss"))
        timings["separate"] = round(time.perf_counter() - t, 2)
        sources = []
        for path in outs:
            s, sr = read_wav(path)
            sources.append(fit_samples(
                s, sr, self.config.sample_rate,
                round(len(s) * self.config.sample_rate / sr)))
        t = time.perf_counter()
        mouth = mouth_openness(info["landmarks"])
        scores = score_sources(sources, self.config.sample_rate, mouth, self.config.fps)
        selection = choose_source(scores)
        timings["select"] = round(time.perf_counter() - t, 2)
        warnings = list(info["warnings"]) + list(selection.warnings)
        return self._finish(sources[selection.index], self.config.sample_rate, mix, job_dir,
                            timings, warnings, selection.as_dict(), t0, on_progress)


def build_engine(config: AdapterConfig, adapter, models_getter, backend=None):
    """The single engine-selection point."""
    name = config.isolation_engine
    if name == DOLPHIN:
        return DolphinEngine(adapter, models_getter)
    if name not in (AV_MOSSFORMER2, SEPARATE_SELECT):
        raise ValueError(f"unknown isolation engine {name!r}; choose one of {ISOLATION_ENGINES}")
    backend = backend or ClearerVoiceBackend(config.clearervoice_dir, config.device)
    tracker = AdapterTracker(adapter, models_getter, config)
    cls = AvMossFormer2Engine if name == AV_MOSSFORMER2 else SeparateSelectEngine
    return cls(tracker, backend, config)
