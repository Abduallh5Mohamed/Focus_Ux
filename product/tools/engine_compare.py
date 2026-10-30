"""Run every isolation engine on the SAME hard clip and the SAME chosen face,
then write a local HTML page with an audio player per result, stage timings and
(when a clean reference exists, e.g. gt5) SI-SDRi.

  python product/tools/engine_compare.py --video clip.mp4 --face 2 --out compare-out
  (--face is the 1-based position from the left in the first frame)

Run it with the original Python. Nothing is uploaded or downloaded.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from engine_harness import Harness  # noqa: E402

ENGINES = ("dolphin", "av_mossformer2", "separate_select")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", required=True)
    ap.add_argument("--face", type=int, required=True, help="1-based, from the left")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--focus", default="A:/focus")
    ap.add_argument("--engines", nargs="+", default=list(ENGINES), choices=ENGINES)
    ap.add_argument("--reference", help="clean WAV of the chosen speaker (optional)")
    args = ap.parse_args()

    import soundfile as sf
    from focus_ml.engine_report import EngineRun, render_compare_html, si_sdri

    args.out.mkdir(parents=True, exist_ok=True)
    harness = Harness(args.focus)
    video = str(Path(args.video).resolve())
    faces = harness.faces_left_to_right("compare", video)
    if not 1 <= args.face <= len(faces):
        raise SystemExit(f"--face must be 1..{len(faces)} (found {len(faces)} faces)")
    face_id = faces[args.face - 1]

    mix_path = args.out / "original_mix.wav"
    with tempfile.TemporaryDirectory() as tmp:
        mix_extract = harness.local.adapter._extract_audio(video, tmp)
        shutil.copyfile(mix_extract, mix_path)
    mix, _ = sf.read(mix_path, dtype="float32")
    ref = sf.read(args.reference, dtype="float32")[0] if args.reference else None

    runs = []
    for name in args.engines:
        run = EngineRun(engine=name)
        try:
            with tempfile.TemporaryDirectory(prefix="focus-compare-") as tmp:
                _, run.wall_s = harness.run(name, "compare", video, face_id, tmp)  # cold
            with tempfile.TemporaryDirectory(prefix="focus-compare-") as tmp:
                result, run.warm_wall_s = harness.run(name, "compare", video, face_id, tmp)
                target = args.out / f"{name}.wav"
                shutil.copyfile(result.wav_path, target)
                run.wav_name, run.timings = target.name, result.timings
                run.warnings, run.details = result.warnings, result.details
                if ref is not None:
                    est = sf.read(target, dtype="float32")[0]
                    run.si_sdri_db = si_sdri(est, mix, ref)
        except Exception as exc:  # report, keep comparing the others
            run.error = f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
        print(f"{name}: {run.error or 'ok'}", flush=True)
        runs.append(run)
    page = args.out / "compare.html"
    page.write_text(render_compare_html(Path(video).name, mix_path.name, runs, ref is not None),
                    encoding="utf-8")
    print("Open", page)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
