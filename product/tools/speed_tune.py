"""Measure one speed change before and after, and decide: adopt / reject / inconclusive.

  python product/tools/speed_tune.py --dataset D --out reports/tune_prefetch \
      --candidate '{"prefetch": true}' --baseline '{"prefetch": false}'

Both variants run the whole dataset in this process, one after the other (baseline first);
repeat with the order swapped to expose warm-up or thermal bias. The decision is
``focus_eval.gate``: quality must not drop on ANY target, every clip needs its own RTF,
the RTF must be <= the target and faster than the baseline's. Run on the RTX 3050 laptop;
anywhere else the verdict says nothing about the laptop.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_runner  # noqa: E402
from focus_eval.compare import Thresholds  # noqa: E402
from focus_eval.dataset import load_dataset  # noqa: E402
from focus_eval.evaluate import evaluate  # noqa: E402
from focus_eval.gate import DEFAULT_RTF_TARGET, decide  # noqa: E402


def _settings(arg: str) -> dict:
    p = Path(arg)
    return json.loads(p.read_text(encoding="utf-8") if p.is_file() else arg)


def overlap_free(ds):
    """Keep only clips with no simultaneous speech. The gated baseline mutes overlap, which the strict
    adoption policy (no silence where the target speaks) always rejects; those clips cannot judge a
    speed change."""
    from focus_eval.audio import load_audio
    from focus_eval.final_report import overlap_type
    ds.clips = [c for c in ds.clips if c.status != "ready" or overlap_type(
        {s.id: load_audio(ds.path(s.ref_audio)) for s in c.speakers}) == "none"]
    return ds


def tune(ds, out: Path, engine_factory, baseline: dict, candidate: dict, rtf_target: float) -> dict:
    reports = {}
    for name, over in (("baseline", baseline), ("candidate", candidate)):
        settings = {**eval_runner.DEFAULT_SETTINGS, "visibility_check": False, "verification": False, **over}
        engine = engine_factory(settings)
        eval_runner.produce_run(ds, out / name, engine, settings, label=name)
        reports[name] = evaluate(ds, out / name)
        (out / f"{name}.report.json").write_text(json.dumps(reports[name], indent=1, ensure_ascii=False), encoding="utf-8")
    verdict = decide(reports["baseline"], reports["candidate"], Thresholds(), rtf_target)
    verdict["settings"] = {"baseline": baseline, "candidate": candidate}
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, ensure_ascii=False), encoding="utf-8")
    return verdict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline", default="{}", help="JSON or file overriding the default settings")
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--rtf-target", type=float, default=DEFAULT_RTF_TARGET)
    ap.add_argument("--keep-overlap-clips", action="store_true",
                    help="do not drop clips with overlapping speech (the verdict will usually be inconclusive)")
    a = ap.parse_args(argv)
    ds = load_dataset(a.dataset)
    if not a.keep_overlap_clips:
        ds = overlap_free(ds)
    verdict = tune(ds, Path(a.out), eval_runner.build_real_engine,
                   _settings(a.baseline), _settings(a.candidate), a.rtf_target)
    print(f"VERDICT: {verdict['verdict'].upper()}  RTF {verdict['rtf']}")
    print(*[f"  - {r}" for r in verdict["reasons"]], sep="\n")
    return {"adopt": 0, "reject": 1, "inconclusive": 3}[verdict["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
