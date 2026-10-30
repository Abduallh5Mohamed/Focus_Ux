"""Thin, lazy wrapper around ClearerVoice-Studio (Apache-2.0).

Lives in its OWN environment and cache (``clearervoice_dir``), never in the
original Dolphin environment. Weights are fetched once by the setup script after
explicit user consent; at run time nothing is downloaded: a missing checkpoint
raises a clear error pointing to the setup step.

ClearerVoice resolves checkpoints as ``checkpoints/<ModelName>`` relative to the
working directory, so inference runs with cwd=clearervoice_dir. The exact
library call shapes follow its public README and have not been executed against
real weights in this workspace (no GPU/weights here); verify with the compare
tool before choosing an engine.
"""
from __future__ import annotations

import os
from pathlib import Path

from .errors import ModelUnavailableError

TSE_MODEL = "AV_MossFormer2_TSE_16K"
SS_MODEL = "MossFormer2_SS_16K"
SETUP_HINT = (
    "run the Windows setup script for the extra isolation engines "
    "(Setup-ClearerVoice.cmd) once, and approve the one-time download"
)


def checkpoint_dir(base_dir: str | None, model: str) -> Path:
    return Path(base_dir or "") / "checkpoints" / model


def require_weights(base_dir: str | None, models: tuple[str, ...]) -> None:
    """Fail clearly (never download) when a checkpoint is absent or empty."""
    if not base_dir or not Path(base_dir).is_dir():
        raise ModelUnavailableError(
            "the extra isolation engine is not installed on this computer; " + SETUP_HINT,
            retryable=False,
            detail=f"clearervoice_dir missing: {base_dir!r}",
        )
    for model in models:
        d = checkpoint_dir(base_dir, model)
        if not d.is_dir() or not any(p.is_file() for p in d.rglob("*")):
            raise ModelUnavailableError(
                f"model weights {model} are missing; " + SETUP_HINT,
                retryable=False,
                detail=f"empty or missing: {d}",
            )


class ClearerVoiceBackend:
    def __init__(self, base_dir: str | None, device: str = "cuda"):
        self.base_dir = base_dir
        self.device = device
        self._models: dict[str, object] = {}

    def _load(self, task: str, model: str):
        require_weights(self.base_dir, (model,))
        if model in self._models:
            return self._models[model]
        from .runtime import offline_inference
        old = os.getcwd()
        os.chdir(self.base_dir)
        try:
            with offline_inference():
                try:
                    from clearvoice import ClearVoice
                except ImportError as exc:
                    raise ModelUnavailableError(
                        "the ClearerVoice package is not installed in its own environment; "
                        + SETUP_HINT, retryable=False, detail=str(exc),
                    ) from exc
                self._models[model] = ClearVoice(task=task, model_names=[model])
        finally:
            os.chdir(old)
        return self._models[model]

    def _run(self, task: str, model: str, input_path: str, out_dir: str):
        cv = self._load(task, model)
        from .runtime import offline_inference
        old = os.getcwd()
        os.chdir(self.base_dir)
        try:
            with offline_inference():
                cv(input_path=input_path, online_write=True, output_path=out_dir)
        finally:
            os.chdir(old)
        wavs = sorted(Path(out_dir).rglob("*.wav"))
        if not wavs:
            raise ModelUnavailableError("the isolation model produced no audio", retryable=True)
        return wavs

    def warm_up(self, models=(TSE_MODEL, SS_MODEL)):
        tasks = {TSE_MODEL: "target_speaker_extraction", SS_MODEL: "speech_separation"}
        for m in models:
            self._load(tasks[m], m)

    def extract_target_speaker(self, video_path: str, out_dir: str) -> list[str]:
        return [str(p) for p in self._run(
            "target_speaker_extraction", TSE_MODEL, video_path, out_dir)]

    def separate(self, wav_path: str, out_dir: str) -> list[str]:
        return [str(p) for p in self._run("speech_separation", SS_MODEL, wav_path, out_dir)]
