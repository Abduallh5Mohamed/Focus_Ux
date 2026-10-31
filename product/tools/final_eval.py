"""One command: run the whole Egyptian evaluation dataset and write the final report.

  python product/tools/final_eval.py --dataset product/datasets/egyptian_eval --out reports/final \
      [--settings settings.json] [--stress noise_10db,reverb_rt60_0.4s] [--listening-seed 7]

Writes <out>/run (audio, timelines, run.json with settings + environment), <out>/report.json,
<out>/report.md and <out>/listening (blind kit; key.json stays with the organiser).
The report is reproducible from the manifest and the recorded settings: re-run with the same
dataset fingerprint and the settings stored in report.json (reproducibility.settings).
The report states plainly when it was NOT produced on an NVIDIA GPU.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_runner  # noqa: E402
from focus_eval.dataset import load_dataset, validate_dataset  # noqa: E402
from focus_eval.final_report import build_report, render_markdown  # noqa: E402
from focus_eval.listening import build_kit  # noqa: E402


def run_final(dataset: str, out: str, engine, settings: dict, *, listening_seed: int | None = None,
              command: str | None = None) -> dict:
    ds = load_dataset(dataset)
    blocking = [p for p in validate_dataset(ds) if "still a template" not in p]
    if blocking:
        raise ValueError("dataset has blocking problems: " + "; ".join(blocking[:5]))
    if not any(c.status == "ready" for c in ds.clips):
        raise ValueError("the dataset has no clip with status 'ready'; there is nothing to evaluate")
    out_dir = Path(out)
    meta = eval_runner.produce_run(ds, out_dir / "run", engine, settings, label=out_dir.name, command=command)
    report = build_report(ds, out_dir / "run")
    report["run_failures"] = meta["failures"]
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    if listening_seed is not None:
        pairs = [{"clip_id": c.id, "target": t, "original": str(ds.path(c.mix_audio)), "reference": str(ds.path(c.speaker(t).ref_audio)),
                  "processed": str(out_dir / "run" / c.id / f"{t}.wav")}
                 for c in ds.clips if c.status == "ready" for t in c.targets
                 if (out_dir / "run" / c.id / f"{t}.wav").is_file()]
        report["listening_kit"] = build_kit(pairs, out_dir / "listening", seed=listening_seed)
        (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--settings", help="JSON file overriding eval_runner.DEFAULT_SETTINGS")
    ap.add_argument("--stress", default="", help="comma-separated synthetic conditions (focus_eval.stress)")
    ap.add_argument("--listening-seed", type=int)
    ap.add_argument("--skip-visibility", action="store_true")
    a = ap.parse_args(argv)
    settings = dict(eval_runner.DEFAULT_SETTINGS)
    if a.settings:
        settings.update(json.loads(Path(a.settings).read_text(encoding="utf-8")))
    if a.stress:
        settings["stress"] = [s for s in a.stress.split(",") if s]
    if a.skip_visibility:
        settings["visibility_check"] = False
    engine = eval_runner.build_real_engine(settings)
    try:
        report = run_final(a.dataset, a.out, engine, settings, listening_seed=a.listening_seed,
                           command=" ".join(["python", "product/tools/final_eval.py", *sys.argv[1:]]))
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_markdown(report))
    if report["run_failures"]:
        print(f"{len(report['run_failures'])} target(s) failed; see report.json run_failures", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
