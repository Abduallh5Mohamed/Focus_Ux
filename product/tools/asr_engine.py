"""Egyptian-Arabic ASR on the isolated WAV, run inside the Windows worker.

The model is loaded once (lazily, on first transcription task) and kept for the
life of the worker process. Weights are never downloaded: the worker sets
HF_HUB_OFFLINE=1, so FOCUS_ASR_MODEL must be a local directory or an already
cached model name. A missing model raises code MODEL_UNAVAILABLE; the website
then reports that honestly and the isolated audio stays available.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "small"  # the previously deployed baseline; see docs/ASR_MODEL_COMPARISON.md


class AsrError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or "cuda failed with error out of memory" in text


class AsrEngine:
    def __init__(self, model: str | None = None, device: str | None = None,
                 compute_type: str | None = None):
        self.model_name = model or os.environ.get("FOCUS_ASR_MODEL", DEFAULT_MODEL)
        self.device = device or os.environ.get("FOCUS_ASR_DEVICE", "cuda")
        self.compute_type = compute_type or os.environ.get("FOCUS_ASR_COMPUTE", "int8_float16")
        self.beam_size = int(os.environ.get("FOCUS_ASR_BEAM", "5"))
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise AsrError("MODEL_UNAVAILABLE", "faster-whisper is not installed") from None
        try:
            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        except Exception as exc:
            if _is_oom(exc):
                raise AsrError("OUT_OF_MEMORY", "GPU memory exhausted loading ASR model") from None
            raise AsrError("MODEL_UNAVAILABLE", "ASR model could not be loaded offline") from None
        return self._model

    def transcribe(self, wav_path: str) -> list[dict]:
        import soundfile as sf

        model = self._load()
        audio, _rate = sf.read(wav_path, dtype="float32")  # worker WAVs are 16 kHz mono
        if audio.ndim > 1:
            audio = audio.mean(1)
        try:
            segments, _info = model.transcribe(
                audio, language="ar", beam_size=self.beam_size, vad_filter=True
            )
            result = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    result.append({
                        "start_ms": max(0, int(round(seg.start * 1000))),
                        "end_ms": max(0, int(round(seg.end * 1000))),
                        "text": text,
                    })
            return result
        except Exception as exc:
            if _is_oom(exc):
                raise AsrError("OUT_OF_MEMORY", "GPU memory exhausted during transcription") from None
            raise
