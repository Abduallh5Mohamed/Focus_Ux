"""Compare the overlap extractors on the overlap test set and write the report.

  python product/tools/overlap_bakeoff.py --set overlap-set --out bakeoff-out \
         [--candidates wesep_bsrnn usef_tse ...] [--real-dir real-clips] [--embedder ecapa]

Writes report.html (tables + blind-listening players), report.json, rows.json and
decision.md. A candidate that cannot run (missing weights, package, broken code,
out of GPU memory) is reported as blocked with the evidence; the others still run.
Nothing is downloaded: run Setup-Overlap.cmd first (approval-first).

--real-dir holds real recordings: <name>.wav, <name>.enroll.wav and <name>.regions.json
([{"start":0.0,"end":3.2,"label":"target|other|overlap"}]); they get players, not scores.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "product" / "packages" / "eval"), str(ROOT / "product" / "packages" / "ml")]


def main():
    from focus_ml.overlap.bakeoff import run_bakeoff
    from focus_ml.overlap.candidates import INFO, ORDER, build_candidate
    from focus_ml.overlap.hybrid import HybridConfig
    from focus_ml.voice.embedder import EMBEDDERS, build_embedder
    from focus_ml.voice.gpu import resolve_device

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", required=True, type=Path, help="output folder of overlap_set.py")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--candidates", nargs="+", default=list(ORDER), choices=ORDER)
    ap.add_argument("--real-dir", type=Path)
    ap.add_argument("--embedder", default="ecapa", choices=EMBEDDERS)
    ap.add_argument("--device", default="auto")
    ap.add_argument("--no-fp16", action="store_true")
    ap.add_argument("--clearervoice-dir", help="the Setup-ClearerVoice folder (MossFormer2 weights)")
    ap.add_argument("--vram-budget-mib", type=float, default=3500.0)
    ap.add_argument("--batch-size", type=int)
    ap.add_argument("--max-mixes", type=int)
    a = ap.parse_args()

    device = resolve_device(a.device)
    embedder = build_embedder(a.embedder, device)
    clearer = a.clearervoice_dir
    if clearer is None:
        import os
        local = os.environ.get("LOCALAPPDATA")
        clearer = str(Path(local) / "FocusClearerVoice") if local else None

    def build(name):
        return build_candidate(name, device=device, fp16=not a.no_fp16, embedder=embedder,
                               clearervoice_dir=clearer)

    basis = {"data": "synthetic mixes from solo recordings", "device": device, "regions": "oracle (ground truth)",
             "caveat": "Only an Egyptian-Arabic set run on the RTX 3050 counts as the acceptance measurement."}
    cfg = HybridConfig(vram_budget_mib=a.vram_budget_mib, batch_size=a.batch_size)
    report = run_bakeoff(a.set, a.out, a.candidates, build, embedder, basis, INFO, cfg, a.real_dir,
                         max_mixes=a.max_mixes)
    print(report["decision"]["text"])
    print("Report:", a.out / "report.html")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Failed: " + str(getattr(exc, "message", exc)), file=sys.stderr)
        sys.exit(1)
