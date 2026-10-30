"""Where the overlap-extractor weights, code and packages live.

Inside the voice home (see ``voice.weights``), in a subfolder of their own so
the extra packages never mix with the original Dolphin environment or the voice
packages. Nothing is downloaded here: only ``setup_overlap.py`` downloads, after
the user's explicit approval. At run time a missing file is an error.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..voice.weights import COMPLETE_MARKER, voice_home
from .base import BlockedError

SETUP_HINT = ("run the overlap extractor setup once (product\\tools\\Setup-Overlap.cmd on Windows, "
              "product/tools/setup_overlap.py elsewhere) and approve the download")

# candidate -> files that must exist under weights/<candidate>/ (Hugging Face
# repo layouts are kept as downloaded)
REQUIRED_FILES: dict[str, tuple[str, ...]] = {
    "wesep_bsrnn": ("avg_model.pt", "config.yaml"),
    "usef_tse": ("config.yaml", "temp_best.pth.tar"),
    "spexplus": ("config.yaml", "last_best_checkpoint.pt"),
    "sepformer_libri3mix": ("hyperparams.yaml", "encoder.ckpt", "decoder.ckpt", "masknet.ckpt"),
    "pyannote_ami_pixit": ("pyannote__speech-separation-ami-1.0/config.yaml",),
    # mossformer2_ss_voiceprint reuses the ClearerVoice checkpoint folder instead
}
# candidate -> code files/folders that must exist under code/<candidate>/
REQUIRED_CODE: dict[str, tuple[str, ...]] = {
    "wesep_bsrnn": ("wesep/__init__.py",),
    "usef_tse": ("models/model_USEF_SepFormer.py", "models/local/TransformerEncoder.py"),
    "spexplus": ("SpEx_plus.py",),
}


def overlap_home(home: Path | None = None) -> Path:
    return (home or voice_home()) / "overlap"


def weights_dir(name: str, home: Path | None = None) -> Path:
    return overlap_home(home) / "weights" / name


def code_dir(name: str, home: Path | None = None) -> Path:
    return overlap_home(home) / "code" / name


def site_dir(home: Path | None = None) -> Path:
    return overlap_home(home) / "site"


def activate_overlap_site(home: Path | None = None) -> None:
    """Append the extractor packages folder LAST on sys.path (the original
    environment always wins); idempotent."""
    site = str(site_dir(home))
    if Path(site).is_dir() and site not in sys.path:
        sys.path.append(site)


def missing_files(name: str, home: Path | None = None) -> list[str]:
    d, c = weights_dir(name, home), code_dir(name, home)
    miss = [f"weights/{name}/{f}" for f in REQUIRED_FILES.get(name, ()) if not (d / f).is_file()]
    miss += [f"code/{name}/{f}" for f in REQUIRED_CODE.get(name, ()) if not (c / f).is_file()]
    if REQUIRED_FILES.get(name) and not (d / COMPLETE_MARKER).is_file():
        miss.append(f"weights/{name}/{COMPLETE_MARKER}")
    return miss


def require_candidate_files(name: str, title: str, home: Path | None = None) -> None:
    miss = missing_files(name, home)
    if miss:
        raise BlockedError(f"{title}: weights or code are not installed on this computer; " + SETUP_HINT,
                           "missing_weights", "missing: " + ", ".join(miss))
