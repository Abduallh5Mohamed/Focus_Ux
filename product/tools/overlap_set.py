"""Build the overlap test set from solo recordings: 2- and 3+-person overlap,
target quieter / equal / louder, and background noise at several levels.

  python product/tools/overlap_set.py --solo-dir solo --out overlap-set --language egyptian_arabic \
         [--noise-dir musan/noise] [--count 24]

solo/ holds <speaker>*.wav (>= 3 speakers, >= 25 s each). The first 12 s of every
speaker is saved as their enrollment recording and is never used in a mix.
Noise: files from --noise-dir (MUSAN noise is CC-BY-4.0; you download it, nothing is
fetched here). Without --noise-dir white noise is used and the set says so.
Audio only. Every mix has exact references and plan-based region truth.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "eval"), str(ROOT / "product" / "packages" / "ml")]

SR = 16000
ENROLL_S = 12


def _noise_bank(noise_dir: Path | None, load):
    if noise_dir is None:
        return None
    files = sorted(p for p in noise_dir.rglob("*.wav"))
    if not files:
        raise ValueError(f"no .wav noise files in {noise_dir}")
    return [(p, load(p)) for p in files[:200]]


def build(solo_dir: Path, out: Path, language: str, count: int | None, noise_dir: Path | None,
          seed: int = 0) -> list[dict]:
    from focus_eval.audio import load_audio
    from focus_eval.overlap_mix import condition_grid, regions_from_plan, scenario_plan
    from focus_eval.voice_mix import build_mix
    from focus_ml.isolation_engines import write_wav

    solo: dict[str, list] = {}
    for f in sorted(solo_dir.glob("*.wav")):
        solo.setdefault(f.stem.split("__")[0], []).append(f)
    if len(solo) < 3:
        raise ValueError(f"need at least 3 speakers, found {len(solo)}")
    full = {s: np.concatenate([load_audio(p) for p in fs]) for s, fs in solo.items()}
    short = [s for s, x in full.items() if len(x) < SR * (ENROLL_S + 13)]
    if short:
        raise ValueError(f"these speakers have less than {ENROLL_S + 13} s of audio: {sorted(short)}")
    (out / "enroll").mkdir(parents=True, exist_ok=True)
    audio = {}
    for s, x in full.items():
        write_wav(str(out / "enroll" / f"{s}.wav"), x[:SR * ENROLL_S], SR)
        audio[s] = x[SR * ENROLL_S:]
    bank = _noise_bank(noise_dir, load_audio)
    rng = np.random.default_rng(seed)
    names = sorted(audio)
    metas = []
    for i, cond in enumerate(condition_grid(count)):
        target = names[i % len(names)]
        pool = [s for s in names if s != target]
        others = [str(s) for s in rng.choice(pool, cond["n_overlap"] - 1, replace=False)]
        plan = scenario_plan(cond["n_overlap"], target, others)
        clips = {}
        for s in {target, *others}:
            need = int(SR * sum(p["length"] for p in plan if p["speaker"] == s))
            off = int(rng.integers(0, 1 + len(audio[s]) - need))
            clips[s] = audio[s][off:]
        gains = {target: cond["target_rel_db"], **{o: 0.0 for o in others}}
        total_s = max(p["start"] + p["length"] for p in plan)
        noise, noise_source = None, None
        if cond["snr_db"] is not None:
            if bank:
                path, data = bank[int(rng.integers(0, len(bank)))]
                off = int(rng.integers(0, max(1, len(data) - int(SR * total_s))))
                noise, noise_source = data[off:], f"file:{path.name}"
            else:
                noise, noise_source = rng.standard_normal(int(SR * total_s)) * 0.05, "white_gaussian (not MUSAN)"
        mix, refs, _ = build_mix(clips, plan, gains, noise, cond["snr_db"])
        d = out / f"mix{i + 1:02d}"
        d.mkdir(exist_ok=True)
        write_wav(str(d / "mix.wav"), mix, SR)
        for s, ref in refs.items():
            write_wav(str(d / f"ref_{s}.wav"), ref, SR)
        meta = {"id": d.name, "target": target, "others": others, **cond, "noise_source": noise_source,
                "seconds": len(mix) / SR, "plan": plan, "regions": regions_from_plan(plan)}
        (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        metas.append(meta)
    (out / "set.json").write_text(json.dumps({
        "language": language, "noise_dir": str(noise_dir) if noise_dir else None, "mixes": len(metas),
        "region_truth": "turn-level, from the mixing plan (oracle)", "seed": seed}, indent=1), encoding="utf-8")
    return metas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--language", required=True,
                    help="what the recordings are, e.g. egyptian_arabic (recorded in the set and the report)")
    ap.add_argument("--noise-dir", type=Path)
    ap.add_argument("--count", type=int, help="subset size (default: every condition, 24 mixes)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    metas = build(a.solo_dir, a.out, a.language, a.count, a.noise_dir, a.seed)
    print(f"Built {len(metas)} overlap mixes in {a.out}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
