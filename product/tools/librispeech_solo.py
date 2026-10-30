"""Build the solo-recording folder for overlap_set.py from a LibriSpeech dev-clean archive.

  python product/tools/librispeech_solo.py --archive dev-clean.tar.gz --out solo \
         --speakers 84 1462 1673 1919 174 251 422 652 --seconds 60

LibriSpeech is CC-BY-4.0 (Panayotov et al.), English, read speech. NOT Egyptian Arabic.
Per speaker, utterances are taken in file order and concatenated into <speaker>.wav
(16 kHz mono) until --seconds is reached; speakers.json records the gender.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "ml")]


def build(archive: Path, out: Path, speakers: list[str], seconds: float) -> dict:
    import soundfile as sf

    from focus_ml.isolation_engines import write_wav
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        members = [f"LibriSpeech/dev-clean/{s}" for s in speakers] + ["LibriSpeech/SPEAKERS.TXT"]
        subprocess.run(["tar", "-xzf", str(archive), "-C", tmp, *members], check=True)
        gender = {}
        for line in (Path(tmp) / "LibriSpeech" / "SPEAKERS.TXT").read_text("utf-8").splitlines():
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[0] in speakers:
                gender[parts[0]] = parts[1]
        info = {}
        for s in speakers:
            files = sorted((Path(tmp) / "LibriSpeech" / "dev-clean" / s).rglob("*.flac"))
            chunks, total, used = [], 0.0, []
            for f in files:
                x, sr = sf.read(str(f), dtype="float32")
                if sr != 16000:
                    raise ValueError(f"{f.name} is {sr} Hz, expected 16 kHz")
                chunks.append(x.reshape(-1))
                used.append(f.stem)
                total += len(x) / sr
                if total >= seconds:
                    break
            if total < seconds:
                raise ValueError(f"speaker {s} has only {total:.1f} s")
            write_wav(str(out / f"{s}.wav"), np.concatenate(chunks), 16000)
            info[s] = {"gender": gender.get(s), "seconds": round(total, 1), "utterances": used}
    (out / "speakers.json").write_text(json.dumps(
        {"corpus": "LibriSpeech dev-clean", "licence": "CC-BY-4.0", "language": "English (read speech), non-Egyptian",
         "speakers": info}, indent=1), encoding="utf-8")
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--speakers", nargs="+", required=True)
    ap.add_argument("--seconds", type=float, default=60.0)
    a = ap.parse_args()
    info = build(a.archive, a.out, a.speakers, a.seconds)
    print(f"Wrote {len(info)} speakers to {a.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
