"""Where the local models live, resolved from settings instead of a fixed drive or folder.

``FOCUS_HOME`` is the folder that holds the lip-model source (``Dolphin``) and its caches (``cache/hf``,
``cache/torch``). It defaults to the project folder. Each part can be placed separately:

    FOCUS_MODEL_SOURCE   the Dolphin source folder
    FOCUS_MODEL_CACHE    the Hugging Face cache (also used as HF_HOME)
    FOCUS_TORCH_HOME     the torch cache (TORCH_HOME)
    FOCUS_VOICE_HOME     voice and overlap-extractor (WeSep) weights, code and packages

Nothing is created or downloaded here.
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def focus_home(explicit: str | os.PathLike | None = None, env=None) -> Path:
    env = os.environ if env is None else env
    raw = explicit or env.get("FOCUS_HOME")
    return Path(raw).expanduser().resolve() if raw else PROJECT_ROOT


def model_environment(home: Path, env=None) -> dict[str, str]:
    """Environment variables for offline model loading. Explicit FOCUS_* settings win over the
    layout under ``home``."""
    env = os.environ if env is None else env
    source = env.get("FOCUS_MODEL_SOURCE") or str(home / "Dolphin")
    cache = env.get("FOCUS_MODEL_CACHE") or str(home / "cache" / "hf")
    torch_home = env.get("FOCUS_TORCH_HOME") or str(home / "cache" / "torch")
    return {"HF_HOME": cache, "TORCH_HOME": torch_home, "FOCUS_MODEL_SOURCE": source,
            "FOCUS_MODEL_CACHE": cache, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


def missing_model_assets(settings: dict[str, str]) -> list[str]:
    """What the local lip model needs that is not there, as readable messages (empty when present)."""
    problems = []
    source = Path(settings["FOCUS_MODEL_SOURCE"])
    if not (source / "Inference.py").is_file():
        problems.append(f"Dolphin source not found at {source} (set FOCUS_HOME or FOCUS_MODEL_SOURCE)")
    if not Path(settings["FOCUS_MODEL_CACHE"]).is_dir():
        problems.append(f"model cache not found at {settings['FOCUS_MODEL_CACHE']} "
                        "(set FOCUS_HOME or FOCUS_MODEL_CACHE)")
    return problems
