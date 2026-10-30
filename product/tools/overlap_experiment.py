"""Real target-speaker-extraction experiment: readiness record, comparison run, report.

  python product/tools/overlap_experiment.py readiness --out product/experiments/real_tse/results
  python product/tools/overlap_experiment.py run --set <overlap_set.py --layout experiment output> \
         --out product/experiments/real_tse/results [--candidates wesep_bsrnn usef_tse spexplus] [--device auto]
  python product/tools/overlap_experiment.py render --out product/experiments/real_tse/results \
         [--conclusion product/experiments/real_tse/conclusion.md]

`run` runs every candidate through the same mixes, enrollments, settings and seed and writes report.json and the
listening folders. `render` (re)builds report.html from report.json, readiness.json and the conclusion text,
without running any model. Nothing is downloaded: set up the candidates first with setup_overlap.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "eval"), str(ROOT / "product" / "packages" / "ml")]

DEFAULT = ("wesep_bsrnn", "usef_tse", "spexplus")


def cmd_readiness(a):
    from focus_ml.overlap.experiment_readiness import readiness_record
    rec = readiness_record()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "readiness.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    for n, c in rec["candidates"].items():
        print(f"{n}: ready={c['ready']} licence={c['licence_status']}")


def cmd_run(a):
    from focus_ml.overlap.candidates import INFO, build_candidate
    from focus_ml.overlap.experiment import run_experiment
    from focus_ml.overlap.experiment_readiness import package_versions
    from focus_ml.overlap.hybrid import HybridConfig
    from focus_ml.voice.embedder import build_embedder
    from focus_ml.voice.gpu import resolve_device

    device = resolve_device(a.device)
    embedder = build_embedder(a.embedder, device)

    def build(name):
        return build_candidate(name, device=device, fp16=not a.no_fp16, embedder=embedder)

    threads = None
    try:
        import torch
        threads = torch.get_num_threads()
    except ImportError:
        pass
    basis = {"data": "LibriSpeech dev-clean solo recordings mixed with exact references (CC-BY-4.0)",
             "device": device, "regions": "oracle (ground truth from the mixing plan)", "seed": a.seed,
             "cpu_threads": threads, "embedder": a.embedder, "versions": package_versions(),
             "caveat": "English, non-Egyptian read speech. Not an Egyptian-Arabic or RTX 3050 result."}
    cfg = HybridConfig(batch_size=a.batch_size)
    report = run_experiment(a.set, a.out, a.candidates, build, embedder, basis, INFO, cfg, a.max_mixes)
    print("Wrote", a.out / "report.json")
    return report


def cmd_render(a):
    from focus_ml.overlap.experiment_report import render_html
    report = json.loads((a.out / "report.json").read_text("utf-8"))
    readiness = json.loads((a.out / "readiness.json").read_text("utf-8"))
    conclusion = a.conclusion.read_text("utf-8") if a.conclusion and a.conclusion.is_file() else ""
    rule = (a.rule.read_text("utf-8") if a.rule and a.rule.is_file() else "")
    commands = a.commands.read_text("utf-8") if a.commands and a.commands.is_file() else ""
    (a.out / "report.html").write_text(render_html(report, readiness, conclusion, rule, commands), encoding="utf-8")
    print("Wrote", a.out / "report.html")


def main():
    exp = ROOT / "product" / "experiments" / "real_tse"
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("readiness")
    r.add_argument("--out", required=True, type=Path)
    r.set_defaults(fn=cmd_readiness)
    p = sub.add_parser("run")
    p.add_argument("--set", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--candidates", nargs="+", default=list(DEFAULT), choices=DEFAULT)
    p.add_argument("--embedder", default="ecapa")
    p.add_argument("--device", default="auto")
    p.add_argument("--no-fp16", action="store_true")
    p.add_argument("--batch-size", type=int)
    p.add_argument("--max-mixes", type=int)
    p.add_argument("--seed", type=int, default=83, help="recorded; the seed itself is used by overlap_set.py")
    p.set_defaults(fn=cmd_run)
    g = sub.add_parser("render")
    g.add_argument("--out", required=True, type=Path)
    g.add_argument("--conclusion", type=Path, default=exp / "conclusion.md")
    g.add_argument("--rule", type=Path, default=exp / "COMPARISON_RULE.md")
    g.add_argument("--commands", type=Path, default=exp / "RTX3050_COMMANDS.md")
    g.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(getattr(exc, "message", exc)), file=sys.stderr)
        sys.exit(1)
