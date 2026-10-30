"""Build a 3-speaker test set by digitally mixing clean single-person videos.

Input: a folder with >= 3 clean videos (one person each, ~15 s, recorded on a
phone). Output: >= 10 mixes, each with mix.mp4 (the three people side by side,
mixed audio), mix.wav, a clean reference WAV per speaker, and meta.json
(left-to-right speaker order, gains). References are the exact gained signals
that were summed, so SI-SDRi uses real numbers.
"""
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 16000
FPS = 25
MIN_MIXES = 10
ENROLL_S = 12
TILE_HEIGHT = 360


def plan_mixes(people: list[str], count: int = MIN_MIXES, seed: int = 0) -> list[dict]:
    """Deterministic plan: every left-to-right ordering of every triple, with a
    gain profile per repeat, until `count` mixes exist."""
    if len(people) < 3:
        raise ValueError("at least 3 clean person videos are needed")
    rng = np.random.default_rng(seed)
    orders = [list(p) for t in itertools.combinations(sorted(people), 3)
              for p in itertools.permutations(t)]
    plans, i = [], 0
    while len(plans) < max(count, MIN_MIXES):
        order = orders[i % len(orders)]
        gains = [0.0, 0.0, 0.0] if i < len(orders) else [float(g) for g in rng.uniform(-4, 4, 3)]
        plans.append({"id": f"mix{len(plans) + 1:02d}", "order": order, "gains_db": gains})
        i += 1
    return plans


def mix_signals(signals: list[np.ndarray], gains_db: list[float]):
    """Sum gained signals; refs share the mix's scaling so mix == sum(refs)."""
    n = min(len(s) for s in signals)
    gained = [s[:n].astype(np.float64) * 10 ** (g / 20) for s, g in zip(signals, gains_db)]
    mix = np.sum(gained, axis=0)
    peak = max(float(np.abs(mix).max()), 1e-9)
    scale = 0.9 / peak if peak > 0.9 else 1.0
    return mix * scale, [g * scale for g in gained]


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _run(cmd):
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + done.stderr[-400:])


def _load_audio(video: Path, out_wav: Path) -> np.ndarray:
    import soundfile as sf
    _run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ar", str(SR),
          "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)])
    data, _ = sf.read(out_wav, dtype="float32")
    return data


def build(src: Path, out: Path, count: int = MIN_MIXES, seed: int = 0) -> list[dict]:
    import soundfile as sf
    videos = {p.stem: p for p in sorted(src.iterdir())
              if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")}
    plans = plan_mixes(list(videos), count, seed)
    out.mkdir(parents=True, exist_ok=True)
    cache = {n: _load_audio(p, out / f"_clean_{n}.wav") for n, p in videos.items()}
    for plan in plans:
        d = out / plan["id"]
        d.mkdir(exist_ok=True)
        mix, refs = mix_signals([cache[n] for n in plan["order"]], plan["gains_db"])
        sf.write(d / "mix.wav", mix, SR, subtype="PCM_16")
        for pos, ref in enumerate(refs):
            sf.write(d / f"ref_{pos}.wav", ref, SR, subtype="PCM_16")
        seconds = len(mix) / SR
        inputs, filters = [], []
        for pos, name in enumerate(plan["order"]):
            inputs += ["-i", str(videos[name])]
            filters.append(f"[{pos}:v]fps={FPS},scale=-2:{TILE_HEIGHT},setsar=1[v{pos}]")
        graph = ";".join(filters) + ";[v0][v1][v2]hstack=inputs=3[v]"
        _run([_ffmpeg(), "-y", "-loglevel", "error", *inputs, "-i", str(d / "mix.wav"),
              "-filter_complex", graph, "-map", "[v]", "-map", "3:a", "-t", f"{seconds:.3f}",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "mix.mp4")])
        (d / "meta.json").write_text(json.dumps({**plan, "seconds": seconds}, indent=1))
    (out / "plan.json").write_text(json.dumps(plans, indent=1))
    return plans


