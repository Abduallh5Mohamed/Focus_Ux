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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clips", required=True, type=Path, help="folder of clean per-person videos")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--count", type=int, default=MIN_MIXES)
    args = ap.parse_args()
    plans = build(args.clips, args.out, args.count)
    print(f"Built {len(plans)} mixes in {args.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
