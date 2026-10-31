"""Check (and optionally fetch) the Demucs music separator.

Run it with the DEDICATED Demucs environment python, never the product one:

    python -m venv runtime/demucs-venv/env
    runtime/demucs-venv/env/Scripts/python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    runtime/demucs-venv/env/Scripts/python -m pip install demucs
    runtime/demucs-venv/env/Scripts/python product/tools/demucs_setup.py            # check only
    runtime/demucs-venv/env/Scripts/python product/tools/demucs_setup.py --download # fetch weights

Then point the product at it:

    set FOCUS_VOICE_EXTRACTOR=music
    set FOCUS_DEMUCS_PYTHON=<abs path to runtime/demucs-venv/env/Scripts/python.exe>

Weights and caches stay under ``model-assets/demucs`` (or ``FOCUS_DEMUCS_DIR``).
Nothing here touches the legacy tree or any global package.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    path = Path(os.environ.get("FOCUS_DEMUCS_DIR") or (PROJECT_ROOT / "model-assets" / "demucs"))
    path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TORCH_HOME", str(path / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(path / "cache"))
    os.environ.setdefault("HF_HOME", str(path / "hf"))
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true",
                    help="fetch the weights once; without it a missing checkpoint is only reported")
    ap.add_argument("--model", default=os.environ.get("FOCUS_DEMUCS_MODEL", "htdemucs"))
    args = ap.parse_args(argv)

    home = cache_dir()
    report = {"cache_dir": str(home), "model": args.model, "python": sys.executable}

    try:
        import torch
        import torchaudio
        import demucs
    except ImportError as exc:
        report.update(ready=False, error=f"missing package: {exc}")
        print(json.dumps(report, indent=2))
        return 3
    report.update(torch=torch.__version__, torchaudio=torchaudio.__version__,
                  demucs=getattr(demucs, "__version__", "unknown"),
                  cuda=bool(torch.cuda.is_available()))

    if not args.download:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        from demucs.pretrained import get_model
        model = get_model(args.model)
    except Exception as exc:  # noqa: BLE001
        report.update(ready=False, error=f"{type(exc).__name__}: {exc}",
                      hint="re-run with --download once to fetch the weights")
        print(json.dumps(report, indent=2))
        return 4

    report.update(ready=True, samplerate=model.samplerate, sources=list(model.sources))
    # A real forward pass on one second of noise: proves the weights load and run.
    import torch
    from demucs.apply import apply_model
    model.eval()
    probe = torch.zeros(1, 2, model.samplerate)
    with torch.no_grad():
        out = apply_model(model, probe, device="cpu", split=False, progress=False)
    report["probe_output_shape"] = list(out.shape)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
