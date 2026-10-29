"""Evaluate SI-SDRi for named runner2 outputs.
Usage: python eval_v2.py "name:ref.wav:est.wav" ["name2:ref2:est2" ...]
Prints per-case SI-SDR(mix), SI-SDR(est), SI-SDRi, lag. Mix is p1_mix.wav unless ref path differs.
"""
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import correlate

GT = "A:/focus/data/gt5"


def rd(p):
    y, sr = sf.read(p if os.path.isabs(p) else f"{GT}/{p}", dtype="float64")
    return y.mean(1) if y.ndim > 1 else y


def align(a, b, max_lag=800):
    c = correlate(b, a, mode="full", method="fft")
    mid = len(a) - 1
    seg = c[mid - max_lag:mid + max_lag + 1]
    lag = int(np.argmax(seg)) - max_lag
    if lag > 0:
        b = b[lag:]
    elif lag < 0:
        a = a[-lag:]
    n = min(len(a), len(b))
    return a[:n], b[:n], lag


def si_sdr(est, ref):
    est = est - est.mean()
    ref = ref - ref.mean()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    t = a * ref
    e = est - t
    return float(10 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(e, e) + 1e-12)))


rows = []
for spec in sys.argv[1:]:
    name, ref_f, est_f = spec.split(":")
    ref = rd(ref_f)
    mix = rd("p1_mix.wav")
    est = rd(est_f)
    e, r, lag = align(est.copy(), ref.copy())
    m, r2, _ = align(mix.copy(), ref.copy())
    n = min(len(e), len(m))
    rows.append({"case": name, "lag_ms": round(lag / 16, 2),
                 "si_sdr_mix": round(si_sdr(m[:n], r2[:n]), 2),
                 "si_sdr_est": round(si_sdr(e[:n], r[:n]), 2),
                 "si_sdri": round(si_sdr(e[:n], r[:n]) - si_sdr(m[:n], r2[:n]), 2),
                 "len": len(est), "nan": int(np.isnan(est).sum()), "inf": int(np.isinf(est).sum()),
                 "peak": round(float(np.max(np.abs(est))), 4)})
for r in rows:
    print(r)
json.dump(rows, open(f"{GT}/eval_v2_last.json", "w"), indent=1)
