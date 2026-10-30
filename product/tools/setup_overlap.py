"""One-time, approval-first setup of the overlap-extraction candidates.

Run with the ORIGINAL Python (A:\\focus\\.venv). Nothing in that environment or its
model cache is changed: packages, code and weights go to <voice home>\\overlap
(%LOCALAPPDATA%\\FocusVoice\\overlap) after an explicit "yes". Nothing is downloaded at
run time; this script is the only thing that downloads.

  weights\\<candidate>\\   checkpoints          code\\<candidate>\\   pinned source files
  site\\                   extra Python packages (never torch/numpy)

MossFormer2 reuses the ClearerVoice folder made by Setup-ClearerVoice.cmd.
A candidate whose download fails is reported and skipped; the others continue.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "ml"), str(Path(__file__).parent)]
from focus_ml.overlap import weights as W  # noqa: E402
from focus_ml.voice.weights import COMPLETE_MARKER  # noqa: E402
from setup_clearervoice import plan_install  # noqa: E402

PACKAGES = ["hyperpyyaml", "speechbrain", "pyyaml", "soundfile", "scipy", "huggingface_hub",
            "pyannote.audio>=4.0,<5", "kaldiio", "fire", "tqdm", "gdown"]
WESEP_SHA = "2a540977a348fbaa92e623210505430e2cec608d"
WESPEAKER_SHA = "8f53b6485d9f88a207bd17e7f8dba899495ec794"
USEF_HF_REVISION = "6e2bd14dd3a2d4fcb6abd246cce5f91538c08dbf"   # reviewed Hugging Face revision of the weights
USEF_SHA = "bdaeb3609735b3a9dbedd1b0625343826f2cb5fe"
CLEARER_SHA = "6b3774dc79c46ae8bed2a4fa5f706f0ac8c75c61"
GDRIVE_ID = "1M4UqK2A2EeHmQ0pCevYqBgaYn3RvklgC"
USEF_CODE_FILES = (
    "models/model_USEF_SepFormer.py", "models/local/PositionalEncoding.py",
    "models/local/TransformerEncoder.py", "models/local/TransformerEncoderCross.py",
    "models/local/attention.py", "models/local/normalization.py", "models/local/activations.py",
    "models/local/dataio.py", "models/local/get_layer_from_string.py",
    "models/local/torch_audio_backend.py")
PIXIT_REPOS = ("pyannote/speech-separation-ami-1.0", "pyannote/separation-ami-1.0",
               "pyannote/wespeaker-voxceleb-resnet34-LM")

EXPLAIN = """
What this does (several GB of downloads, once; each candidate is independent):
  wesep_bsrnn          REAL-TSE WeSep BSRNN: code zip from GitHub + checkpoint from Google Drive
                       (code Apache-2.0; checkpoint has NO explicit licence)
  usef_tse             USEF-TSE SepFormer wsj0-2mix, ~410 MB, CC-BY-NC-4.0 (non-commercial)
  spexplus             ClearerVoice SpEx+ wsj0-2mix, Apache-2.0, plus one pinned source file
  sepformer_libri3mix  SpeechBrain SepFormer libri3mix, Apache-2.0
  pyannote_ami_pixit   pyannote speech-separation-ami-1.0, MIT, gated: accept the terms at
                       https://huggingface.co/pyannote/speech-separation-ami-1.0 and use a READ token
  mossformer2          reuses the Setup-ClearerVoice.cmd download (run that first)
