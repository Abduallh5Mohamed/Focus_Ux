"""Readiness and licence record of the three voice-conditioned candidates.

Facts that cannot be read from files (source URLs, licence statements, how the enrollment
is fed) are written here once, with where each statement was checked. Facts that can be read
(file hashes, package versions, whether the files are present) are measured on the computer
that runs this. Nothing is downloaded here.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as md
import platform
import sys
from pathlib import Path

from . import weights as W
from .candidates import INFO

UNRESTRICTED = "clear for unrestricted use"
NON_COMMERCIAL = "academic / non-commercial only"
UNCLEAR = "unclear, not approved for deployment"
NOT_APPROVED = (NON_COMMERCIAL, UNCLEAR)

# Statements checked on 2026-10-30 against the sources named in "checked".
FACTS = {
    "wesep_bsrnn": {
        "weights_source": "https://drive.google.com/uc?export=download&id=1M4UqK2A2EeHmQ0pCevYqBgaYn3RvklgC "
                          "(Google Drive archive from the REAL-T project; file spk_emb_100/avg_model.pt)",
        "code_source": "https://github.com/REAL-TSE/wesep-real-tse @ 2a540977a348fbaa92e623210505430e2cec608d "
                       "(wesep package) plus https://github.com/wenet-e2e/wespeaker @ "
                       "8f53b6485d9f88a207bd17e7f8dba899495ec794 (git dependency)",
        "enrollment_feed": "Enrollment waveform (at most 10 s, 16 kHz) -> 80-bin Kaldi fbank with mean "
                           "normalisation -> speaker network inside the model (spk_emb); the mixture waveform "
                           "goes in alongside. Called in memory with extract_speech_from_pcm.",
        "licence_status": UNCLEAR,
        "licence_reason": "No licence file or licence statement accompanies the Google Drive checkpoint, and the "
                          "GitHub API reports no licence for the REAL-TSE repository (checked 2026-10-30). "
                          "The upstream wesep/wespeaker code is Apache-2.0, but that does not license these weights.",
        "checked": "GitHub API licence field for REAL-TSE/wesep-real-tse: null; README links the Drive file only.",
    },
    "usef_tse": {
        "weights_source": "https://huggingface.co/ZBang/USEF-TSE/tree/main/chkpt/USEF-SepFormer/wsj0-2mix "
                          "(revision 6e2bd14dd3a2d4fcb6abd246cce5f91538c08dbf at record time)",
        "code_source": "https://github.com/ZBang/USEF-TSE @ bdaeb3609735b3a9dbedd1b0625343826f2cb5fe "
                       "(nine model files copied unchanged)",
        "enrollment_feed": "Enrollment waveform (at most 10 s) resampled to 8 kHz and passed as the second model "
                           "input; the same encoder embeds it and cross-attention fuses it with the mixture "
                           "(no separate speaker embedding).",
        "licence_status": NON_COMMERCIAL,
        "licence_reason": "The GitHub LICENSE file is Creative Commons Attribution-NonCommercial 4.0. The Hugging "
                          "Face repository has no model card (README.md returns 404 on 2026-10-30), so the weights "
                          "carry that same non-commercial licence by the project's own statement. Trained on WSJ0.",
        "checked": "raw LICENSE of ZBang/USEF-TSE @ bdaeb36; HF README.md 404.",
    },
    "spexplus": {
        "weights_source": "https://huggingface.co/alibabasglab/log_wsj0-2mix_speech_SpEx-plus_2spk "
                          "(revision 2b99a144297ac4d074bb9dcc4ce9734a7e8924fd at record time; "
                          "checkpoints/log_wsj0-2mix_speech_SpEx-plus_2spk/last_best_checkpoint.pt)",
        "code_source": "https://github.com/modelscope/ClearerVoice-Studio @ 6b3774dc79c46ae8bed2a4fa5f706f0ac8c75c61 "
                       "(train/target_speaker_extraction/models/SpEx_plus/SpEx_plus.py, one file)",
        "enrollment_feed": "Enrollment waveform (at most 10 s) resampled to 8 kHz plus its length is the "
                           "auxiliary input of the SpEx+ speaker encoder (a ResNet speaker network trained with "
                           "the extractor); the first of the three multi-scale outputs is used, then matched in "
                           "polarity and level to the mixture by least squares.",
        "licence_status": UNRESTRICTED,
        "licence_reason": "Hugging Face model card metadata says license: apache-2.0; ClearerVoice-Studio is "
                          "Apache-2.0 and the SpEx+ source file carries an MIT header. The training data (WSJ0) is "
                          "licensed separately by the LDC; this record does not assess that.",
        "checked": "HF README.md front matter 'license: apache-2.0'; LICENSE of ClearerVoice-Studio @ 6b3774d.",
    },
}

PACKAGES = ("torch", "torchaudio", "numpy", "scipy", "soundfile", "speechbrain", "hyperpyyaml", "pyyaml",
            "wespeaker", "silero-vad", "onnxruntime", "kaldiio", "pystoi", "pesq", "huggingface-hub", "setuptools")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)).replace("\\", "/"): sha256(p)
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def package_versions() -> dict[str, str]:
    W.activate_overlap_site()
    from ..voice.weights import activate_site
    activate_site()
    out = {}
    for name in PACKAGES:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "not installed"
    out["python"] = platform.python_version()
    out["platform"] = platform.platform()
    return out


def readiness_record(home: Path | None = None, names=("wesep_bsrnn", "usef_tse", "spexplus")) -> dict:
    rec = {"packages": package_versions(), "candidates": {}}
    for n in names:
        info, f = INFO[n], FACTS[n]
        wd, cd = W.weights_dir(n, home), W.code_dir(n, home)
        missing = W.missing_files(n, home)
        code_hashes = _tree_hashes(cd) if cd.is_dir() else {}
        rec["candidates"][n] = {
            "title": info.title, "ready": not missing, "missing": missing,
            "weights_source": f["weights_source"], "code_source": f["code_source"],
            "weight_file_sha256": {p.name: sha256(p) for p in sorted(wd.glob("*"))
                                   if p.is_file() and p.name != W.COMPLETE_MARKER} if wd.is_dir() else {},
            "weight_file_bytes": {p.name: p.stat().st_size for p in sorted(wd.glob("*"))
                                  if p.is_file() and p.name != W.COMPLETE_MARKER} if wd.is_dir() else {},
            "code_files_sha256": code_hashes,
            "enrollment_feed": f["enrollment_feed"], "model_sample_rate_hz": info.model_rate,
            "code_licence": info.code_licence, "weights_licence": info.weights_licence,
            "licence_status": f["licence_status"], "licence_reason": f["licence_reason"],
            "licence_checked": f["checked"],
            "approved_for_deployment": False,
            "note": ("never approved: " + f["licence_status"]) if f["licence_status"] in NOT_APPROVED
            else "weights licence permits use; training-data and product licence review still open",
        }
    return rec


def main(argv=None) -> int:      # pragma: no cover - convenience
    import json
    print(json.dumps(readiness_record(), indent=1))
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
