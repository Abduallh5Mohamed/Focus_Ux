"""Where the voice weights/packages live, and clear errors when they are absent.

Nothing is ever downloaded here: only the setup script downloads, after the
user's explicit approval. At run time a missing weight is an error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .errors import ModelUnavailableError

DIARIZER_REPO = "pyannote/speaker-diarization-community-1"
ECAPA_REPO = "speechbrain/spkrec-ecapa-voxceleb"
SETUP_HINT = ("run the voice setup once (product\\tools\\Setup-Voice.cmd on Windows, "
              "product/tools/setup_voice.py elsewhere) and approve the download")
# the setup script writes this marker only after a complete download
COMPLETE_MARKER = ".focus-complete"
REQUIRED = {
    DIARIZER_REPO: ("config.yaml",),
    ECAPA_REPO: ("hyperparams.yaml", "embedding_model.ckpt", "label_encoder.txt", "mean_var_norm_emb.ckpt"),
}


def default_home() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "FocusVoice"
    return Path(__file__).resolve().parents[5] / "runtime" / "voice"


def voice_home() -> Path:
    return Path(os.environ.get("FOCUS_VOICE_HOME") or default_home())


def cache_dir(home: Path | None = None) -> Path:
    return (home or voice_home()) / "weights"


def weight_dir(repo: str, home: Path | None = None) -> Path:
    return cache_dir(home) / repo.replace("/", "__")


def weight_status(home: Path | None = None) -> dict[str, bool]:
    out = {}
    for repo, files in REQUIRED.items():
        d = weight_dir(repo, home)
        out[repo] = (d / COMPLETE_MARKER).is_file() and all((d / f).is_file() for f in files)
    return out


def require_weights(repo: str, home: Path | None = None) -> Path:
    if not weight_status(home).get(repo):
        raise ModelUnavailableError(
            f"the voice model {repo} is not installed on this computer; " + SETUP_HINT,
            retryable=False, detail=f"missing or incomplete: {weight_dir(repo, home)}")
    return weight_dir(repo, home)


def activate_site(home: Path | None = None) -> None:
    """Append the voice packages folder LAST on sys.path so the original
    environment's packages always win; idempotent."""
    site = str((home or voice_home()) / "site")
    if Path(site).is_dir() and site not in sys.path:
        sys.path.append(site)
