"""Final evaluation report assembled from the files one run wrote.

Pure numpy: it reads a run directory (see ``product/tools/eval_runner.py``) and
the dataset manifest, and computes every number from them. The report is
reproducible from the manifest and the recorded settings: the metrics block
does not depend on wall-clock time, and timing lives in its own block.

Run directory additions beyond the ``evaluate`` layout::

    <run>/run.json                         label, settings, environment, bench_by_clip, profile_by_clip
    <run>/<clip>/<target>.timeline.json    target/uncertain regions the pipeline kept
    <run>/verification.json                pooled same/different-speaker scores
    <run>/visibility.json                  per clip: outputs for video / blacked-out video / audio only
    <run>/stress/<condition>/<clip>/       mix.wav (degraded) and <target>.wav
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from statistics import mean

import numpy as np

from . import EVALUATION_POLICY, SCHEMA_VERSION
from .audio import load_audio
from .dataset import STATUS_READY, Dataset
from .evaluate import DEFAULT_AMBIGUOUS_MARGIN_DB, _score_row, evaluate, summarize
from .voice_metrics import eer, far_frr, gate_metrics, to_frames
from .voice_mix import activity_segments

REPORT_FORMAT = "focus-final-report/1"
TARGET_DEVICE_MARKER = "3050"            # the demo laptop's GPU
LEAVES_FRAME_TAG = "face_disappears"
LIMITATION_TAGS = ("similar_voices", "whisper", "shout", "noise", "reverb", "no_solo_enrollment")


def overlap_type(refs: dict) -> str:
    """none / two_speakers / three_plus, by the most references active at once."""
    n = min(len(r) for r in refs.values())
    frames = np.stack([to_frames(activity_segments(r[:n]), n / 16000) for r in refs.values()])
    peak = int(frames[:, :].sum(axis=0).max()) if frames.size else 0
    return "three_plus" if peak >= 3 else "two_speakers" if peak == 2 else "none"


def _mean(values):
    values = [v for v in values if v is not None]
    return round(mean(values), 4) if values else None


def _retention_rows(ds: Dataset, run: Path, rows: list[dict]) -> dict:
    """Per (clip, target): gate metrics from the saved timeline and reference activity."""
    out = {}
    for clip in ds.clips:
        if clip.status != STATUS_READY:
            continue
        refs = {s.id: load_audio(ds.path(s.ref_audio)) for s in clip.speakers}
        n = len(load_audio(ds.path(clip.mix_audio)))
        truth = {sid: activity_segments(r) for sid, r in refs.items()}
        for target in clip.targets:
            path = run / clip.id / f"{target}.timeline.json"
            if not path.is_file():
                continue
            kept = [(r["start"], r["end"]) for r in json.loads(path.read_text("utf-8")) if r["label"] == "target"]
            others = [seg for sid, v in truth.items() if sid != target for seg in v]
            out[(clip.id, target)] = gate_metrics(kept, truth[target], others, n / 16000)
    return out


def _group(rows: list[dict], gates: dict, key) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    result = {}
    for name, rs in sorted(groups.items()):
        g = [gates[(r["clip_id"], r["speaker_id"])] for r in rs if (r["clip_id"], r["speaker_id"]) in gates]
        s = summarize(rs)
        result[name] = {
            "n_targets": s["n_targets"], "n_audio_ok": s["n_audio_ok"],
            "si_sdri_db_mean": s["si_sdri_db"]["mean"], "si_sdri_db_median": s["si_sdri_db"]["median"],
            "wrong_person": s["wrong_person"],
            "target_retention": _mean([x["target_retention"] for x in g]),
            "wrong_share_of_output": _mean([x["wrong_share_of_output"] for x in g]),
            "dropout_fraction_mean": _mean([r.get("dropout_fraction") for r in rs if r["audio_status"] == "ok"]),
        }
    return result


def _verification(run: Path) -> dict:
    path = run / "verification.json"
    if not path.is_file():
        return {"status": "not_run", "reason": "verification.json missing"}
    v = json.loads(path.read_text("utf-8"))
    t, o = v["scores"]["target"], v["scores"]["other"]
    if not t or not o:
        return {"status": "not_measurable", "reason": "need same-speaker and different-speaker trials",
                "n_target_trials": len(t), "n_other_trials": len(o), "parameters": v.get("parameters")}
    e = eer(t, o)
    deployed = {k: far_frr(t, o, th) for k, th in (v.get("thresholds") or {}).items()}
    return {"status": "measured", "eer": e, "at_deployed_thresholds": deployed,
            "false_accept_rate_at_target_threshold": (deployed.get("target_threshold") or {}).get("far"),
            "false_reject_rate_at_target_threshold": (deployed.get("target_threshold") or {}).get("frr"),
            "parameters": v.get("parameters")}


def _visibility(run: Path) -> dict:
    path = run / "visibility.json"
    if not path.is_file():
        return {"status": "not_run"}
    clips = json.loads(path.read_text("utf-8"))["clips"]
    checked = {k: v for k, v in clips.items() if v.get("status") == "checked"}
    failed = [k for k, v in checked.items() if not v["identical"]]
    return {"status": "not_run" if not checked else ("pass" if not failed else "FAIL"),
            "n_checked": len(checked), "n_skipped": len(clips) - len(checked),
            "failed_clips": failed, "clips": clips,
            "claim": "output audio is byte-identical with the video, a blacked-out video and audio only"}


def _stress(ds: Dataset, run: Path, margin: float) -> dict:
    root = run / "stress"
    if not root.is_dir():
        return {"status": "not_run"}
    out = {}
    for cond_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        rows = []
        for clip in ds.clips:
            mix_path = cond_dir / clip.id / "mix.wav"
            if clip.status != STATUS_READY or not mix_path.is_file():
                continue
            mix = load_audio(mix_path)
            refs = {s.id: load_audio(ds.path(s.ref_audio)) for s in clip.speakers}
            for target in clip.targets:
                rows.append(_score_row(ds, clip, target, cond_dir, mix, refs, margin, dropout_blocks=False))
        s = summarize(rows)
        out[cond_dir.name] = {"n_targets": s["n_targets"], "n_audio_ok": s["n_audio_ok"],
                              "wrong_person": s["wrong_person"], "si_sdri_db": s["si_sdri_db"],
                              "synthetic": True}
    return {"status": "measured", "conditions": out,
            "note": "synthetic degradations (focus_eval.stress); not a substitute for real recordings"}


def _limitations(rows, gates, base_by_overlap: dict, by_tag: dict, stress: dict, enroll_mode: str) -> dict:
    sections = {"overlap_three_plus": base_by_overlap.get("three_plus") or {"status": "no_clips"}}
    for tag in LIMITATION_TAGS:
        sections[tag] = by_tag.get(tag) or {"status": "no_clips"}
    sections["noise_reverb_synthetic"] = stress
    sections["enrollment_without_clean_solo_span"] = (
        by_tag.get("no_solo_enrollment") or {"status": "no_clips"})
    sections["enrollment_mode_of_this_run"] = enroll_mode
    return sections


def build_report(ds: Dataset, run_dir: str | Path, *, margin_db: float = DEFAULT_AMBIGUOUS_MARGIN_DB,
                 manifest_hint: str | None = None) -> dict:
    run = Path(run_dir)
    meta = json.loads((run / "run.json").read_text("utf-8")) if (run / "run.json").is_file() else {}
    base = evaluate(ds, run, margin_db, dropout_blocks=False)
    rows = base["rows"]
    gates = _retention_rows(ds, run, rows)
    types = {}
    for clip in ds.clips:
        if clip.status == STATUS_READY:
            types[clip.id] = overlap_type({s.id: load_audio(ds.path(s.ref_audio)) for s in clip.speakers})
    by_overlap = _group(rows, gates, lambda r: types.get(r["clip_id"], "unknown"))
    by_tag = {}
    for tag in sorted({t for r in rows for t in r["tags"]}):
        by_tag.update(_group([r for r in rows if tag in r["tags"]], gates, lambda r, t=tag: t))
    leaves = [r for r in rows if LEAVES_FRAME_TAG in r["tags"]]
    stress = _stress(ds, run, margin_db)
    env = meta.get("environment") or {}
    device_name = (env.get("gpu_name") or "")
    profile = meta.get("profile_by_clip") or {}
    settings = meta.get("settings")
    on_target = TARGET_DEVICE_MARKER in device_name
    manifest_sha = hashlib.sha256((ds.root / "manifest.json").read_bytes()).hexdigest()
    return {
        "format": REPORT_FORMAT, "schema_version": SCHEMA_VERSION, "evaluation_policy": EVALUATION_POLICY,
        "measured_on_target_laptop": on_target,
        "headline_warning": None if on_target else (
            "NOT measured on the RTX 3050 laptop (device: %s). Speed and VRAM figures do not count as "
            "met targets." % (device_name or "no GPU / unknown")),
        "reproducibility": {
            "dataset_id": ds.dataset_id, "dataset_fingerprint": ds.fingerprint(), "manifest_sha256": manifest_sha,
            "settings": settings, "environment": env, "run_label": base["run_label"],
            "reproduce": meta.get("command"),
        },
        "metrics": {
            "targets_scored": base["summary"]["n_audio_ok"], "targets_expected": base["summary"]["n_targets"],
            "not_ready_clips": base["not_ready_clips"],
            "verification": _verification(run),
            "overall": _group(rows, gates, lambda r: "all"),
            "wrong_person": base["summary"]["wrong_person"],
            "by_overlap_type": by_overlap,
            "by_tag": by_tag,
            "target_leaves_the_frame": {
                "tag": LEAVES_FRAME_TAG,
                "status": "measured" if leaves else "no_clips",
                "targets": [{"clip_id": r["clip_id"], "speaker_id": r["speaker_id"],
                             "audio_status": r["audio_status"], "si_sdri_db": r.get("si_sdri"),
                             "wrong_person": r.get("wrong_person"),
                             **{k: v for k, v in (gates.get((r["clip_id"], r["speaker_id"])) or {}).items()
                                if k in ("target_retention", "wrong_share_of_output")}} for r in leaves],
            },
            "visibility_independence": _visibility(run),
            "limitations": _limitations(rows, gates, by_overlap, by_tag, stress,
                                        (settings or {}).get("enroll", "unknown")),
        },
        "timing": {
            "rtf_by_clip": {c: (meta.get("bench_by_clip") or {}).get(c) for c in sorted(profile or meta.get("bench_by_clip") or {})},
            "rtf_worst": max((v["rtf"] for v in (meta.get("bench_by_clip") or {}).values() if v.get("rtf") is not None), default=None),
            "peak_vram_mib": max((p["peak_vram_mib"] for p in profile.values() if p.get("peak_vram_mib") is not None), default=None),
            "peak_ram_mib": max((p["peak_ram_mib"] for p in profile.values() if p.get("peak_ram_mib") is not None), default=None),
            "profile_by_clip": profile,
        },
        "rows": rows,
    }


def stable_metrics(report: dict) -> str:
    """Canonical JSON of everything that must reproduce exactly (no timing)."""
    return json.dumps({"reproducibility": {k: v for k, v in report["reproducibility"].items()
                                           if k not in ("environment", "reproduce", "run_label")},
                       "metrics": report["metrics"]}, sort_keys=True, ensure_ascii=False)


def _f(v, nd=3):
    return "n/a" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def render_markdown(rep: dict) -> str:
    m, t = rep["metrics"], rep["timing"]
    L = ["# FOCUS final evaluation", ""]
    if rep["headline_warning"]:
        L += [f"> **{rep['headline_warning']}**", ""]
    r = rep["reproducibility"]
    L += [f"Dataset `{r['dataset_id']}` fingerprint `{r['dataset_fingerprint'][:16]}`, run `{r['run_label']}`.",
          f"Targets scored {m['targets_scored']}/{m['targets_expected']}; "
          f"template clips skipped: {len(m['not_ready_clips'])}.", ""]
    v = m["verification"]
    L += ["## Speaker verification (embedding)"]
    if v["status"] == "measured":
        L += [f"EER {_f(v['eer']['eer'])} ({v['eer']['n_target_trials']} same / {v['eer']['n_other_trials']} different trials). "
              f"False accept at the deployed target threshold {_f(v['false_accept_rate_at_target_threshold'])}, "
              f"false reject {_f(v['false_reject_rate_at_target_threshold'])}."]
    else:
        L += [f"{v['status']}: {v.get('reason', '')}"]
    o = m["overall"].get("all", {})
    L += ["", "## Full pipeline", f"Wrong person {m['wrong_person']['wrong']}/{m['wrong_person']['evaluable']}, "
          f"target retention {_f(o.get('target_retention'))}, SI-SDRi mean {_f(o.get('si_sdri_db_mean'), 2)} dB.", "",
          "### By overlap type", "| type | targets | SI-SDRi dB | retention | wrong person |", "|---|---|---|---|---|"]
    for k, g in m["by_overlap_type"].items():
        L.append(f"| {k} | {g['n_targets']} | {_f(g['si_sdri_db_mean'], 2)} | {_f(g['target_retention'])} | "
                 f"{g['wrong_person']['wrong']}/{g['wrong_person']['evaluable']} |")
    lf = m["target_leaves_the_frame"]
    L += ["", f"### Target leaves the frame (`{lf['tag']}`): {lf['status']}"]
    for x in lf["targets"]:
        L.append(f"- {x['clip_id']}/{x['speaker_id']}: {x['audio_status']}, SI-SDRi {_f(x['si_sdri_db'], 2)}, "
                 f"retention {_f(x.get('target_retention'))}, wrong person {x['wrong_person']}")
    vi = m["visibility_independence"]
    L += ["", f"### Visibility independence: **{vi['status']}** "
          f"({vi.get('n_checked', 0)} checked, {vi.get('n_skipped', 0)} skipped)"]
    L += ["", "## Speed and memory",
          f"Worst real-time factor {_f(t['rtf_worst'])}, peak VRAM {_f(t['peak_vram_mib'], 1)} MiB, "
          f"peak RAM {_f(t['peak_ram_mib'], 1)} MiB."]
    L += ["", "## Limitations (measured subsets)"]
    for name, sec in m["limitations"].items():
        if isinstance(sec, dict) and "wrong_person" in sec:
            L.append(f"- {name}: n={sec['n_targets']}, SI-SDRi {_f(sec['si_sdri_db_mean'], 2)} dB, "
                     f"retention {_f(sec['target_retention'])}, wrong person "
                     f"{sec['wrong_person']['wrong']}/{sec['wrong_person']['evaluable']}")
        elif isinstance(sec, dict) and sec.get("status") == "measured" and "conditions" in sec:
            for c, s in sec["conditions"].items():
                L.append(f"- {name} / {c}: SI-SDRi {_f(s['si_sdri_db']['mean'], 2)} dB, wrong person "
                         f"{s['wrong_person']['wrong']}/{s['wrong_person']['evaluable']} (synthetic)")
        else:
            L.append(f"- {name}: {sec.get('status', sec) if isinstance(sec, dict) else sec}")
    return "\n".join(L) + "\n"
