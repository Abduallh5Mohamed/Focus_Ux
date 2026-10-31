"""One-time setup of the extra isolation engines (ClearerVoice-Studio, Apache-2.0).

Run with the Python that has PyTorch (the .cmd launchers find it; or set FOCUS_PYTHON). Nothing in that environment or
in its model cache is changed: packages and weights go to a separate folder
(%LOCALAPPDATA%\\FocusClearerVoice) after an explicit "yes".

It asks pip (dry run, no changes) which packages the original environment is
missing, installs ONLY those into <folder>\\site, refuses if torch/numpy would
need a different version, then downloads the two weight sets once.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusClearerVoice"
WEIGHTS = {
    "AV_MossFormer2_TSE_16K": "alibabasglab/AV_MossFormer2_TSE_16K",
    "MossFormer2_SS_16K": "alibabasglab/MossFormer2_SS_16K",
}
PROTECTED = ("torch", "torchaudio", "torchvision", "numpy")


def plan_install(report: dict) -> tuple[list[str], list[str]]:
    """From a pip --report: (packages to install, protected packages it would change)."""
    wanted, blocked = [], []
    for item in report.get("install", []):
        meta = item["metadata"]
        name = meta["name"].lower().replace("_", "-")
        spec = f"{meta['name']}=={meta['version']}"
        (blocked if name in PROTECTED else wanted).append(spec)
    return wanted, blocked


def _pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def main(base: Path = DEFAULT_DIR) -> int:
    print("Extra isolation engines: one-time setup")
    print("Folder (separate from your original setup):", base)
    print("It will install missing Python packages and download two model weight sets")
    print("(several hundred MB). Your original environment and cache are not changed.")
    if input("Type yes to continue: ").strip().lower() != "yes":
        print("Cancelled. Nothing was downloaded.")
        return 1
    site = base / "site"
    site.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        _pip("install", "--dry-run", "--quiet", "--report", str(report_path), "clearvoice")
        wanted, blocked = plan_install(json.loads(report_path.read_text("utf-8")))
    if blocked:
        print("Stopped: ClearerVoice would need different versions of", ", ".join(blocked))
        print("Your original environment was not touched. Send this message back.")
        return 2
    if wanted:
        _pip("install", "--target", str(site), "--no-deps", *wanted)
    sys.path.append(str(site))
    from huggingface_hub import snapshot_download
    for name, repo in WEIGHTS.items():
        target = base / "checkpoints" / name
        print("Downloading", name, "...")
        snapshot_download(repo_id=repo, local_dir=str(target))
    print("Done. Weights are stored once; the worker now runs offline.")
    print("Choose an engine with FOCUS_ISOLATION_ENGINE (see docs/ISOLATION_ENGINES.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
