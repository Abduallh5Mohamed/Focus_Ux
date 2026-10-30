"""Score a voice-pipeline run on ground-truth mixes.

Mix folder (from three_speaker_set.py --solo-dir): <mix>/mix.wav, ref_<spk>.wav, truth.json.
Run folder: <run>/<mix>/<target>/{timeline.json, diarization.json, gated_baseline.wav, report.json}.
Numbers are computed only from files a real run wrote.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

from .audio import aligned_si_sdr, load_audio
from .voice_metrics import der, gate_metrics


def _by_speaker(items) -> dict:
    out: dict = {}
    for t in items:
        out.setdefault(t["speaker"], []).append((t["start"], t["end"]))
    return out


def score_target(mix_dir: Path, run_dir: Path, target: str) -> dict:
    truth = json.loads((mix_dir / "truth.json").read_text("utf-8"))
    ref_segs = {s: [tuple(x) for x in v] for s, v in truth["segments"].items()}
    total = truth["seconds"]
    diar = json.loads((run_dir / "diarization.json").read_text("utf-8"))
    timeline = json.loads((run_dir / "timeline.json").read_text("utf-8"))
    report = json.loads((run_dir / "report.json").read_text("utf-8"))
    passed = [(r["start"], r["end"]) for r in timeline if r["label"] == "target"]
    others = [seg for s, v in ref_segs.items() if s != target for seg in v]
    row = {"target": target, "diarization": der(ref_segs, _by_speaker(diar["turns"]), total),
           "gate": gate_metrics(passed, ref_segs[target], others, total),
           "labels_s": {k: round(sum(r["end"] - r["start"] for r in timeline if r["label"] == k), 2)
                        for k in ("target", "other", "uncertain")},
           "rtf": report["timing"]["real_time_factor"],
           "peak_vram_mib": report["timing"]["peak_vram_mib"],
           "oracle_diarization": bool(report.get("oracle_diarization", False))}
    mix, ref = load_audio(mix_dir / "mix.wav"), load_audio(mix_dir / f"ref_{target}.wav")
    est = load_audio(run_dir / "gated_baseline.wav")
    n = min(len(mix), len(est), len(ref))
    s_est = aligned_si_sdr(est[:n].copy(), ref[:n].copy())[0]
    s_mix = aligned_si_sdr(mix[:n].copy(), ref[:n].copy())[0]
    row["si_sdri_db"] = round(s_est - s_mix, 3)
    row["length_ok"] = len(est) == len(mix)
    return row


def evaluate_voice_run(mixes: str | Path, run: str | Path) -> dict:
    mixes, run = Path(mixes), Path(run)
    rows = []
    for mix_dir in sorted(p for p in mixes.iterdir() if (p / "truth.json").is_file()):
        for tdir in sorted(p for p in (run / mix_dir.name).glob("*") if (p / "report.json").is_file()):
            row = score_target(mix_dir, tdir, tdir.name)
            row["mix"] = mix_dir.name
            rows.append(row)
    if not rows:
        raise FileNotFoundError(f"no scored targets under {run}")
    avg = lambda f: (lambda v: round(mean(v), 4) if v else None)([x for x in map(f, rows) if x is not None])
    return {"n_targets": len(rows),
            "summary": {
                "diarization_error_rate": avg(lambda r: r["diarization"]["der"]),
                "wrong_person_rate": avg(lambda r: r["gate"]["wrong_person_rate"]),
                "target_retention": avg(lambda r: r["gate"]["target_retention"]),
                "wrong_share_of_output": avg(lambda r: r["gate"]["wrong_share_of_output"]),
                "si_sdri_db_gated_baseline": avg(lambda r: r["si_sdri_db"]),
                "real_time_factor": avg(lambda r: r["rtf"]),
                "peak_vram_mib": max((r["peak_vram_mib"] for r in rows if r["peak_vram_mib"] is not None), default=None),
                "oracle_diarization": any(r["oracle_diarization"] for r in rows)},
            "rows": rows}


def region_scores(mixes: str | Path, run: str | Path, only: list[str] | None = None) -> dict:
    """Target/other score lists from the solo regions of a run, labelled by ground truth
    (a region belongs to the speaker with the most true speech in it, if that speech
    covers at least 80% of the region and nobody else speaks). Used to calibrate thresholds."""
    from .voice_metrics import to_frames
    mixes, run = Path(mixes), Path(run)
    tgt, oth = [], []
    for mix_dir in sorted(p for p in mixes.iterdir() if (p / "truth.json").is_file()):
        if only and mix_dir.name not in only:
            continue
        truth = json.loads((mix_dir / "truth.json").read_text("utf-8"))
        total = truth["seconds"]
        frames = {s: to_frames(v, total) for s, v in truth["segments"].items()}
        for tdir in sorted(p for p in (run / mix_dir.name).glob("*") if (p / "report.json").is_file()):
            for r in json.loads((tdir / "timeline.json").read_text("utf-8")):
                if r["score"] is None:
                    continue
                a, b = int(r["start"] / 0.01), int(r["end"] / 0.01)
                active = {s: f[a:b].mean() for s, f in frames.items()}
                solo = [s for s, v in active.items() if v >= 0.8]
                if len(solo) != 1 or any(v > 0.05 for s, v in active.items() if s != solo[0]):
                    continue
                (tgt if solo[0] == tdir.name else oth).append(r["score"])
    return {"target": tgt, "other": oth}
