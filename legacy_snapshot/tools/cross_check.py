"""Cross-check that each estimate matches its OWN reference, not the other speaker."""
import json

import numpy as np
import soundfile as sf
from scipy.signal import correlate

GT = "A:/focus/data/gt5"


def rd(p):
    y, sr = sf.read(GT + "/" + p, dtype="float64")
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
    return a[:n], b[:n]


def si_sdr(est, ref):
    est = est - est.mean()
    ref = ref - ref.mean()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    t = a * ref
    e = est - t
    return float(10 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(e, e) + 1e-12)))


ra, rb = rd("p1_a_ref.wav"), rd("p1_b_ref.wav")
ea, eb = rd("p1_a_est.wav"), rd("p1_b_est.wav")
res = {}
for name, est, ref in [("estA_vs_refA", ea, ra), ("estA_vs_refB", ea, rb),
                       ("estB_vs_refB", eb, rb), ("estB_vs_refA", eb, ra)]:
    a, b = align(est.copy(), ref.copy())
    res[name] = round(si_sdr(a, b), 2)
print(json.dumps(res, indent=1))
json.dump(res, open(GT + "/cross_check.json", "w"), indent=1)
