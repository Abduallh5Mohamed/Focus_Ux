"""Acceptance cases A-D through the production routing path with real inference (GPU).

Run ONLY after overlap_minimal_infer.py succeeded and you listened to its output.

  python product\\tools\\overlap_acceptance.py --candidate wesep_bsrnn --enrollment target_enroll.wav ^
      --target target_clean.wav --other other1_clean.wav --other other2_clean.wav --out acceptance-out

Clean recordings are cut/looped to 8 s and summed, so SI-SDRi has references. Per case it writes
mixture, strict output ("final"), continuity output and the extractor-only target estimate, plus
results.json (target retention, leakage, SI-SDRi, silent %, time, peak VRAM, sync). Case D is run
only when the model declares 3+ speaker support. Regions are ground truth (oracle), which isolates
the extractor; end-to-end diarization is a separate measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product"), str(ROOT / "product" / "packages" / "ml")]


def main() -> int:
    import numpy as np
    from focus_ml.isolation_engines import write_wav
    from focus_ml.overlap.acceptance import CASES, build_case, score_case
    from focus_ml.overlap.base import ENROLL_MAX_S, trim_enrollment, vram_peak_mib, vram_reset
    from focus_ml.overlap.candidates import INFO, ORDER, build_candidate
    from focus_ml.overlap.hybrid import HybridExtractor
    from focus_ml.overlap.preflight import run_preflight
    from focus_ml.voice.embedder import build_embedder
    from focus_ml.voice.gpu import resolve_device
    from focus_ml.voice.preprocess import load_canonical
    from focus_ml.voice.routing import CONTINUITY, STRICT, RoutedExtractor, RoutingConfig
    from focus_ml.voice.types import SAMPLE_RATE, Voiceprint

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidate", default="wesep_bsrnn", choices=ORDER)
    ap.add_argument("--enrollment", type=Path, required=True)
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--other", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seconds", type=float, default=8.0)
    a = ap.parse_args()
    pre = run_preflight(a.candidate)
    if not pre["ok"]:
        print("Preflight failed; nothing was run: " + pre["verdict"], file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    load = lambda p: load_canonical(str(p)).copy()  # noqa: E731
    embedder = build_embedder("ecapa", resolve_device("auto"))
    ref = trim_enrollment(load(a.enrollment), ENROLL_MAX_S)
    vp = Voiceprint([float(v) for v in embedder.embed(ref)], embedder.name, len(ref) / SAMPLE_RATE, {})
    extractor = build_candidate(a.candidate, device="cuda", embedder=embedder)
    info = INFO[a.candidate]
    target, others = load(a.target), [load(p) for p in a.other]
    results = []
    for case in CASES:
        if case == "D" and "overlap_3plus" not in info.categories:
            results.append({"case": "D", "status": "not run: the model does not declare 3+ speaker support"})
            continue
        try:
            mix, t, o, regions = build_case(case, target, others, a.seconds)
        except ValueError as exc:
            results.append({"case": case, "status": f"not run: {exc}"})
            continue
        row = {"case": case, "model_mechanism": info.mechanism}
        for mode in (STRICT, CONTINUITY):
            routed = RoutedExtractor(HybridExtractor(extractor, vp, ref, embedder), RoutingConfig(mode=mode))
            vram_reset()
            t0 = time.perf_counter()
            out = routed.extract(mix, regions)
            dt = time.perf_counter() - t0
            m = score_case(case, out, mix, t, o, dt, vram_peak_mib())
            m["fallback_used"] = routed.last_report["fallback_used"]
            m["isolation_claim"] = routed.last_report["isolation_claim"]
            row[mode] = m
            write_wav(str(a.out / f"case{case}_{'final' if mode == STRICT else 'continuity'}.wav"), out, SAMPLE_RATE)
        write_wav(str(a.out / f"case{case}_mixture.wav"), mix, SAMPLE_RATE)
        row["extractor_only_gpu_report"] = routed.hybrid.last_report
        results.append(row)
    write_wav(str(a.out / "enrollment_reference.wav"), ref, SAMPLE_RATE)
    (a.out / "results.json").write_text(json.dumps(
        {"candidate": info.as_dict(), "gpu": pre["probes"].get("gpu"), "preflight": pre["verdict"],
         "regions": "oracle", "results": results}, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("Failed: " + str(getattr(exc, "message", exc)), file=sys.stderr)
        sys.exit(1)
