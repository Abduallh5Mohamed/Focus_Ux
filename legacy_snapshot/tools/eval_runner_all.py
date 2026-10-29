"""Consolidated SI-SDRi for runner outputs (A, B, downscale-A) vs their refs."""
import json

import numpy as np
import soundfile as sf
from scipy.signal import correlate

GT = "A:/focus/data/gt5"


def rd(p):
    y, sr = sf.read(p, dtype="float64")
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


cases = [("A", "p1_a_ref.wav", "run_a_warm0.wav"),
         ("B", "p1_b_ref.wav", "run_b_warm0.wav"),
         ("A_downscale0.5", "p1_a_ref.wav", "run_a_ds_warm0.wav"),
         ("B_downscale0.5", "p1_b_ref.wav", "run_b_ds_warm0.wav")]
rows = []
for name, ref_f, est_f in cases:
    try:
        ref = rd(f"{GT}/{ref_f}")
        mix = rd(f"{GT}/p1_mix.wav")
        est = rd(f"{GT}/{est_f}")
        e, r, lag = align(est.copy(), ref.copy())
        m, r2, _ = align(mix.copy(), ref.copy())
        n = min(len(e), len(m))
        rows.append({"case": name, "lag_ms": round(lag / 16, 2),
                     "si_sdr_mix": round(si_sdr(m[:n], r2[:n]), 2),
                     "si_sdr_est": round(si_sdr(e[:n], r[:n]), 2),
                     "si_sdri": round(si_sdr(e[:n], r[:n]) - si_sdr(m[:n], r2[:n]), 2)})
    except Exception as ex:
        rows.append({"case": name, "error": str(ex)[:120]})
for r in rows:
    print(r)
json.dump(rows, open(f"{GT}/runner_eval.json", "w"), indent=1)
