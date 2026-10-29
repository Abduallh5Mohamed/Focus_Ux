"""Command line: validate / evaluate / compare / init-template."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import SCHEMA_VERSION
from .compare import DEFAULT_CER_INCREASE, DEFAULT_SI_SDRI_DROP_DB, Thresholds, compare_reports
from .dataset import STATUS_TEMPLATE, DatasetError, load_dataset, validate_dataset
from .evaluate import DEFAULT_AMBIGUOUS_MARGIN_DB, evaluate

TEMPLATE_SCENARIOS = [
    ("baseline_01", ["baseline"], "two speakers, both faces clear and still"),
    ("baseline_02", ["baseline"], "two speakers, both faces clear and still"),
    ("head_motion_01", ["head_motion"], "target turns and nods while talking"),
    ("head_motion_02", ["head_motion"], "target near the frame edge, moving"),
    ("face_disappears_01", ["face_disappears"], "target face leaves frame or is covered mid-clip"),
    ("face_disappears_02", ["face_disappears"], "target looks away for several seconds while speaking"),
    ("similar_voices_01", ["similar_voices"], "two speakers of the same sex and similar pitch"),
    ("similar_voices_02", ["similar_voices"], "two speakers of the same sex and similar pitch"),
    ("overlap_01", ["overlap"], "speakers talk over each other for several seconds"),
    ("overlap_02", ["overlap", "head_motion"], "overlapping speech with head movement"),
]


def make_template() -> dict:
    clips = []
    for cid, tags, note in TEMPLATE_SCENARIOS:
        base = f"clips/{cid}"
        clips.append({
            "id": cid,
            "status": STATUS_TEMPLATE,
            "scenario": note,
            "tags": tags,
            "video": f"{base}/video.mp4",
            "mix_audio": f"{base}/mix.wav",
            "source": {"description": "", "url": "", "license": "", "recorded_by": ""},
            "speakers": [
                {"id": sid, "ref_audio": f"{base}/{sid}_ref.wav", "transcript": f"{base}/{sid}.txt",
                 "transcript_status": "human_verified"}
                for sid in ("a", "b")
            ],
            "targets": ["a", "b"],
        })
    return {"schema_version": SCHEMA_VERSION, "dataset_id": "egyptian-eval-v0", "clips": clips}


def _fmt(v, nd=3):
    return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def render_report(rep: dict) -> str:
    s = rep["summary"]
    wp, tv, tp = s["wrong_person"], s["text_verified"], s["text_provisional"]
    lines = [
        f"Run: {rep['run_label']}   Dataset: {rep['dataset_id']}",
        f"Targets: {s['n_targets']} (audio ok {s['n_audio_ok']}, missing {s['n_missing_audio']}, "
        f"error {s['n_audio_error']}); template clips skipped: {len(rep['not_ready_clips'])}",
        f"Wrong person: {wp['wrong']}/{wp['evaluable']} (rate {_fmt(wp['rate'])}), ambiguous {wp['ambiguous']}",
        f"SI-SDRi dB: mean {_fmt(s['si_sdri_db']['mean'], 2)}, median {_fmt(s['si_sdri_db']['median'], 2)}",
        f"Text, human-verified refs: n={tv['n_scored']} CER {_fmt(tv.get('cer'))} WER {_fmt(tv.get('wer'))}",
        f"Text, PROVISIONAL refs (not final): n={tp['n_scored']} CER {_fmt(tp.get('cer'))} WER {_fmt(tp.get('wer'))}",
        f"Missing hypothesis transcripts: {s['n_text_missing_hypothesis']}",
    ]
    for tag, ts in rep["by_tag"].items():
        w = ts["wrong_person"]
        lines.append(f"  [{tag}] n={ts['n_targets']} wrong {w['wrong']}/{w['evaluable']} "
                     f"SI-SDRi {_fmt(ts['si_sdri_db']['mean'], 2)} CER {_fmt(ts['text_verified'].get('cer'))}")
    return "\n".join(lines)


def render_compare(cmp: dict) -> str:
    lines = [f"Baseline: {cmp['baseline']}  Candidate: {cmp['candidate']}  compared: {cmp['n_compared']}"]
    lines += [f"WARNING: {w}" for w in cmp["warnings"]]
    lines.append(f"scored in both: {cmp['n_scored_in_both']}")
    if cmp["status"] == "inconclusive":
        lines += [f"INCONCLUSIVE: {r}" for r in cmp["inconclusive_reasons"]]
        lines.append("RESULT: INCONCLUSIVE (no pass/fail verdict can be given)")
        for r in cmp["regressions"]:
            lines.append(f"  - (unverified) {r['kind']} {r.get('clip_id', 'overall')}")
        return "\n".join(lines)
    if cmp["only_in_baseline"] or cmp["only_in_candidate"]:
        lines.append(f"Only in baseline: {len(cmp['only_in_baseline'])}, only in candidate: {len(cmp['only_in_candidate'])}")
    if cmp["ok"]:
        lines.append("RESULT: no regressions")
    else:
        lines.append(f"RESULT: {len(cmp['regressions'])} REGRESSION(S)")
        for r in cmp["regressions"]:
            detail = {k: v for k, v in r.items() if k not in ("kind", "clip_id", "speaker_id")}
            who = f"{r['clip_id']}/{r['speaker_id']}" if "clip_id" in r else "overall"
            lines.append(f"  - {r['kind']} {who} {detail}")
    return "\n".join(lines)


def _write_json(path: str | None, obj: dict) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="focus_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="check a dataset manifest and its files")
    p.add_argument("--dataset", required=True)

    p = sub.add_parser("evaluate", help="score a run against a dataset")
    p.add_argument("--dataset", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--out", help="write the JSON report here")
    p.add_argument("--ambiguous-margin-db", type=float, default=DEFAULT_AMBIGUOUS_MARGIN_DB)

    p = sub.add_parser("compare", help="compare two JSON reports")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--si-sdri-drop-db", type=float, default=DEFAULT_SI_SDRI_DROP_DB)
    p.add_argument("--cer-increase", type=float, default=DEFAULT_CER_INCREASE)
    p.add_argument("--include-provisional", action="store_true")
    p.add_argument("--out")

    p = sub.add_parser("init-template", help="write a 10-clip template manifest")
    p.add_argument("--out", required=True, help="dataset directory to create")

    a = ap.parse_args(argv)
    try:
        if a.cmd == "init-template":
            out = Path(a.out)
            if (out / "manifest.json").exists():
                print(f"refusing to overwrite {out / 'manifest.json'}", file=sys.stderr)
                return 2
            out.mkdir(parents=True, exist_ok=True)
            (out / "manifest.json").write_text(
                json.dumps(make_template(), ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"wrote {out / 'manifest.json'}")
            return 0
        if a.cmd == "validate":
            problems = validate_dataset(load_dataset(a.dataset))
            for line in problems:
                print(line)
            hard = [p for p in problems if "still a template" not in p]
            print(f"{len(problems)} issue(s), {len(hard)} blocking")
            return 1 if hard else 0
        if a.cmd == "evaluate":
            ds = load_dataset(a.dataset)
            blocking = [p for p in validate_dataset(ds) if "still a template" not in p]
            if blocking:
                print("dataset has blocking problems; run `validate`:", *blocking[:10], sep="\n  ", file=sys.stderr)
                return 2
            rep = evaluate(ds, a.run, a.ambiguous_margin_db)
            _write_json(a.out, rep)
            print(render_report(rep))
            return 0
        if a.cmd == "compare":
            base = json.loads(Path(a.baseline).read_text(encoding="utf-8"))
            cand = json.loads(Path(a.candidate).read_text(encoding="utf-8"))
            cmp = compare_reports(base, cand, Thresholds(a.si_sdri_drop_db, a.cer_increase, a.include_provisional))
            _write_json(a.out, cmp)
            print(render_compare(cmp))
            return {"pass": 0, "regression": 1, "inconclusive": 3}[cmp["status"]]
    except (DatasetError, FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2
