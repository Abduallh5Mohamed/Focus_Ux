"""Check (and optionally fetch) the ClearerVoice speech separator.

Run it with the DEDICATED ClearerVoice environment python:

    python -m venv A:/Focus_runtime/cv-venv/env
    A:/Focus_runtime/cv-venv/env/Scripts/python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    A:/Focus_runtime/cv-venv/env/Scripts/python -m pip install clearvoice --no-deps
    A:/Focus_runtime/cv-venv/env/Scripts/python -m pip install torchvision --index-url https://download.pytorch.org/whl/cpu
    A:/Focus_runtime/cv-venv/env/Scripts/python -m pip install einops gdown huggingface-hub joblib librosa \
        numpy opencv-python packaging pydub python_speech_features rotary_embedding_torch scenedetect \
        scikit-learn scipy soundfile torchinfo tqdm yamlargparse audioop-lts

(`audioop-lts` is required on Python 3.13 because pydub still imports `audioop`,
which the standard library dropped.)

    <cv python> product/tools/clearervoice_setup.py            # check only
    <cv python> product/tools/clearervoice_setup.py --download  # fetch weights once

Then point the product at it:

    FOCUS_VOICE_EXTRACTOR=separation
    FOCUS_CLEARERVOICE_PYTHON=<abs path to the cv venv python>
    FOCUS_CLEARERVOICE_HOME=<dir that holds checkpoints/>   (default model-assets/clearervoice)

Measured cost on this laptop (CPU, 137 s clip): model fetch ~9 min once, then
~18 min of inference. It is a quality path, not a fast one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def home_dir() -> Path:
    path = Path(os.environ.get("FOCUS_CLEARERVOICE_HOME") or (PROJECT_ROOT / "model-assets" / "clearervoice"))
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(path / "hf"))
    os.environ.setdefault("TORCH_HOME", str(path / "torch"))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true",
                    help="fetch the checkpoint once; without it a missing one is only reported")
    ap.add_argument("--model", default=os.environ.get("FOCUS_CLEARERVOICE_MODEL", "MossFormer2_SS_16K"))
    args = ap.parse_args(argv)

    home = home_dir()
    report = {"home": str(home), "model": args.model, "python": sys.executable}
    try:
        import torch
        import torchaudio
        import clearvoice
    except Exception as exc:  # noqa: BLE001
        report.update(ready=False, error=f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, indent=2))
        return 3
    report.update(torch=torch.__version__, torchaudio=torchaudio.__version__,
                  clearvoice=getattr(clearvoice, "__version__", "unknown"),
                  cuda=bool(torch.cuda.is_available()))

    checkpoint = home / "checkpoints" / args.model
    report["checkpoint"] = str(checkpoint)
    report["checkpoint_present"] = checkpoint.is_dir() and any(checkpoint.rglob("*"))

    if not report["checkpoint_present"] and not args.download:
        report.update(ready=False, hint="re-run with --download once to fetch the weights")
        print(json.dumps(report, indent=2))
        return 4

    if not args.download:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    old = os.getcwd()
    os.chdir(home)
    try:
        from clearvoice import ClearVoice
        ClearVoice(task="speech_separation", model_names=[args.model])
    except Exception as exc:  # noqa: BLE001
        report.update(ready=False, error=f"{type(exc).__name__}: {exc}")
        print(json.dumps(report, indent=2))
        return 5
    finally:
        os.chdir(old)

    report.update(ready=True, checkpoint_present=True)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
