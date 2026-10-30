"""Bake-off: every candidate through the hybrid on the same mixes, scored per
region category, with blind-listening audio. Region labels are ground truth
(oracle) so the extractor is measured, not the diarizer.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import numpy as np

from ..isolation_engines import read_wav, write_wav
from ..voice.embedder import embed_segments
from ..voice.extractor import GatedBaseline
from ..voice.types import OTHER, SAMPLE_RATE, TARGET, UNCERTAIN, LabelledRegion, Segment, Voiceprint
from . import metrics as M
from .base import BlockedError
from .hybrid import OVERLAP_REASON, HybridConfig, HybridExtractor
from .report import blind_labels

LIMITATIONS = [
    "Region boundaries are ground truth from the mixing plan (turn level, pauses inside turns are not "
    "removed); a real diarizer will be less exact, which the next task measures end to end.",
    "SI-SDRi is clamped to [-30, 50] dB so muted output counts as -30 dB instead of minus infinity.",
    "Target retention is the clipped projection of the output on the clean reference (0 = absent, "
    "1 = present at the right level); a correct but quiet output scores below 1.",
    "Wrong-person rate counts only regions where the output is not muted; muted share is reported next to it.",
    "The voiceprint check uses the embedder's target threshold, calibrated on non-Egyptian speech; "
    "recalibrate on Egyptian recordings.",
    "Models trained on English (WSJ0-2mix, LibriMix, AMI) are used on Arabic speech without adaptation.",
]


def make_voiceprint(embedder, enrollment) -> Voiceprint:
    dur = len(enrollment) / SAMPLE_RATE
    vec, used = embed_segments(embedder, enrollment, [Segment(0.0, dur)])
    if vec is None:
        raise ValueError("the enrollment recording is too short to measure a voice")
    return Voiceprint([float(v) for v in vec], embedder.name, used, {"kind": "voice_file"})


def labelled_regions(regions: list[dict], target: str) -> list[LabelledRegion]:
    out = []
    for r in regions:
        act = r["active"]
        if len(act) >= 2:
            out.append(LabelledRegion(r["start"], r["end"], UNCERTAIN, None, None, OVERLAP_REASON))
        elif act == [target]:
            out.append(LabelledRegion(r["start"], r["end"], TARGET, target, 1.0, "oracle"))
        else:
            out.append(LabelledRegion(r["start"], r["end"], OTHER, act[0], 0.0, "oracle"))
    return out


def _load(path) -> np.ndarray:
    x, sr = read_wav(str(path))
    if sr != SAMPLE_RATE:
        raise ValueError(f"{path} is {sr} Hz; 16 kHz mono WAV is required")
    return x.astype(np.float32)


def _timing(reports: list[dict]) -> dict:
    ov_s = sum(r["overlap_seconds"] for r in reports)
    ex_s = sum(r["extract_seconds"] for r in reports)
    wins = sum(r["windows"] for r in reports)
    peaks = [r["peak_vram_mib"] for r in reports if r["peak_vram_mib"] is not None]
    return {"windows": wins, "overlap_seconds": round(ov_s, 2), "extract_seconds": round(ex_s, 3),
            "rtf_overlap": round(ex_s / ov_s, 4) if ov_s else None,
            "seconds_per_window": round(ex_s / wins, 4) if wins else None,
            "peak_vram_mib": max(peaks) if peaks else None,
            "fp16": reports[0]["fp16"] if reports else None,
            "fp16_fallbacks": sum(r["fp16_fallbacks"] for r in reports),
            "batch_sizes": sorted({r["batch_size"] for r in reports if r["batch_size"]}),
            "oom_backoffs": sum(r["oom_backoffs"] for r in reports),
            "uncertain_muted_seconds": round(sum(r["uncertain_muted_seconds"] for r in reports), 2)}


def _blocked_record(exc: Exception) -> dict:
    if isinstance(exc, BlockedError):
        return exc.as_record()
    tail = traceback.format_exception_only(type(exc), exc)[-1].strip()
    return {"kind": "broken_code", "message": "the candidate failed while running", "evidence": tail}


def run_bakeoff(set_dir, out_dir, names, build, embedder, basis: dict, info: dict,
                hybrid_config: HybridConfig | None = None, real_dir=None,
                listen_mixes: int = 6, max_mixes: int | None = None) -> dict:
    """``build(name)`` returns an OverlapExtractor; ``info`` maps names to CandidateInfo."""
    set_dir, out_dir = Path(set_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mixes = sorted(p for p in set_dir.iterdir() if (p / "meta.json").is_file())[:max_mixes]
    if not mixes:
        raise FileNotFoundError(f"no mixes (meta.json) found in {set_dir}")
    set_info = json.loads((set_dir / "set.json").read_text("utf-8")) if (set_dir / "set.json").is_file() else {}
    basis = {**basis, "language": set_info.get("language", "unknown")}
    prints, enrolls = {}, {}

    def enroll_of(spk):
        if spk not in prints:
            enrolls[spk] = _load(set_dir / "enroll" / f"{spk}.wav")
            prints[spk] = make_voiceprint(embedder, enrolls[spk])
        return enrolls[spk], prints[spk]

    data = []
    for d in mixes:
        meta = json.loads((d / "meta.json").read_text("utf-8"))
        refs = {s: _load(d / f"ref_{s}.wav") for s in {meta["target"], *meta["others"]}}
        data.append((d, meta, _load(d / "mix.wav"), refs))

    base_rows, base_out = [], {}
    gate = GatedBaseline()
    for d, meta, mix, refs in data:
        est = gate.extract(mix, labelled_regions(meta["regions"], meta["target"]))
        base_rows += [{**r, "mix": meta["id"]} for r in M.score_clip(est, mix, refs, meta["target"], meta["regions"])]
        base_out[meta["id"]] = est
    base_agg = M.aggregate(base_rows)

    real = _real_items(real_dir) if real_dir else []
    outputs: dict[str, dict[str, np.ndarray]] = {"gated_baseline": base_out}
    real_out: dict[str, dict[str, np.ndarray]] = {}
    cands: dict[str, dict] = {}
    for name in names:
        ex = build(name)
        rec = {"info": info[name].as_dict(), "blocked": None, "aggregate": {}, "timing": {},
               "overlap": None, "baseline_overlap": None, "rows": [], "clip_si_sdri_db_mean": None}
        try:
            ex.check_ready()
            rows, reports, clip_gain, outs = [], [], [], {}
            for d, meta, mix, refs in data:
                enroll, vp = enroll_of(meta["target"])
                hy = HybridExtractor(ex, vp, enroll, embedder, hybrid_config)
                est = hy.extract(mix, labelled_regions(meta["regions"], meta["target"]))
                reports.append(hy.last_report)
                rows += [{**r, "mix": meta["id"]} for r in M.score_clip(est, mix, refs, meta["target"], meta["regions"])]
                clip_gain.append(M.clip_si_sdri(est, mix, refs[meta["target"]]))
                outs[meta["id"]] = est
            routs = {}
            for item in real:
                hy = HybridExtractor(ex, make_voiceprint(embedder, item["enroll"]), item["enroll"],
                                     embedder, hybrid_config)
                routs[item["name"]] = hy.extract(item["mix"], item["regions"])
            outputs[name] = outs
            for k, v in routs.items():
                real_out.setdefault(k, {})[name] = v
            rec.update(rows=rows, aggregate=M.aggregate(rows), timing=_timing(reports),
                       clip_si_sdri_db_mean=round(float(np.mean(clip_gain)), 3))
            cats = tuple(c for c in M.OVERLAP_CATEGORIES if c in info[name].categories)
            rec["overlap"] = M.pooled_overlap(rec["aggregate"], cats)
            rec["baseline_overlap"] = M.pooled_overlap(base_agg, cats)
        except Exception as exc:       # report, keep comparing the others
            rec["blocked"] = _blocked_record(exc)
        finally:
            try:
                ex.unload()            # one extractor resident at a time
            except Exception:
                pass
        cands[name] = rec
        print(f"{name}: {'BLOCKED ' + rec['blocked']['kind'] if rec['blocked'] else 'ok'}", flush=True)

    summary = {n: {"overlap": c["overlap"], "baseline_overlap": c["baseline_overlap"], "blocked": c["blocked"],
                   "categories": list(c["info"]["categories"])} for n, c in cands.items()}
    decision = M.decide(summary, M.pooled_overlap(base_agg), basis)
    listening = _write_listening(out_dir, data[:listen_mixes], outputs, "mix")
    real_listen = _write_real(out_dir, real, real_out)
    report = {"basis": basis, "set": set_info, "mixes": len(data),
              "baseline": {"aggregate": base_agg, "overlap": M.pooled_overlap(base_agg)},
              "candidates": {n: {k: v for k, v in c.items() if k != "rows"} for n, c in cands.items()},
              "decision": decision, "listening": listening, "real_clips": real_listen,
              "limitations": LIMITATIONS}
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "rows.json").write_text(json.dumps(
        {n: c["rows"] for n, c in cands.items()}, indent=1), encoding="utf-8")
    from .report import render_html
    (out_dir / "report.html").write_text(render_html(report), encoding="utf-8")
    (out_dir / "decision.md").write_text(_decision_md(report), encoding="utf-8")
    return report


def _real_items(real_dir) -> list[dict]:
    items = []
    for wav in sorted(Path(real_dir).glob("*.wav")):
        if wav.name.endswith(".enroll.wav"):
            continue
        enroll, regs = wav.with_suffix(".enroll.wav"), wav.with_suffix(".regions.json")
        if not (enroll.is_file() and regs.is_file()):
            raise FileNotFoundError(f"{wav.name} needs {enroll.name} and {regs.name}")
        labels = {"target": TARGET, "other": OTHER, "overlap": UNCERTAIN}
        regions = [LabelledRegion(r["start"], r["end"], labels[r["label"]], None, None,
                                  OVERLAP_REASON if r["label"] == "overlap" else "annotated")
                   for r in json.loads(regs.read_text("utf-8"))]
        items.append({"name": wav.stem, "mix": _load(wav), "enroll": _load(enroll), "regions": regions,
                      "mix_path": wav, "enroll_path": enroll})
    return items


def _write_listening(out_dir: Path, data, outputs, kind: str) -> list[dict]:
    result = []
    for d, meta, mix, refs in data:
        have = [n for n, o in outputs.items() if meta["id"] in o]
        labels = blind_labels(have, meta["id"])
        folder = out_dir / "listen" / meta["id"]
        folder.mkdir(parents=True, exist_ok=True)
        write_wav(str(folder / "mixture.wav"), mix, SAMPLE_RATE)
        for letter, n in labels.items():
            write_wav(str(folder / f"{letter}.wav"), outputs[n][meta["id"]], SAMPLE_RATE)
        result.append({"clip": f"{meta['id']} (target {meta['target']}, {meta['n_overlap']}-person overlap, "
                               f"target {meta['target_rel_db']:+.0f} dB, noise "
                               f"{'none' if meta['snr_db'] is None else str(int(meta['snr_db'])) + ' dB SNR'})",
                       "mix": f"listen/{meta['id']}/mixture.wav",
                       "items": [{"label": k, "file": f"listen/{meta['id']}/{k}.wav"} for k in sorted(labels)],
                       "key": labels})
    return result


def _write_real(out_dir: Path, real, real_out) -> list[dict]:
    result = []
    for item in real:
        outs = {"gated_baseline": GatedBaseline().extract(item["mix"], item["regions"]),
                **real_out.get(item["name"], {})}
        labels = blind_labels(list(outs), "real:" + item["name"])
        folder = out_dir / "listen_real" / item["name"]
        folder.mkdir(parents=True, exist_ok=True)
        write_wav(str(folder / "mixture.wav"), item["mix"], SAMPLE_RATE)
        write_wav(str(folder / "enroll.wav"), item["enroll"], SAMPLE_RATE)
        for letter, n in labels.items():
            write_wav(str(folder / f"{letter}.wav"), outs[n], SAMPLE_RATE)
        result.append({"clip": item["name"], "mix": f"listen_real/{item['name']}/mixture.wav",
                       "enroll": f"listen_real/{item['name']}/enroll.wav",
                       "items": [{"label": k, "file": f"listen_real/{item['name']}/{k}.wav"} for k in sorted(labels)],
                       "key": labels})
    return result


def _decision_md(report: dict) -> str:
    d, b = report["decision"], report["basis"]
    lines = ["# Overlap extraction decision", "", f"**{d['text']}**", "",
             f"Status: `{d['status']}`. Data: {b.get('data', '?')} ({b.get('language')}); device: {b.get('device')}.",
             "", "## Evidence (pooled over overlap regions)", "",
             "| Candidate | SI-SDRi dB | Wrong person | Target retention | Verdict |", "|---|---|---|---|---|"]
    base = d.get("baseline_overlap") or {}
    lines.append(f"| gated baseline | {base.get('si_sdri_db_mean')} | — | {base.get('retention_mean')} | reference |")
    for n, c in report["candidates"].items():
        o = c.get("overlap") or {}
        verdict = (f"blocked ({c['blocked']['kind']})" if c["blocked"] else
                   "eligible" if n in d["eligible"] else d["rejected"].get(n, ""))
        lines.append(f"| {n} | {o.get('si_sdri_db_mean')} | {o.get('wrong_person_rate')} | "
                     f"{o.get('retention_mean')} | {verdict} |")
    if d.get("fine_tuning_plan"):
        lines += ["", "## Fine-tuning plan", "", d["fine_tuning_plan"]]
    return "\n".join(lines) + "\n"
