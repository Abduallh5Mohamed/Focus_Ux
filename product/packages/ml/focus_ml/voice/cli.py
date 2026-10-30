"""Command line: run / enroll / readiness. Audio only; works on a WAV or a video's audio.

  python -m focus_ml.voice.cli run clip.mp4 --enroll-speaker SPEAKER_00 --out out/
  python -m focus_ml.voice.cli run clip.wav --voiceprint me.json --out out/
  python -m focus_ml.voice.cli enroll --file my_voice.wav --save me.json
  python -m focus_ml.voice.cli readiness --url https://...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..errors import MlError
from ..isolation_engines import write_wav
from .diarizer import CachedDiarizer, PyannoteDiarizer
from .embedder import EMBEDDERS, build_embedder
from .enroll import (EnrollmentConfig, enroll_from_file, enroll_from_range,
                     enroll_from_speaker)
from .gpu import StageLog, resolve_device
from .match import MatchConfig
from .pipeline import analyze, run_pipeline
from .preprocess import load_canonical
from .types import SAMPLE_RATE, Voiceprint
from .weights import cache_dir, voice_home


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _add_enroll_args(p):
    p.add_argument("--enroll-speaker", help="diarized speaker label from this audio, e.g. SPEAKER_00")
    p.add_argument("--enroll-range", nargs=2, type=float, metavar=("START_S", "END_S"))
    p.add_argument("--enroll-file", help="a separate recording of the person speaking")
    p.add_argument("--voiceprint", help="a saved voiceprint JSON")
    p.add_argument("--min-clean-s", type=float, default=4.0, help="minimum clean enrollment speech")


def make_voiceprint(a, samples, diar, embedder, diarizer) -> Voiceprint:
    cfg = EnrollmentConfig(min_clean_s=a.min_clean_s)
    chosen = [x for x in (a.enroll_speaker, a.enroll_range, a.enroll_file, a.voiceprint) if x]
    if len(chosen) != 1:
        raise MlError("choose exactly one of --enroll-speaker, --enroll-range, --enroll-file, --voiceprint")
    if a.voiceprint:
        vp = Voiceprint.from_dict(json.loads(Path(a.voiceprint).read_text("utf-8")))
        if vp.embedder != embedder.name:
            raise MlError(f"that voiceprint uses {vp.embedder!r}; run with --embedder {vp.embedder}")
        return vp
    if a.enroll_speaker:
        return enroll_from_speaker(samples, diar, a.enroll_speaker, embedder, cfg)
    if a.enroll_range:
        return enroll_from_range(samples, diar, a.enroll_range[0], a.enroll_range[1], embedder, cfg)
    f = load_canonical(a.enroll_file)
    file_diar = diarizer.diarize(f)
    diarizer.unload()          # one model on the GPU at a time: free it before the embedder loads
    return enroll_from_file(f, file_diar, embedder, cfg, name=Path(a.enroll_file).name)


def _setup(a):
    device = resolve_device(a.device)
    diarizer = CachedDiarizer(PyannoteDiarizer(device), cache_dir().parent / "diarization-cache")
    embedder = build_embedder(a.embedder, device)
    return device, diarizer, embedder


def cmd_run(a) -> int:
    device, diarizer, embedder = _setup(a)
    samples = load_canonical(a.input)
    log = StageLog(device)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with log.stage("diarize"):
        diar = diarizer.diarize(samples)
    diarizer.unload()
    analysis = analyze(samples, None, embedder, log, diarization=diar)
    for spk, vp in analysis.speaker_voiceprints.items():
        _dump(out / f"voiceprint_{spk}.json", vp.as_dict())
    with log.stage("enroll"):
        vp = make_voiceprint(a, samples, diar, embedder, diarizer)
    embedder.unload()
    match = MatchConfig.for_embedder(embedder.name)
    if a.target_threshold is not None:
        match.target_threshold = a.target_threshold
    if a.other_threshold is not None:
        match.other_threshold = a.other_threshold
    match.__post_init__()
    res = run_pipeline(samples, vp, diarization=diar, embedder=embedder, match=match, log=log)
    _dump(out / "diarization.json", diar.as_dict())
    _dump(out / "best_clean_spans.json", analysis.best_spans)
    _dump(out / "timeline.json", [r.as_dict() for r in res.regions])
    write_wav(str(out / "gated_baseline.wav"), res.output, SAMPLE_RATE)
    timing = log.as_dict()
    timing["audio_seconds"] = round(len(samples) / SAMPLE_RATE, 3)
    timing["real_time_factor"] = round(timing["total_seconds"] / max(timing["audio_seconds"], 1e-9), 3)
    _dump(out / "report.json", {
        "input": Path(a.input).name, "embedder": embedder.name, "diarizer": diarizer.model_id,
        "match": vars(match), "enrollment": vp.as_dict() | {"vector": "<omitted>"},
        "timing": timing,
        "output_samples": int(len(res.output)), "input_samples": int(len(samples)),
    })
    _dump(out / "voiceprint_target.json", vp.as_dict())
    for w in vp.warnings:
        print("warning:", w, file=sys.stderr)
    print(f"wrote results to {out}")
    return 0


def cmd_enroll(a) -> int:
    device, diarizer, embedder = _setup(a)
    samples = load_canonical(a.file)
    diar = diarizer.diarize(samples)
    diarizer.unload()
    cfg = EnrollmentConfig(min_clean_s=a.min_clean_s)
    vp = enroll_from_file(samples, diar, embedder, cfg, name=Path(a.file).name)
    embedder.unload()
    _dump(Path(a.save), vp.as_dict())
    for w in vp.warnings:
        print("warning:", w, file=sys.stderr)
    print(f"voiceprint saved to {a.save} ({vp.duration_s:.1f} s of clean speech)")
    return 0


def cmd_readiness(a) -> int:
    from .readiness import collect
    rep = collect(a.url, a.local_api)
    print(json.dumps(rep, indent=1))
    return 0 if rep["ready_for_gpu"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="focus_ml.voice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("input")
    p.add_argument("--out", required=True)
    p.add_argument("--embedder", choices=EMBEDDERS, default="ecapa")
    p.add_argument("--device", default="auto")
    p.add_argument("--target-threshold", type=float)
    p.add_argument("--other-threshold", type=float)
    _add_enroll_args(p)
    p = sub.add_parser("enroll")
    p.add_argument("--file", required=True)
    p.add_argument("--save", required=True)
    p.add_argument("--embedder", choices=EMBEDDERS, default="ecapa")
    p.add_argument("--device", default="auto")
    p.add_argument("--min-clean-s", type=float, default=4.0)
    p = sub.add_parser("readiness")
    p.add_argument("--url")
    p.add_argument("--local-api", action="store_true")
    a = ap.parse_args(argv)
    try:
        return {"run": cmd_run, "enroll": cmd_enroll, "readiness": cmd_readiness}[a.cmd](a)
    except MlError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
