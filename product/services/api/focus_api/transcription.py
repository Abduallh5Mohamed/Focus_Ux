"""TranscriptProvider backed by the connected Windows worker (ASR on the isolated WAV).

The model is loaded once by the worker process and shares its GPU with isolation
because the dispatcher runs one job at a time and the bridge has one outstanding
task. Failures are raised as TranscriptError with a stable reason; no text is
ever fabricated and the isolated audio stays available.
"""
from __future__ import annotations

from pathlib import Path

from services.worker.errors import TranscriptError

from .interfaces import ProviderError

_REASONS = {
    "MODEL_UNAVAILABLE": ("model_unavailable", "transcription model is not available", False),
    "OUT_OF_MEMORY": ("out_of_memory", "transcription ran out of GPU memory", True),
    "TIMEOUT": ("timeout", "transcription timed out", True),
    "GPU_BUSY": ("out_of_memory", "GPU unavailable for transcription", True),
}


class RemoteTranscriber:
    def __init__(self, bridge, repo, *, timeout_s: float = 300.0):
        self.bridge, self.repo, self.timeout_s = bridge, repo, timeout_s

    def _video_id(self, wav_path: str) -> str:
        # Layout is <jobs>/<job_id>/isolated.wav; resolve through the repository.
        job = self.repo.find_job(Path(wav_path).parent.name)
        if job is None:
            raise TranscriptError("job for transcription not found", reason="failed")
        return job.video_id

    def transcribe(self, wav_path, on_progress=None):
        video_id = self._video_id(wav_path)
        try:
            return self.bridge.call(
                kind="transcribe", video_id=video_id, video_path=wav_path,
                timeout_s=self.timeout_s,
            )
        except ProviderError as exc:
            if "offline" in str(exc):
                raise TranscriptError(str(exc), reason="worker_offline") from exc
            reason, message, retryable = _REASONS.get(
                exc.code, ("failed", "transcription failed", True)
            )
            raise TranscriptError(message, reason=reason, retryable=retryable) from exc