def build_from_solo(src: Path, out: Path, speakers_per_mix: int = 3, overlap_s: float = 1.5,
                    count: int = MIN_MIXES, turn_s: float = 4.0, turns: int = 6,
                    snr_db: float | None = None, seed: int = 0) -> list[dict]:
    """Ground-truth audio mixes from solo recordings (``<speaker>*.wav`` in ``src``).

    Writes per mix: mix.wav, ref_<speaker>.wav (full length, each speaker's exact
    gained signal), truth.json (who spoke when) and meta.json. Overlap between
    consecutive turns is ``overlap_s`` seconds (0 = none). Audio only.
    """
    root = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(root / "product" / "packages" / "eval"), str(root / "product" / "packages" / "ml")]
    from focus_eval.audio import load_audio
    from focus_eval.voice_mix import build_mix, plan_conversation
    from focus_ml.isolation_engines import write_wav
    solo: dict[str, list] = {}
    for f in sorted(src.glob("*.wav")):
        solo.setdefault(f.stem.split("__")[0], []).append(f)
    if len(solo) < speakers_per_mix:
        raise ValueError(f"need at least {speakers_per_mix} speakers, found {len(solo)}")
    full = {s: np.concatenate([load_audio(p) for p in fs]) for s, fs in solo.items()}
    # The first ENROLL_S of every speaker is kept OUT of the mixes and saved as the
    # separate enrollment recording, so enrollment never hears the mixed material.
    enroll_dir = out / "enroll"
    enroll_dir.mkdir(parents=True, exist_ok=True)
    audio = {}
    for s, x in full.items():
        write_wav(str(enroll_dir / f"{s}.wav"), x[:SR * ENROLL_S], SR)
        audio[s] = x[SR * ENROLL_S:]
    rng = np.random.default_rng(seed)
    names = sorted(audio)
    out.mkdir(parents=True, exist_ok=True)
    plans = []
    for i in range(max(count, 1)):
        chosen = [str(s) for s in rng.choice(names, speakers_per_mix, replace=False)]
        plan = plan_conversation(chosen, turns, turn_s, overlap_s)
        offsets = {s: int(rng.integers(0, 1 + max(0, len(audio[s]) - SR * turn_s * turns))) for s in chosen}
        clips = {s: audio[s][offsets[s]:] for s in chosen}
        gains = {s: float(rng.uniform(-4, 4)) for s in chosen}
        noise = rng.standard_normal(SR * 10) * 0.05 if snr_db is not None else None
        mix, refs, truth = build_mix(clips, plan, gains, noise, snr_db)
        d = out / f"mix{i + 1:02d}"
        d.mkdir(exist_ok=True)
        write_wav(str(d / "mix.wav"), mix, SR)
        for s, ref in refs.items():
            write_wav(str(d / f"ref_{s}.wav"), ref, SR)
        meta = {"id": d.name, "speakers": chosen, "overlap_s": overlap_s, "gains_db": gains,
                "snr_db": snr_db, "seconds": len(mix) / SR, "plan": plan}
        (d / "truth.json").write_text(json.dumps({"seconds": len(mix) / SR, "segments": truth}, indent=1))
        (d / "meta.json").write_text(json.dumps(meta, indent=1))
        plans.append(meta)
    return plans


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--solo-dir", type=Path, help="audio-only mode: folder of <speaker>*.wav solo recordings")
    ap.add_argument("--speakers-per-mix", type=int, default=3, choices=(2, 3, 4))
    ap.add_argument("--overlap-s", type=float, default=1.5)
    ap.add_argument("--snr-db", type=float)
    ap.add_argument("--clips", type=Path, help="folder of clean per-person videos")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--count", type=int, default=MIN_MIXES)
    args = ap.parse_args()
    if args.solo_dir:
        plans = build_from_solo(args.solo_dir, args.out, args.speakers_per_mix, args.overlap_s,
                                args.count, snr_db=args.snr_db)
        print(f"Built {len(plans)} audio mixes with ground truth in {args.out}")
        return
    if not args.clips:
        ap.error("give --clips (video mode) or --solo-dir (audio mode)")
    plans = build(args.clips, args.out, args.count)
    print(f"Built {len(plans)} mixes in {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
