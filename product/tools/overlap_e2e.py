"""End-to-end FOCUS test with REAL models: pyannote diarization, voice enrollment, WeSep overlap extraction.

  python product\\tools\\overlap_e2e.py --recording meeting.wav --enrollment target_enroll.wav --out e2e-out

Run it only after overlap_minimal_infer.py succeeded. The extractor is enabled here by an explicit opt-in
(constructor argument), never through a changed default. Runs the preflight first and stops if it fails.
Writes: preflight.json, enrollment.json, diarization.json, strict/isolated.wav, continuity/isolated.wav,
mixture.wav, enrollment.wav, e2e_report.json (routing evidence: overlap seconds, windows sent to WeSep,
pieces kept or muted, fallback flags).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product"), str(ROOT / "product" / "packages" / "ml")]


def routing_proved_extraction(routing: dict) -> tuple[bool, str]:
    """True only when overlap audio really went through the extractor and some of it was kept."""
    if routing.get("overlap_extraction") != "ran":
        return False, f"overlap_extraction = {routing.get('overlap_extraction')!r}"
    h = routing.get("hybrid") or {}
    if not (h.get("overlap_seconds") or 0) > 0:
        return False, "no overlapping speech was found by diarization, so nothing was tested"
    if not (h.get("windows") or 0) > 0:
        return False, "no window was sent to the extractor"
    if not any(p.get("status") == "extracted" for p in h.get("pieces") or []):
        return False, "every extracted piece was muted by the voiceprint/silence check"
    return True, "overlap was sent to the extractor and extracted speech was kept"


def main() -> int:
    from focus_ml.overlap.candidates import build_candidate
    from focus_ml.overlap.preflight import run_preflight
    from focus_ml.voice.embedder import build_embedder
    from focus_ml.voice.engine import AudioOnlyEngine
    from focus_ml.voice.gpu import resolve_device
    from focus_ml.voice.routing import CONTINUITY, STRICT, RoutingConfig

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recording", type=Path, required=True)
    ap.add_argument("--enrollment", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--candidate", default="wesep_bsrnn")
    a = ap.parse_args()
    pre = run_preflight(a.candidate)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "preflight.json").write_text(json.dumps(pre, indent=2))
    if not pre["ok"]:
        print("Preflight failed; nothing was run: " + pre["verdict"], file=sys.stderr)
        return 2
    from focus_ml.voice.diarizer import PyannoteDiarizer
    device = resolve_device("auto")
    embedder = build_embedder("ecapa", device)
    shutil.copyfile(a.recording, a.out / "mixture.wav")
    shutil.copyfile(a.enrollment, a.out / "enrollment.wav")
    report = {"candidate": a.candidate, "device": device, "global_default": "unchanged (extractor disabled)",
              "opt_in": "explicit constructor argument in overlap_e2e.py", "runs": {}}
    base = AudioOnlyEngine(PyannoteDiarizer(), embedder)
    analysis = base.analyze(str(a.recording))
    diar = analysis["diarization"]
    (a.out / "diarization.json").write_text(json.dumps(diar, indent=2))
    enr = base.enroll_file(str(a.enrollment), "target")
    (a.out / "enrollment.json").write_text(json.dumps(enr, indent=2))
    report["speakers_found"] = [s["speaker"] for s in analysis["speakers"]]
    for mode in (STRICT, CONTINUITY):
        d = a.out / mode
        d.mkdir(exist_ok=True)
        extractor = build_candidate(a.candidate, device="cuda", embedder=embedder)
        eng = AudioOnlyEngine(PyannoteDiarizer(), embedder, routing=RoutingConfig(mode=mode),
                              overlap_extractor=extractor)
        res = eng.isolate(str(a.recording), enr["voiceprint"], diar, str(d), enrollment_audio_path=str(a.enrollment))
        routing = res.details.get("routing", {})
        hyb = routing.get("hybrid") or routing.get("extractor_report") or {}
        report["runs"][mode] = {"wav": str(Path(mode) / "isolated.wav"), "warnings": res.warnings,
                                "routing": routing, "timings": res.timings,
                                "overlap_routed_to_extractor": routing_proved_extraction(routing)[0],
                                "overlap_check": routing_proved_extraction(routing)[1],
                                "extractor_detail": hyb}
        print(mode, "overlap_extraction =", routing.get("overlap_extraction"),
              "fallback_used =", routing.get("fallback_used"), "claim =", routing.get("isolation_claim"))
    (a.out / "e2e_report.json").write_text(json.dumps(report, indent=2, default=str))
    ok = all(r["overlap_routed_to_extractor"] for r in report["runs"].values())
    print("PASS: overlapping speech was sent to " + a.candidate if ok else
          "FAIL: overlap was NOT extracted; see e2e_report.json (fallback is labelled not_isolation)")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("Failed: " + str(getattr(exc, "message", exc)), file=sys.stderr)
        sys.exit(1)
