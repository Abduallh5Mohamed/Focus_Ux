"""Runs the audio-only pipeline over an evaluation dataset and writes a run directory.

Library used by ``final_eval.py`` (one-command evaluation) and ``speed_tune.py``
(before/after measurements). The engine is injected, so the same code runs the
real models on the laptop and the tone fakes in the tests.

Output layout: see ``focus_eval.final_report`` (module docstring).
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from importlib import metadata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "product" / "packages" / "ml", ROOT / "product" / "packages" / "eval"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from focus_eval.audio import load_audio  # noqa: E402
from focus_eval.dataset import STATUS_READY, Dataset  # noqa: E402
from focus_eval.stress import CONDITIONS, degrade  # noqa: E402
from focus_eval.voice_metrics import verification_trials  # noqa: E402
from focus_eval.voice_mix import activity_segments  # noqa: E402
from focus_ml.isolation_engines import _ffmpeg, write_wav  # noqa: E402
from focus_ml.voice import preprocess  # noqa: E402
from focus_ml.voice.embedder import embed_segments  # noqa: E402
from focus_ml.voice.profile import ResourceMonitor, StageProfiler  # noqa: E402
from focus_ml.voice.types import SAMPLE_RATE, Segment  # noqa: E402

DEFAULT_SETTINGS = {
    "embedder": "ecapa", "device": "auto",
    "enroll": "ref",              # ref: enroll from the speaker's clean reference (a separate-recording proxy)
                                  # mix_span: enroll from the clean span found in the mixture itself
    "prefetch": True,             # decode the next clip on a CPU thread while the GPU works
    "keep_resident": [],          # models kept loaded between stages ([] = unload all, the validated default)
    "match_max_chunk_s": 3.0,     # region length used for voice matching
    "verification_utt_s": 2.0, "verification_enroll_n": 1,
    "stress": [],                 # synthetic degradation conditions to add (see focus_eval.stress)
    "visibility_check": True,
    "verification": True,
}


# -- environment record -------------------------------------------------------
def _version(name: str):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def environment_info() -> dict:
    gpu_name = vram = None
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram = round(torch.cuda.get_device_properties(0).total_memory / 2**20)
    except ImportError:
        pass
    rev = None
    try:
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=10).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "python": platform.python_version(), "platform": platform.platform(), "git_revision": rev,
        "gpu_name": gpu_name, "gpu_total_vram_mib": vram,
        "libraries": {n: _version(n) for n in ("numpy", "torch", "torchaudio", "speechbrain", "pyannote.audio")},
    }


# -- helpers --------------------------------------------------------------------
def _overlap_s(turns, spans) -> float:
    total = 0.0
    for t in turns:
        for a, b in spans:
            total += max(0.0, min(t["end"], b) - max(t["start"], a))
    return total


def pick_speaker(analysis: dict, reference_spans) -> dict | None:
    """The analysed voice that talks most where the reference is active (ground truth mapping)."""
    turns = analysis["diarization"]["turns"]
    best, best_s = None, 0.0
    for sp in analysis["speakers"]:
        s = _overlap_s([t for t in turns if t["speaker"] == sp["speaker"]], reference_spans)
        if s > best_s:
            best, best_s = sp, s
    return best


def _enroll(engine, settings, analysis, ref_path, ref_spans):
    """Voiceprint dict, or (None, reason) when enrolment is refused."""
    if settings["enroll"] == "ref":
        out = engine.enroll_file(str(ref_path))
        return out["voiceprint"], None
    sp = pick_speaker(analysis, ref_spans)
    if sp is None:
        return None, "no analysed voice matches this speaker"
    if not sp["usable"]:
        return None, sp["refusal"]
    return sp["voiceprint"], None


def _isolate_to(engine, audio_path, vp, analysis, dest: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="focus-eval-") as tmp:
        res = engine.isolate(str(audio_path), vp, analysis["diarization"], tmp)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(res.wav_path, dest)
    return res.details


def _total(profile: dict) -> float:
    return profile["total_seconds"]


def _blacked_out(video: Path, out: Path) -> bool:
    done = subprocess.run(
        [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-f", "lavfi", "-i",
         "color=c=black:s=320x240:r=25", "-map", "1:v", "-map", "0:a", "-shortest", "-c:v", "mpeg4",
         "-c:a", "pcm_s16le", str(out)], capture_output=True, text=True)
    return done.returncode == 0 and out.is_file()


def _audio_only(video: Path, out: Path) -> bool:
    done = subprocess.run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn",
                           "-c:a", "pcm_s16le", str(out)], capture_output=True, text=True)
    return done.returncode == 0 and out.is_file()


# -- the run --------------------------------------------------------------------
def verification_scores(ds: Dataset, engine, settings) -> dict:
    """Same/different-speaker scores, trials built per clip from the clean references."""
    utt, n_enroll = settings["verification_utt_s"], settings["verification_enroll_n"]
    tgt, oth = [], []
    for clip in ds.clips:
        if clip.status != STATUS_READY:
            continue
        vecs = {}
        for s in clip.speakers:
            x = load_audio(ds.path(s.ref_audio))
            chunks = []
            for a, b in activity_segments(x, SAMPLE_RATE, min_gap_s=0.5):
                t = a
                while t + utt <= b:
                    chunks.append(Segment(t, t + utt))
                    t += utt
            found = [embed_segments(engine.embedder, x, [c], min_s=0.5)[0] for c in chunks]
            vecs[s.id] = [v for v in found if v is not None]
        t_, o_ = verification_trials(vecs, enroll_n=n_enroll)
        tgt += t_
        oth += o_
    engine.embedder.unload()
    return {"scores": {"target": tgt, "other": oth},
            "thresholds": {"target_threshold": engine.match.target_threshold,
                           "other_threshold": engine.match.other_threshold},
            "parameters": {"utterance_s": utt, "enrollment_utterances": n_enroll,
                           "trials_per_clip": "within each clip, pooled across clips"}}


def visibility_check(ds: Dataset, engine, settings, work: Path) -> dict:
    """The output must not depend on the picture: original video, blacked-out video, audio only."""
    clips = {}
    for clip in ds.clips:
        if clip.status != STATUS_READY:
            continue
        video = ds.path(clip.video) if clip.video else None
        if video is None or not video.is_file():
            clips[clip.id] = {"status": "skipped", "reason": "no video file for this clip"}
            continue
        target = clip.targets[0]
        ref_spans = activity_segments(load_audio(ds.path(clip.speaker(target).ref_audio)))
        d = work / "visibility" / clip.id
        d.mkdir(parents=True, exist_ok=True)
        variants = {"video": video}
        if _blacked_out(video, d / "black.avi"):
            variants["black_video"] = d / "black.avi"
        if _audio_only(video, d / "audio.wav"):
            variants["audio_only"] = d / "audio.wav"
        if len(variants) < 3:
            clips[clip.id] = {"status": "skipped", "reason": "ffmpeg could not build the variants"}
            continue
        outputs = {}
        for name, path in variants.items():
            analysis = engine.analyze(str(path))
            vp, why = _enroll(engine, settings, analysis, ds.path(clip.speaker(target).ref_audio), ref_spans)
            if vp is None:
                outputs[name] = "refused: " + str(why)
                continue
            _isolate_to(engine, path, vp, analysis, d / f"{name}.out.wav")
            outputs[name] = (d / f"{name}.out.wav").read_bytes()
        refused = [v for v in outputs.values() if isinstance(v, str)]
        if refused:
            clips[clip.id] = {"status": "skipped", "reason": refused[0]}
            continue
        digests = {n: hashlib.sha256(b).hexdigest() for n, b in outputs.items()}
        clips[clip.id] = {"status": "checked", "identical": len(set(digests.values())) == 1,
                          "sha256": digests, "target": target}
    return {"clips": clips}


def produce_run(ds: Dataset, out_dir: str | Path, engine, settings: dict, *, label: str = "run",
                command: str | None = None, monitor: ResourceMonitor | None = None) -> dict:
    """Run every ready clip/target. Returns run.json's content (also written)."""
    settings = {**DEFAULT_SETTINGS, **settings}
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; refusing to mix two runs")
    out.mkdir(parents=True, exist_ok=True)
    own_monitor = monitor is None
    monitor = monitor or ResourceMonitor()
    if own_monitor:
        monitor.start()
    device = settings.get("device_resolved", "cpu")
    ready = [c for c in ds.clips if c.status == STATUS_READY]
    paths = [str(ds.path(c.mix_audio)) for c in ready]
    stream = preprocess.prefetch_decoded(paths) if settings["prefetch"] else ((p, None) for p in paths)
    bench, profile, failures = {}, {}, []
    decodes0 = preprocess.decode_count
    try:
        for clip, (_, _) in zip(ready, stream):
            mix_path = ds.path(clip.mix_audio)
            audio_s = len(load_audio(mix_path)) / SAMPLE_RATE
            prof = StageProfiler(device, monitor)
            engine.log = prof
            entry = {"audio_seconds": round(audio_s, 3), "targets": {}}
            try:
                analysis = engine.analyze(str(mix_path))
            except Exception as exc:   # recorded, never hidden; the CLI exits non-zero
                failures.append({"clip_id": clip.id, "stage": "analyze", "error": f"{type(exc).__name__}: {exc}"})
                bench[clip.id] = {"rtf": None, "n_failed": 1, "error": "analyze failed"}
                engine.log = None
                continue
            analysis_s = _total(prof.as_dict())
            entry["analysis"] = prof.as_dict()
            worst = 0.0
            failed = 0
            for target in clip.targets:
                tprof = StageProfiler(device, monitor)
                engine.log = tprof
                spk = clip.speaker(target)
                try:
                    ref_spans = activity_segments(load_audio(ds.path(spk.ref_audio)))
                    vp, why = _enroll(engine, settings, analysis, ds.path(spk.ref_audio), ref_spans)
                    if vp is None:
                        raise RuntimeError("enrolment refused: " + str(why))
                    details = _isolate_to(engine, mix_path, vp, analysis, out / clip.id / f"{target}.wav")
                    (out / clip.id / f"{target}.timeline.json").write_text(
                        json.dumps(details["regions"]), encoding="utf-8")
                except Exception as exc:
                    failed += 1
                    failures.append({"clip_id": clip.id, "target": target, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                d = tprof.as_dict()
                entry["targets"][target] = d
                worst = max(worst, _total(d))
            engine.log = None
            vrams = [entry["analysis"]["peak_vram_mib"]] + [t["peak_vram_mib"] for t in entry["targets"].values()]
            rams = [entry["analysis"]["peak_ram_mib"]] + [t["peak_ram_mib"] for t in entry["targets"].values()]
            entry["peak_vram_mib"] = max((v for v in vrams if v is not None), default=None)
            entry["peak_ram_mib"] = max((v for v in rams if v is not None), default=None)
            rtf = round((analysis_s + worst) / audio_s, 3) if audio_s and entry["targets"] else None
            entry["rtf"] = rtf
            bench[clip.id] = {"rtf": rtf, "n_failed": failed}
            profile[clip.id] = entry
        meta = {"label": label, "settings": settings, "command": command, "environment": environment_info(),
                "bench_by_clip": bench, "profile_by_clip": profile, "failures": failures,
                "audio_decodes": preprocess.decode_count - decodes0}
        engine.log = None
        if settings["stress"]:
            for cond in settings["stress"]:
                if cond not in CONDITIONS:
                    raise ValueError(f"unknown stress condition {cond!r}")
                _stress_condition(ds, engine, settings, out, cond, failures)
        if settings["verification"]:
            (out / "verification.json").write_text(
                json.dumps(verification_scores(ds, engine, settings)), encoding="utf-8")
        if settings["visibility_check"]:
            (out / "visibility.json").write_text(
                json.dumps(visibility_check(ds, engine, settings, out)), encoding="utf-8")
        meta["failures"] = failures
        (out / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return meta
    finally:
        engine.log = None
        if own_monitor:
            monitor.stop()


def _stress_condition(ds, engine, settings, out: Path, cond: str, failures: list) -> None:
    for clip in ds.clips:
        if clip.status != STATUS_READY:
            continue
        d = out / "stress" / cond / clip.id
        mix = degrade(load_audio(ds.path(clip.mix_audio)), cond, seed=0)
        d.mkdir(parents=True, exist_ok=True)
        write_wav(str(d / "mix.wav"), mix, SAMPLE_RATE)
        try:
            analysis = engine.analyze(str(d / "mix.wav"))
        except Exception as exc:
            failures.append({"clip_id": clip.id, "stage": f"stress/{cond}/analyze", "error": f"{type(exc).__name__}: {exc}"})
            continue
        for target in clip.targets:
            spk = clip.speaker(target)
            try:
                spans = activity_segments(load_audio(ds.path(spk.ref_audio)))
                vp, why = _enroll(engine, settings, analysis, ds.path(spk.ref_audio), spans)
                if vp is None:
                    raise RuntimeError("enrolment refused: " + str(why))
                _isolate_to(engine, d / "mix.wav", vp, analysis, d / f"{target}.wav")
            except Exception as exc:
                failures.append({"clip_id": clip.id, "target": target, "stage": f"stress/{cond}",
                                 "error": f"{type(exc).__name__}: {exc}"})


def build_real_engine(settings: dict):
    """Real models from the original environment (downloads disabled by the weights loader)."""
    from focus_ml.voice.diarizer import PyannoteDiarizer
    from focus_ml.voice.embedder import build_embedder
    from focus_ml.voice.engine import AudioOnlyEngine
    from focus_ml.voice.gpu import resolve_device
    from focus_ml.voice.match import MatchConfig
    from focus_ml.voice.profile import ResidencyPolicy

    device = resolve_device(settings.get("device", "auto"))
    settings["device_resolved"] = device
    embedder = build_embedder(settings["embedder"], device)
    match = MatchConfig.for_embedder(settings["embedder"])
    match.max_chunk_s = settings["match_max_chunk_s"]
    return AudioOnlyEngine(PyannoteDiarizer(device), embedder, match=match,
                           residency=ResidencyPolicy(tuple(settings["keep_resident"])))
