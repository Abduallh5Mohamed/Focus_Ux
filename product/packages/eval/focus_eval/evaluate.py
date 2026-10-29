"""Score one run (isolated audio + hypothesis transcripts) against a dataset.

Run layout::

    <run>/<clip_id>/<target_speaker>.wav   isolated audio for that target
    <run>/<clip_id>/<target_speaker>.txt   hypothesis transcript (optional)
    <run>/run.json                         optional {"label": "..."}
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median

from . import SCHEMA_VERSION
from .audio import AudioError, aligned_si_sdr, load_audio
from .dataset import PROVISIONAL, STATUS_READY, VERIFIED, Clip, Dataset
from .textnorm import error_counts

DEFAULT_AMBIGUOUS_MARGIN_DB = 3.0
LENGTH_TOLERANCE_S = 0.1   # output length must match the mixture within this
FRAME_S = 0.1              # continuity check frame size
DROPOUT_MAX_FRACTION = 0.1  # max share of reference-active frames the output may leave silent


def _dropout_fraction(est, ref) -> float:
    """Share of frames where the reference speaks but the output is (near) silent."""
    n = int(FRAME_S * 16000)
    frames = min(len(est), len(ref)) // n
    if frames == 0:
        return 0.0
    e = est[: frames * n].reshape(frames, n)
    r = ref[: frames * n].reshape(frames, n)
    e_rms = (e ** 2).mean(axis=1) ** 0.5
    r_rms = (r ** 2).mean(axis=1) ** 0.5
    active = r_rms > 0.25 * r_rms.mean()
    if not active.any():
        return 0.0
    silent = e_rms < 1e-3 * max(r_rms.mean(), 1e-12)
    return float((active & silent).sum() / active.sum())


def _score_row(ds: Dataset, clip: Clip, target: str, run: Path, mix, refs, margin_db: float) -> dict:
    speaker = clip.speaker(target)
    row: dict = {
        "clip_id": clip.id,
        "speaker_id": target,
        "tags": clip.tags,
        "audio_status": "ok",
        "reference_status": speaker.transcript_status,
        "text_status": "ok",
    }
    est_path = run / clip.id / f"{target}.wav"
    if not est_path.is_file():
        row["audio_status"] = "missing_audio"
        row["text_status"] = "not_scored"
        return row
    try:
        est = load_audio(est_path)
        diff_s = (len(est) - len(mix)) / 16000.0
        row["length_diff_s"] = round(diff_s, 3)
        problem = None
        if abs(diff_s) > LENGTH_TOLERANCE_S:
            problem = (f"output is {abs(diff_s):.2f}s {'shorter' if diff_s < 0 else 'longer'} "
                       f"than the mixture (tolerance {LENGTH_TOLERANCE_S}s)")
        else:
            drop = _dropout_fraction(est, refs[target])
            row["dropout_fraction"] = round(drop, 4)
            if drop > DROPOUT_MAX_FRACTION:
                problem = f"output is silent in {drop:.0%} of the frames where the target speaks"
        if problem:
            row["audio_status"] = "truncated"
            row["error"] = problem
            row["text_status"] = "not_scored"
            return row
        s_est, lag, edge = aligned_si_sdr(est.copy(), refs[target].copy())
        s_mix, _, _ = aligned_si_sdr(mix.copy(), refs[target].copy())
        row.update(
            si_sdr_est=round(s_est, 3),
            si_sdr_mix=round(s_mix, 3),
            si_sdri=round(s_est - s_mix, 3),
            lag_ms=round(lag / 16.0, 2),
            lag_edge=bool(edge),
        )
        scores = {sid: aligned_si_sdr(est.copy(), r.copy())[0] for sid, r in refs.items()}
        if len(scores) >= 2:
            best = max(scores, key=scores.get)
            others = max(v for k, v in scores.items() if k != target)
            row.update(
                wrong_person=best != target,
                margin_db=round(scores[target] - others, 3),
                ambiguous=abs(scores[target] - others) < margin_db,
                scores_db={k: round(v, 3) for k, v in scores.items()},
            )
        else:
            row["wrong_person"] = None
    except AudioError as exc:
        row["audio_status"] = "error"
        row["error"] = str(exc)
        row["text_status"] = "not_scored"
        return row

    hyp_path = run / clip.id / f"{target}.txt"
    ref_path = ds.path(speaker.transcript) if speaker.transcript else None
    if ref_path is None or not ref_path.is_file():
        row["text_status"] = "no_reference"
    elif not hyp_path.is_file():
        row["text_status"] = "missing_hypothesis"
    else:
        ref_text = ref_path.read_text(encoding="utf-8")
        hyp_text = hyp_path.read_text(encoding="utf-8")
        try:
            ce, cn = error_counts(ref_text, hyp_text, "char")
            we, wn = error_counts(ref_text, hyp_text, "word")
        except ValueError as exc:
            row["text_status"] = "invalid_reference"
            row["error"] = str(exc)
        else:
            row.update(
                char_errors=ce, char_total=cn, cer=round(ce / cn, 4),
                word_errors=we, word_total=wn, wer=round(we / wn, 4),
            )
    return row


def _text_summary(rows: list[dict]) -> dict:
    scored = [r for r in rows if "cer" in r]
    out = {"n_scored": len(scored)}
    if scored:
        ce, cn = sum(r["char_errors"] for r in scored), sum(r["char_total"] for r in scored)
        we, wn = sum(r["word_errors"] for r in scored), sum(r["word_total"] for r in scored)
        out.update(cer=round(ce / cn, 4), wer=round(we / wn, 4))
    return out


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["audio_status"] == "ok"]
    person = [r for r in ok if r.get("wrong_person") is not None]
    wrong = [r for r in person if r["wrong_person"]]
    sdri = [r["si_sdri"] for r in ok]
    return {
        "n_targets": len(rows),
        "n_audio_ok": len(ok),
        "n_missing_audio": sum(r["audio_status"] == "missing_audio" for r in rows),
        "n_audio_error": sum(r["audio_status"] == "error" for r in rows),
        "n_truncated": sum(r["audio_status"] == "truncated" for r in rows),
        "wrong_person": {
            "evaluable": len(person),
            "wrong": len(wrong),
            "rate": round(len(wrong) / len(person), 4) if person else None,
            "ambiguous": sum(bool(r.get("ambiguous")) for r in person),
        },
        "si_sdri_db": {
            "mean": round(mean(sdri), 3) if sdri else None,
            "median": round(median(sdri), 3) if sdri else None,
        },
        # Corpus-level rates (total errors / total reference length). Provisional
        # references are reported separately and never mixed into verified numbers.
        "text_verified": _text_summary([r for r in rows if r["reference_status"] == VERIFIED]),
        "text_provisional": _text_summary([r for r in rows if r["reference_status"] == PROVISIONAL]),
        "n_text_missing_hypothesis": sum(r["text_status"] == "missing_hypothesis" for r in rows),
    }


def evaluate(ds: Dataset, run_dir: str | Path, ambiguous_margin_db: float = DEFAULT_AMBIGUOUS_MARGIN_DB) -> dict:
    run = Path(run_dir)
    if not run.is_dir():
        raise FileNotFoundError(f"run directory not found: {run}")
    label = run.name
    meta = run / "run.json"
    if meta.is_file():
        label = str(json.loads(meta.read_text(encoding="utf-8")).get("label", label))

    rows: list[dict] = []
    not_ready = [c.id for c in ds.clips if c.status != STATUS_READY]
    for clip in ds.clips:
        if clip.status != STATUS_READY:
            continue
        mix = load_audio(ds.path(clip.mix_audio))
        refs = {s.id: load_audio(ds.path(s.ref_audio)) for s in clip.speakers}
        for target in clip.targets:
            rows.append(_score_row(ds, clip, target, run, mix, refs, ambiguous_margin_db))

    fingerprint = ds.fingerprint()
    tags = sorted({t for r in rows for t in r["tags"]})
    bench = None
    if meta.is_file():
        bench = json.loads(meta.read_text(encoding="utf-8")).get("bench_by_clip")
    return {
        "schema_version": SCHEMA_VERSION,
        "bench_by_clip": bench,
        "dataset_id": ds.dataset_id,
        "dataset_fingerprint": fingerprint,
        "run_label": label,
        "not_ready_clips": not_ready,
        "thresholds": {"ambiguous_margin_db": ambiguous_margin_db},
        "summary": summarize(rows),
        "by_tag": {t: summarize([r for r in rows if t in r["tags"]]) for t in tags},
        "rows": rows,
    }