Your original Dolphin environment and its cache are not touched.
"""


class Fetcher:
    """The only place that touches the network (replaced by a fake in tests)."""

    def hf_file(self, repo: str, filename: str, dest: Path, token=None, revision=None) -> None:
        from huggingface_hub import hf_hub_download
        with tempfile.TemporaryDirectory() as tmp:
            p = hf_hub_download(repo_id=repo, filename=filename, local_dir=tmp, token=token, revision=revision)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)

    def hf_snapshot(self, repo: str, cache_dir: Path, token=None) -> None:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo, cache_dir=str(cache_dir), token=token)

    def hf_snapshot_local(self, repo: str, dest: Path) -> None:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=repo, local_dir=str(dest))

    def url_file(self, url: str, dest: Path) -> None:
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:   # noqa: S310
            shutil.copyfileobj(r, f)

    def gdrive(self, file_id: str, dest: Path) -> None:
        import gdown
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not gdown.download(id=file_id, output=str(dest), quiet=False):
            raise RuntimeError("Google Drive refused the download (quota or permission)")


def _mark(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / COMPLETE_MARKER).write_text("ok", encoding="utf-8")


def step_sepformer(f, home, token):
    d = W.weights_dir("sepformer_libri3mix", home)
    f.hf_snapshot_local("speechbrain/sepformer-libri3mix", d)
    _mark(d)


def step_spexplus(f, home, token):
    d, sub = W.weights_dir("spexplus", home), "checkpoints/log_wsj0-2mix_speech_SpEx-plus_2spk/"
    repo = "alibabasglab/log_wsj0-2mix_speech_SpEx-plus_2spk"
    f.hf_file(repo, sub + "config.yaml", d / "config.yaml")
    f.hf_file(repo, sub + "last_best_checkpoint.pt", d / "last_best_checkpoint.pt")
    f.url_file("https://raw.githubusercontent.com/modelscope/ClearerVoice-Studio/" + CLEARER_SHA +
               "/train/target_speaker_extraction/models/SpEx_plus/SpEx_plus.py",
               W.code_dir("spexplus", home) / "SpEx_plus.py")
    _mark(d)


def step_usef(f, home, token):
    d, c = W.weights_dir("usef_tse", home), W.code_dir("usef_tse", home)
    f.hf_file("ZBang/USEF-TSE", "chkpt/USEF-SepFormer/wsj0-2mix/config.yaml", d / "config.yaml",
              revision=USEF_HF_REVISION)
    f.hf_file("ZBang/USEF-TSE", "chkpt/USEF-SepFormer/wsj0-2mix/temp_best.pth.tar", d / "temp_best.pth.tar",
              revision=USEF_HF_REVISION)
    for rel in USEF_CODE_FILES:
        f.url_file(f"https://raw.githubusercontent.com/ZBang/USEF-TSE/{USEF_SHA}/{rel}", c / rel)
    for pkg in ("models", "models/local"):
        (c / pkg / "__init__.py").write_text("", encoding="utf-8")
    _mark(d)


def step_pixit(f, home, token):
    d = W.weights_dir("pyannote_ami_pixit", home)
    for repo in PIXIT_REPOS:
        f.hf_snapshot(repo, d / "hf_cache", token)
    f.hf_file(PIXIT_REPOS[0], "config.yaml", d / "pyannote__speech-separation-ami-1.0" / "config.yaml", token)
    _mark(d)


def step_wesep(f, home, token):
    d, c = W.weights_dir("wesep_bsrnn", home), W.code_dir("wesep_bsrnn", home)
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / "wesep.zip"
        f.url_file(f"https://github.com/REAL-TSE/wesep-real-tse/archive/{WESEP_SHA}.zip", z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
        src = Path(tmp) / f"wesep-real-tse-{WESEP_SHA}" / "wesep"
        if c.exists():
            shutil.rmtree(c)
        c.mkdir(parents=True)
        shutil.copytree(src, c / "wesep")
        blob = Path(tmp) / "checkpoint.bin"
        f.gdrive(GDRIVE_ID, blob)
        if zipfile.is_zipfile(blob):
            with zipfile.ZipFile(blob) as zf:
                zf.extractall(Path(tmp) / "ckpt")
            hits = list((Path(tmp) / "ckpt").rglob("spk_emb_100/avg_model.pt"))
            if not hits:
                raise RuntimeError("spk_emb_100/avg_model.pt not found in the downloaded archive")
            d.mkdir(parents=True, exist_ok=True)
            for name in ("avg_model.pt", "config.yaml"):
                shutil.copyfile(hits[0].parent / name, d / name)
        else:
            raise RuntimeError("the Google Drive download is not an archive; place spk_emb_100/avg_model.pt "
                               f"and config.yaml in {d} by hand")
    _mark(d)


STEPS = {"sepformer_libri3mix": step_sepformer, "spexplus": step_spexplus, "usef_tse": step_usef,
         "pyannote_ami_pixit": step_pixit, "wesep_bsrnn": step_wesep}


def _pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", *args], check=True)


def install_packages(home: Path) -> int:
    site = W.site_dir(home)
    site.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "report.json"
        _pip("install", "--dry-run", "--quiet", "--report", str(rp), *PACKAGES)
        wanted, blocked = plan_install(json.loads(rp.read_text("utf-8")))
    if blocked:
        print("Stopped: the extractor packages would need different versions of", ", ".join(blocked))
        print("Your original environment was not touched. Send this message back.")
        return 2
    if wanted:
        _pip("install", "--target", str(site), "--no-deps", *wanted)
    # WeSep's speaker-embedding dependency is a pinned git commit (needs git on PATH)
    try:
        _pip("install", "--target", str(site), "--no-deps",
             f"git+https://github.com/wenet-e2e/wespeaker.git@{WESPEAKER_SHA}")
    except (subprocess.CalledProcessError, OSError) as exc:
        print("Note: wespeaker could not be installed (needs git); REAL-TSE WeSep will be reported blocked:", exc)
    return 0


def main(home: Path | None = None, only: list[str] | None = None, fetcher=None, ask=input,
         packages=install_packages, token_getter=None) -> int:
    home = home or W.voice_home()
    fetcher = fetcher or Fetcher()
    chosen = only or list(STEPS)
    print("Overlap extractors: one-time setup")
    print("Folder (separate from your original setup):", W.overlap_home(home))
    print(EXPLAIN)
    if ask("Type yes to continue: ").strip().lower() != "yes":
        print("Cancelled. Nothing was installed or downloaded.")
        return 1
    rc = packages(home)
    if rc:
        return rc
    W.activate_overlap_site(home)
    token = token_getter() if token_getter else None
    failed = {}
    for name in chosen:
        print("Setting up", name, "...")
        try:
            STEPS[name](fetcher, home, token)
        except Exception as exc:     # one candidate failing must not stop the others
            failed[name] = f"{type(exc).__name__}: {str(exc)[:300]}"
            print("  FAILED:", failed[name])
    for name in chosen:
        miss = W.missing_files(name, home)
        print(f"{name}: {'ready' if not miss and name not in failed else 'NOT ready'}", *(["-", "; ".join(miss)] if miss else []))
    if failed:
        print("Some candidates are not installed. They will be reported as blocked, with this evidence.")
        return 3
    print("Done. Check with:  python -m focus_ml.voice.cli readiness")
    return 0


def _token():
    import getpass
    import os
    return os.environ.get("HF_TOKEN") or getpass.getpass(
        "Paste your Hugging Face READ token (hidden; needed for pyannote_ami_pixit), or press Enter: ").strip() or None


if __name__ == "__main__":
    sys.exit(main(token_getter=_token))
