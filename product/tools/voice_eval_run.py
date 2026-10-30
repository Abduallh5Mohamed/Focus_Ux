"""Real-model measurement runs for the voice pipeline (audio only).

  verify : speaker-verification scores (EER, thresholds) for one embedder on a folder of
           solo recordings <speaker>*.wav. Needs only the embedder weights.
  run    : the full pipeline on ground-truth mixes (three_speaker_set.py --solo-dir ...).
           Needs the diarizer weights unless --oracle-diarization (labelled as such).
Score a run with:  python -m focus_eval.cli voice-eval --mixes M --run R
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "ml"), str(ROOT / "product" / "packages" / "eval")]

from focus_eval.voice_metrics import calibrate_thresholds, eer, far_frr, verification_trials  # noqa: E402
from focus_eval.voice_mix import activity_segments  # noqa: E402
from focus_ml.isolation_engines import write_wav  # noqa: E402
from focus_ml.voice.diarizer import CachedDiarizer, PyannoteDiarizer, from_turns  # noqa: E402
from focus_ml.voice.embedder import build_embedder, embed_segments  # noqa: E402
from focus_ml.voice.enroll import enroll_from_file  # noqa: E402
from focus_ml.voice.gpu import StageLog, resolve_device  # noqa: E402
from focus_ml.voice.match import MatchConfig  # noqa: E402
from focus_ml.voice.pipeline import run_pipeline  # noqa: E402
from focus_ml.voice.preprocess import load_canonical  # noqa: E402
from focus_ml.voice.types import SAMPLE_RATE, Segment  # noqa: E402
from focus_ml.voice.weights import cache_dir  # noqa: E402


def utterances(x, utt_s: float):
    """Fixed-length chunks inside speech-active spans (ground-truth helper, not a model)."""
    out = []
    for a, b in activity_segments(x, SAMPLE_RATE, min_gap_s=0.5):
        t = a
        while t + utt_s <= b:
            out.append(Segment(t, t + utt_s))
            t += utt_s
    return out


def cmd_verify(a) -> int:
    emb = build_embedder(a.embedder, resolve_device(a.device))
    vecs = {}
    files = {}
    for f in sorted(Path(a.solo_dir).glob("*.wav")):
        files.setdefault(f.stem.split("__")[0], []).append(f)
    for spk, fs in files.items():
        x = np.concatenate([load_canonical(str(p)) for p in fs])
        vecs[spk] = [embed_segments(emb, x, [u], min_s=0.5)[0] for u in utterances(x, a.utt_s)]
    emb.unload()
    tgt, oth = verification_trials(vecs, enroll_n=a.enroll_n)
    e = eer(tgt, oth)
    cal = calibrate_thresholds(tgt, oth)
    rep = {"embedder": a.embedder, "speakers": len(vecs), "utterance_s": a.utt_s,
           "utterances_per_speaker": {k: len(v) for k, v in vecs.items()},
           "enrollment_utterances": a.enroll_n, "eer": e, "at_eer": far_frr(tgt, oth, e["threshold"]),
           "calibrated": cal, "at_calibrated_target_threshold": far_frr(tgt, oth, cal["target_threshold"]),
           "dataset_note": a.note, "scores": {"target": tgt, "other": oth}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "scores"}, indent=1))
    return 0


def cmd_run(a) -> int:
    device = resolve_device(a.device)
    emb = build_embedder(a.embedder, device)
    mixes = Path(a.mixes)
    inner = None if a.oracle_diarization else PyannoteDiarizer(device)
    diarizer = None if inner is None else CachedDiarizer(inner, cache_dir().parent / "diarization-cache")
    match = MatchConfig.for_embedder(a.embedder)
    if a.target_threshold is not None:
        match.target_threshold = a.target_threshold
    if a.other_threshold is not None:
        match.other_threshold = a.other_threshold
    match.__post_init__()
    for mdir in sorted(p for p in mixes.iterdir() if (p / "truth.json").is_file()):
        truth = json.loads((mdir / "truth.json").read_text("utf-8"))
        x = load_canonical(str(mdir / "mix.wav"))
        for target in sorted(truth["segments"]):
            log = StageLog(device)
            # enrollment from a SEPARATE voice recording of the target (no mixed audio)
            enroll_audio = load_canonical(str(mixes / "enroll" / f"{target}.wav"))
            with log.stage("enroll"):
                e_diar = from_turns([Segment(s, e, target) for s, e in activity_segments(enroll_audio)]) \
                    if a.oracle_diarization else diarizer.diarize(enroll_audio)
                vp = enroll_from_file(enroll_audio, e_diar, emb, name=f"{target}.wav")
            emb.unload()
            if a.oracle_diarization:
                diar = from_turns([Segment(s, e, spk) for spk, v in truth["segments"].items() for s, e in v])
            else:
                with log.stage("diarize"):
                    diar = diarizer.diarize(x)
                diarizer.unload()
            res = run_pipeline(x, vp, diarization=diar, embedder=emb, match=match, log=log)
            out = Path(a.out) / mdir.name / target
            out.mkdir(parents=True, exist_ok=True)
            (out / "diarization.json").write_text(json.dumps(diar.as_dict()))
            (out / "timeline.json").write_text(json.dumps([r.as_dict() for r in res.regions]))
            write_wav(str(out / "gated_baseline.wav"), res.output, SAMPLE_RATE)
            t = log.as_dict()
            t["audio_seconds"] = round(len(x) / SAMPLE_RATE, 3)
            t["real_time_factor"] = round(t["total_seconds"] / t["audio_seconds"], 3)
            (out / "report.json").write_text(json.dumps({
                "embedder": a.embedder, "oracle_diarization": a.oracle_diarization,
                "diarizer": "oracle (ground truth)" if a.oracle_diarization else "pyannote/speaker-diarization-community-1",
                "match": vars(match), "timing": t, "dataset_note": a.note}, indent=1))
            print("done", mdir.name, target)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("verify", "run"):
        p = sub.add_parser(name)
        p.add_argument("--embedder", default="ecapa", choices=("ecapa", "pyannote"))
        p.add_argument("--device", default="auto")
        p.add_argument("--out", required=True)
        p.add_argument("--note", default="", help="what this dataset is (e.g. non-Egyptian LibriSpeech)")
    p = sub.choices["verify"]
    p.add_argument("--solo-dir", required=True)
    p.add_argument("--utt-s", type=float, default=4.0)
    p.add_argument("--enroll-n", type=int, default=3)
    p = sub.choices["run"]
    p.add_argument("--mixes", required=True)
    p.add_argument("--oracle-diarization", action="store_true")
    p.add_argument("--target-threshold", type=float)
    p.add_argument("--other-threshold", type=float)
    a = ap.parse_args(argv)
    return {"verify": cmd_verify, "run": cmd_run}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
