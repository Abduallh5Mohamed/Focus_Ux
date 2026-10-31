"""Real-weights experiment: every candidate on the same mixes, against the gated baseline.

Per mix and candidate two outputs are made and scored against the clean references:
  raw     the extractor run on the WHOLE mixture (one window, no region knowledge)
  hybrid  the production-shaped path: target solo turns pass through, extraction only in
          the overlap regions (oracle region labels), voiceprint check on every piece
plus the gated baseline (mute everything but the target's solo turns) and, per candidate,
the residual (mixture minus the raw extraction). Everything is saved as playable files.

One failing candidate never stops the others; the exact error text is kept per candidate
and per mix. No stub or oracle extractor is ever created here.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import numpy as np

from ..isolation_engines import read_wav
from ..voice.extractor import GatedBaseline
from ..voice.types import SAMPLE_RATE
from . import experiment_metrics as X
from .base import BlockedError, vram_peak_mib, vram_reset
from .bakeoff import labelled_regions, make_voiceprint
from .hybrid import HybridConfig, HybridExtractor

GROUPS = {2: "2-speaker mixes (overlap = target + 1)",
          3: "3-speaker mixes (overlap = target + 1 or 2 others; only the full-overlap mixes are pure target + 2)"}
VRAM_NOTE = "not measured (CPU)"


def _load(path) -> np.ndarray:
    x, sr = read_wav(str(path))
    if sr != SAMPLE_RATE:
        raise ValueError(f"{path} is {sr} Hz; 16 kHz mono is required")
    return x.astype(np.float32)


def write_audio(path: Path, samples, fmt: str = "flac") -> None:
    """Playable file. Samples above full scale are peak-scaled for playback only (scores use the raw signal)."""
    import soundfile as sf
    x = np.asarray(samples, dtype=np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.99:
        x = x * (0.99 / peak)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), x, SAMPLE_RATE, format=fmt.upper(), subtype="PCM_16")


def error_record(exc: BaseException) -> dict:
    """The exact error: class, full message, and the last frames of the traceback."""
    rec = {"type": type(exc).__name__, "message": str(getattr(exc, "evidence", "") or exc)}
    if isinstance(exc, BlockedError):
        rec.update(kind=exc.kind, blocked_message=exc.message, evidence=exc.evidence)
    rec["traceback_tail"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-6:])[-3000:]
    return rec


def _timed(fn):
    w0, c0 = time.perf_counter(), time.process_time()
    out = fn()
    return out, round(time.perf_counter() - w0, 4), round(time.process_time() - c0, 4)


def pool_report(mix_metas: list[dict], outputs: dict[str, dict[str, dict]]) -> dict:
    """outputs: output_key -> mix id -> {"overlap": scores, "clip": scores}. Pooled per group
    (never across groups), and per group x target level and x scenario."""
    pooled = {}
    for n in sorted({m["n_overlap"] for m in mix_metas}):
        ids = [m["id"] for m in mix_metas if m["n_overlap"] == n]
        grp = {}
        for key, per_mix in outputs.items():
            entry = {}
            for scope in ("overlap", "clip"):
                entry[scope] = X.pool([per_mix[i][scope] for i in ids if i in per_mix])
            entry["by_level"] = {f"{lv:+.0f} dB": X.pool([per_mix[m["id"]]["overlap"] for m in mix_metas
                                                         if m["n_overlap"] == n and m["target_rel_db"] == lv
                                                         and m["id"] in per_mix])
                                 for lv in sorted({m["target_rel_db"] for m in mix_metas if m["n_overlap"] == n})}
            entry["by_scenario"] = {sc: X.pool([per_mix[m["id"]]["overlap"] for m in mix_metas
                                               if m["n_overlap"] == n and m.get("scenario") == sc
                                               and m["id"] in per_mix])
                                    for sc in sorted({m.get("scenario", "?") for m in mix_metas if m["n_overlap"] == n})}
            grp[key] = entry
        pooled[str(n)] = grp
    return pooled


def timing_summary(records: list[dict], overlap_s: list[float]) -> dict:
    ok = [r for r in records if r and "wall_s" in r]
    if not ok:
        return {}
    audio = sum(r["audio_s"] for r in ok)
    wall = sum(r["wall_s"] for r in ok)
    return {"mixes": len(ok), "audio_seconds": round(audio, 2), "wall_seconds": round(wall, 3),
            "cpu_seconds": round(sum(r["cpu_s"] for r in ok), 3), "rtf": round(wall / audio, 4),
            "seconds_per_mix": round(wall / len(ok), 3),
            "peak_vram": (f"{max(v):.0f} MiB" if (v := [r["peak_vram_mib"] for r in ok
                                                      if r.get("peak_vram_mib") is not None]) else VRAM_NOTE)}


def run_experiment(set_dir, out_dir, names, build, embedder, basis: dict, info: dict,
                   hybrid_config: HybridConfig | None = None, max_mixes: int | None = None,
                   audio_format: str = "flac") -> dict:
    set_dir, out_dir = Path(set_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mixes = sorted(p for p in set_dir.iterdir() if (p / "meta.json").is_file())[:max_mixes]
    if not mixes:
        raise FileNotFoundError(f"no mixes (meta.json) found in {set_dir}")
    set_info = json.loads((set_dir / "set.json").read_text("utf-8"))
    data = []
    for d in mixes:
        meta = json.loads((d / "meta.json").read_text("utf-8"))
        refs = {s: _load(d / f"ref_{s}.wav") for s in {meta["target"], *meta["others"]}}
        data.append((d, meta, _load(d / "mix.wav"), refs))
    metas = [m for _, m, _, _ in data]
    prints, enrolls = {}, {}

    def enroll_of(spk):
        if spk not in prints:
            enrolls[spk] = _load(set_dir / "enroll" / f"{spk}.wav")
            prints[spk] = make_voiceprint(embedder, enrolls[spk])
        return enrolls[spk], prints[spk]

    scores: dict[str, dict[str, dict]] = {"gated_baseline": {}}
    listening = {m["id"]: {"files": []} for m in metas}

    def save(meta, name, label, x):
        rel = f"listen/{meta['id']}/{name}.{audio_format}"
        write_audio(out_dir / rel, x, audio_format)
        listening[meta["id"]]["files"].append({"label": label, "file": rel, "key": name})

    gate = GatedBaseline()
    for d, meta, mix, refs in data:
        enroll, _ = enroll_of(meta["target"])
        regions = labelled_regions(meta["regions"], meta["target"])
        est = gate.extract(mix, regions)
        scores["gated_baseline"][meta["id"]] = X.score_output(est, mix, refs, meta["target"], meta["regions"])
        save(meta, "00_mixture", "Original mixture", mix)
        save(meta, "01_target_reference", "Clean target reference", refs[meta["target"]])
        save(meta, "02_enrollment", "Enrollment clip (separate recording)", enroll)
        save(meta, "gated_baseline", "Gated baseline (target solo turns only)", est)

    cands = {}
    for name in names:
        rec = {"info": info[name].as_dict(), "blocked": None, "load_seconds": None, "errors": [],
               "mixes": {}, "timing": {}}
        cands[name] = rec
        ex = build(name)
        try:
            ex.check_ready()
            _, load_s, _ = _timed(ex.load)
            rec["load_seconds"] = load_s
        except Exception as exc:           # noqa: BLE001 - reported with the exact text
            rec["blocked"] = error_record(exc)
            print(f"{name}: FAILED to load: {rec['blocked']['type']}: {rec['blocked']['message'][:200]}", flush=True)
            continue
        raw_t, hyb_t, ov_s = [], [], []
        for d, meta, mix, refs in data:
            enroll, vp = enroll_of(meta["target"])
            t = meta["target"]
            m_rec = {}
            rec["mixes"][meta["id"]] = m_rec
            try:                                     # raw: the model on the whole mixture
                vram_reset()
                raw, wall, cpu = _timed(lambda: ex.extract_batch([mix], vp, enroll)[0])
                raw_vram = vram_peak_mib()
                m_rec["raw"] = {"scores": X.score_output(raw, mix, refs, t, meta["regions"]), "wall_s": wall,
                                "cpu_s": cpu, "audio_s": round(len(mix) / SAMPLE_RATE, 3), "peak_vram_mib": raw_vram,
                                "rtf": round(wall / (len(mix) / SAMPLE_RATE), 4)}
                raw_t.append(m_rec["raw"])
                scores.setdefault(f"{name}:raw", {})[meta["id"]] = m_rec["raw"]["scores"]
                save(meta, f"{name}_raw", f"{name}: raw extraction (model on the whole mixture)", raw)
                save(meta, f"{name}_residual", f"{name}: residual (mixture minus raw extraction)", mix - raw)
            except Exception as exc:         # noqa: BLE001
                rec["errors"].append({"mix": meta["id"], "stage": "raw", **error_record(exc)})
            try:                                     # hybrid: pass-through + extraction in overlap only
                hy = HybridExtractor(ex, vp, enroll, embedder, hybrid_config)
                est, wall, cpu = _timed(lambda: hy.extract(mix, labelled_regions(meta["regions"], t)))
                r = hy.last_report
                m_rec["hybrid"] = {"scores": X.score_output(est, mix, refs, t, meta["regions"]), "wall_s": wall,
                                   "cpu_s": cpu, "audio_s": round(len(mix) / SAMPLE_RATE, 3),
                                   "overlap_s": r["overlap_seconds"], "extract_s": r["extract_seconds"],
                                   "rtf_overlap": r["rtf_overlap"], "windows": r["windows"], "peak_vram_mib": r["peak_vram_mib"],
                                   "uncertain_muted_s": r["uncertain_muted_seconds"],
                                   "pieces": r["pieces"]}
                hyb_t.append(m_rec["hybrid"])
                ov_s.append(r["overlap_seconds"])
                scores.setdefault(f"{name}:hybrid", {})[meta["id"]] = m_rec["hybrid"]["scores"]
                save(meta, f"{name}_hybrid", f"{name}: hybrid output (extraction only in overlap)", est)
            except Exception as exc:         # noqa: BLE001
                rec["errors"].append({"mix": meta["id"], "stage": "hybrid", **error_record(exc)})
        rec["timing"] = {"raw_whole_mixture": timing_summary(raw_t, []),
                         "hybrid": {**timing_summary(hyb_t, ov_s),
                                    "extract_seconds": round(sum(r["extract_s"] for r in hyb_t), 3),
                                    "overlap_seconds": round(sum(ov_s), 2),
                                    "rtf_overlap": round(sum(r["extract_s"] for r in hyb_t) / sum(ov_s), 4)
                                    if sum(ov_s) else None} if hyb_t else {}}
        rec["inference_completed"] = bool(raw_t or hyb_t)
        try:
            ex.unload()
        except Exception:                    # noqa: BLE001
            pass
        print(f"{name}: raw {len(raw_t)}/{len(data)} hybrid {len(hyb_t)}/{len(data)} errors {len(rec['errors'])}",
              flush=True)

    pooled = pool_report(metas, scores)
    gated = {g: {"overlap": pooled[g]["gated_baseline"]["overlap"]} for g in pooled}
    verdicts = {g: {n: X.improves(pooled[g].get(f"{n}:hybrid", {}).get("overlap")) for n in names
                    if f"{n}:hybrid" in pooled[g]} for g in pooled}
    report = {"basis": {**basis, "language": set_info.get("language", "unknown")}, "set": set_info,
              "mixes": [{k: m[k] for k in ("id", "target", "others", "n_overlap", "scenario", "target_rel_db",
                                           "seconds", "regions", "plan")} for m in metas],
              "candidates": cands, "pooled": pooled, "gated_baseline_pooled": gated, "verdicts": verdicts,
              "listening": listening, "groups": GROUPS, "peak_vram": VRAM_NOTE if str(basis.get("device")) == "cpu"
              else "see per-candidate timing"}
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    return report
