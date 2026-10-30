"""Selection gate over the 3-speaker set (see three_speaker_set.py).

A winner needs: median SI-SDRi >= 10 dB, a recorded listening pass on the real
hard clip, and a 15 s clip in <= 5 s after warm-up. Record the listening result
yourself in a JSON file, e.g. {"av_mossformer2": true, "dolphin": false}.

  python product/tools/engine_gate.py --set mixes --listening listening.json --out gate-out
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from engine_harness import Harness  # noqa: E402

ENGINES = ("dolphin", "av_mossformer2", "separate_select")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", required=True, type=Path, help="output folder of three_speaker_set.py")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--listening", type=Path, help="JSON {engine: true/false}")
    ap.add_argument("--focus", default="A:/focus")
    ap.add_argument("--engines", nargs="+", default=list(ENGINES), choices=ENGINES)
    args = ap.parse_args()

    import soundfile as sf
    from focus_ml.engine_report import EngineSetResult, gate_verdict, render_gate_html, si_sdri

    listening = json.loads(args.listening.read_text()) if args.listening else {}
    mixes = sorted(p for p in args.set.iterdir() if (p / "meta.json").is_file())
    if len(mixes) < 10:
        raise SystemExit("the 3-speaker set needs at least 10 mixes")
    harness = Harness(args.focus)
    results = []
    for name in args.engines:
        res = EngineSetResult(name, [], [], 0.0)
        warmed = False
        for d in mixes:
            meta = json.loads((d / "meta.json").read_text())
            video = str(d / "mix.mp4")
            mix = sf.read(d / "mix.wav", dtype="float32")[0]
            try:
                faces = harness.faces_left_to_right(d.name, video)
                if len(faces) != 3:
                    raise RuntimeError(f"expected 3 faces, found {len(faces)}")
                for pos in range(3):
                    with tempfile.TemporaryDirectory(prefix="focus-gate-") as tmp:
                        result, wall = harness.run(name, d.name, video, faces[pos], tmp)
                        est = sf.read(result.wav_path, dtype="float32")[0]
                    ref = sf.read(d / f"ref_{pos}.wav", dtype="float32")[0]
                    res.si_sdri_db.append(si_sdri(est, mix, ref))
                    if warmed:  # the first run of an engine includes model loading
                        res.warm_wall_s.append(wall)
                        res.clip_seconds = max(res.clip_seconds, meta["seconds"])
                    warmed = True
            except Exception as exc:
                res.errors += 1
                print(f"{name} {d.name}: {type(exc).__name__}: {getattr(exc, 'message', exc)}")
        print(f"{name}: {len(res.si_sdri_db)} targets scored, {res.errors} failed mixes", flush=True)
        results.append(res)
    verdict = gate_verdict(results, listening)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gate.json").write_text(json.dumps(verdict, indent=1))
    (args.out / "gate.html").write_text(render_gate_html(verdict), encoding="utf-8")
    print(verdict["message"])
    print("Report:", args.out / "gate.html")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
