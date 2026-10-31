"""Read-only check of this computer for the local GPU worker (any NVIDIA CUDA GPU).

Reports the GPU, driver, CUDA and free VRAM, the Python in use, the model folders and checkpoints, the
sizing that WeSep extraction would start with, and (with --url) the connection to a remote website.
Loads no model, downloads nothing, measures no speed. Writes gpu-check-out/gpu_check.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "product" / "packages" / "ml"))
sys.path.insert(0, str(ROOT / "product"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", help="HTTPS address of a remote website: also check the worker connection")
    ap.add_argument("--local-api", action="store_true", help="check the loopback API with the local credential")
    ap.add_argument("--out", type=Path, default=Path("gpu-check-out"))
    args = ap.parse_args(argv)
    from focus_ml import gpu_report
    report = gpu_report.collect(args.url, args.local_api)
    print(gpu_report.render(report))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gpu_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Report saved to", args.out / "gpu_check.json")
    return 0 if report["ready_for_audio_only_worker"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
