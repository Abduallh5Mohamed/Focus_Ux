"""One-time, approval-first setup of the audio-only voice pipeline.

Run with the ORIGINAL Python (A:\\focus\\.venv). Nothing in that environment or
its model cache is changed: packages and weights go to their own folder
(%LOCALAPPDATA%\\FocusVoice) after an explicit "yes". Nothing is downloaded
at run time; this script is the only thing that downloads.

  site\\     extra Python packages (pyannote.audio, SpeechBrain, ...)
  weights\\  the two voice models
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "product" / "packages" / "ml"))
from focus_ml.voice.weights import (COMPLETE_MARKER, DIARIZER_REPO, ECAPA_REPO,  # noqa: E402
                                    REQUIRED, default_home, weight_dir)

PACKAGES = ["pyannote.audio>=4.0,<5", "speechbrain", "soundfile", "huggingface_hub"]
PROTECTED = ("torch", "torchaudio", "torchvision", "numpy")
TERMS_URL = "https://huggingface.co/" + DIARIZER_REPO

EXPLAIN = f"""
What this does (about 1-2 GB of downloads, once):
  1. Installs a few Python packages into their own folder.
  2. Downloads two voice models:
     - {DIARIZER_REPO}  (works out who is speaking when)
     - {ECAPA_REPO}  (measures a voice, to recognise the same person)
Your original Dolphin setup and its model cache are not touched.

Hugging Face terms step (needed once, for the first model only):
  The who-is-speaking model is "gated": its author asks you to accept the terms
  before you can download it. It is free and licensed CC-BY-4.0 (credit the author).
  a) Log in at huggingface.co, open  {TERMS_URL}
  b) Press the button that accepts the conditions.
  c) Create a READ access token (Settings > Access Tokens). You will be asked to paste it
     here. It is used only for this download and is not saved by this script.
"""


def plan_install(report: dict) -> tuple[list[str], list[str]]:
    wanted, blocked = [], []
    for item in report.get("install", []):
        meta = item["metadata"]
        name = meta["name"].lower().replace("_", "-")
        (blocked if name in PROTECTED else wanted).append(f"{meta['name']}=={meta['version']}")
    return wanted, blocked


def _pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def download(home: Path, token: str | None, snapshot_download=None) -> None:
    if snapshot_download is None:
        from huggingface_hub import snapshot_download
    for repo in (ECAPA_REPO, DIARIZER_REPO):
        target = weight_dir(repo, home)
        print("Downloading", repo, "...")
        snapshot_download(repo_id=repo, local_dir=str(target),
                          token=token if repo == DIARIZER_REPO else None)
        missing = [f for f in REQUIRED[repo] if not (target / f).is_file()]
        if missing:
            raise RuntimeError(f"{repo}: download incomplete, missing {missing}")
        (target / COMPLETE_MARKER).write_text("ok", encoding="utf-8")


def main(home: Path | None = None) -> int:
    home = home or default_home()
    print("Voice pipeline: one-time setup")
    print("Folder (separate from your original setup):", home)
    print(EXPLAIN)
    if input("Type yes to continue: ").strip().lower() != "yes":
        print("Cancelled. Nothing was installed or downloaded.")
        return 1
    site = home / "site"
    site.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "report.json"
        _pip("install", "--dry-run", "--quiet", "--report", str(rp), *PACKAGES)
        wanted, blocked = plan_install(json.loads(rp.read_text("utf-8")))
    if blocked:
        print("Stopped: the voice packages would need different versions of", ", ".join(blocked))
        print("Your original environment was not touched. Send this message back.")
        return 2
    if wanted:
        _pip("install", "--target", str(site), "--no-deps", *wanted)
    sys.path.append(str(site))
    token = os.environ.get("HF_TOKEN") or getpass.getpass(
        "Paste your Hugging Face READ token (hidden), or press Enter to try without one: ").strip() or None
    try:
        download(home, token)
    except Exception as exc:
        print("Download failed:", type(exc).__name__, str(exc)[:300])
        print("If it mentions 401/403, accept the terms at", TERMS_URL, "and use a READ token.")
        return 3
    print("Done. Check with:  python -m focus_ml.voice.cli readiness")
    return 0


if __name__ == "__main__":
    sys.exit(main())
