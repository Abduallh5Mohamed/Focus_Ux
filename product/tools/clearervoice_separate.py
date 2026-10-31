"""Run ClearerVoice speech separation (MossFormer2_SS_16K) on one WAV.

Runs in the SEPARATE ClearerVoice environment (torch + clearvoice), never in
the product's ML environment. Prints the produced stems as JSON on stdout.

    <cv python> product/tools/clearervoice_separate.py in.wav out_dir \
        [--model MossFormer2_SS_16K] [--home <dir with checkpoints/>]

Weights are expected under ``<home>/checkpoints/<model>``. They are NOT
downloaded here unless ``--allow-download`` is passed, matching the rule the
rest of the repo follows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--model", default=os.environ.get("FOCUS_CLEARERVOICE_MODEL", "MossFormer2_SS_16K"))
    ap.add_argument("--home", default=os.environ.get("FOCUS_CLEARERVOICE_HOME")
                    or str(PROJECT_ROOT / "model-assets" / "clearervoice"))
    ap.add_argument("--allow-download", action="store_true")
    args = ap.parse_args(argv)

    home = Path(args.home)
    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(home / "hf"))
    os.environ.setdefault("TORCH_HOME", str(home / "torch"))
    if not args.allow_download:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")

    try:
        from clearvoice import ClearVoice
    except Exception as exc:  # noqa: BLE001 - environment dependent
        print(f"clearvoice environment incomplete: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    old = os.getcwd()
    os.chdir(home)                       # checkpoints/ resolves relative to cwd
    try:
        model = ClearVoice(task="speech_separation", model_names=[args.model])
        model(input_path=str(args.src), online_write=True, output_path=str(out_dir))
    except Exception as exc:  # noqa: BLE001
        print(f"separation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4
    finally:
        os.chdir(old)

    stems = sorted(str(p) for p in out_dir.rglob("*.wav"))
    if len(stems) < 2:
        print(f"expected at least two stems, got {len(stems)}", file=sys.stderr)
        return 5
    print(json.dumps({"stems": stems}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
