"""
align_eval.py — SI-SDRi per (pair, speaker), with lag alignment.

Usage:
    python align_eval.py --pairs p1 p2 p3 --dir A:\focus\data\gt
    python align_eval.py --self-test

Files expected per pair in --dir:
    <pair>_a_ref.wav   clean reference, speaker a   (16 kHz mono)
    <pair>_b_ref.wav   clean reference, speaker b
    <pair>_mix.wav     the mixture fed to the model
    <pair>_a_est.wav   model output for speaker a
    <pair>_b_est.wav   model output for speaker b

Sign convention (verified in verify2/logs/03_align_test.log):
    lag < 0  -> est is LATE  -> trim the head of est
    lag > 0  -> est is EARLY -> trim the head of ref
"""
import argparse
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import correlate

SR = 16000
MAX_LAG = 800          # +-50 ms at 16 kHz
EDGE_WARN = 0.9        # warn when |lag| >= 90% of MAX_LAG


def load(path, sr=SR):
    y, s = sf.read(path, dtype="float64", always_2d=True)
    y = y.mean(axis=1)
    if s != sr:
        n = int(round(len(y) * sr / s))
        y = np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y)
    return y


def lag_of(est, ref, max_lag=MAX_LAG):
    """negative = est is late, positive = est is early."""
    c = correlate(ref, est, mode="full", method="fft")
    mid = len(est) - 1
    lo, hi = mid - max_lag, mid + max_lag + 1
    seg = c[lo:hi]
    lag = int(np.argmax(seg)) - max_lag
    edge = abs(lag) >= EDGE_WARN * max_lag
    return lag, edge


def align(est, ref, max_lag=MAX_LAG):
    lag, edge = lag_of(est, ref, max_lag)
    if lag > 0:
        ref = ref[lag:]
    elif lag < 0:
        est = est[-lag:]
    n = min(len(est), len(ref))
    return est[:n], ref[:n], lag, edge


def si_sdr(est, ref):
    est = est - est.mean()
    ref = ref - ref.mean()
    a = np.dot(est, ref) / (np.dot(ref, ref) + 1e-12)
    t = a * ref
    e = est - t
    return 10.0 * np.log10((np.dot(t, t) + 1e-12) / (np.dot(e, e) + 1e-12))


def eval_pair(pair, d, verbose=True):
    rows = []
    mix = load(os.path.join(d, f"{pair}_mix.wav"))
    for who in ("a", "b"):
        p_ref = os.path.join(d, f"{pair}_{who}_ref.wav")
        p_est = os.path.join(d, f"{pair}_{who}_est.wav")
        if not (os.path.exists(p_ref) and os.path.exists(p_est)):
            if verbose:
                print(f"  MISSING: {p_ref if not os.path.exists(p_ref) else p_est}")
            continue
        ref = load(p_ref)
        est = load(p_est)

        est_a, ref_a, lag, edge = align(est.copy(), ref.copy())
        if edge and verbose:
            print(f"  WARNING {pair}/{who}: |lag|={abs(lag)} hit the search window "
                  f"(+-{MAX_LAG}) — the offset is outside range, result is unreliable")
        s_mix = si_sdr(*align(mix.copy(), ref.copy())[:2])
        s_est = si_sdr(est_a, ref_a)
        rows.append(dict(pair=pair, who=who, lag_ms=round(lag / SR * 1000, 2),
                         sdr_mix=round(s_mix, 2), sdr_est=round(s_est, 2),
                         sdr_i=round(s_est - s_mix, 2), edge=edge))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=[])
    ap.add_argument("--dir", default=r"A:\focus\data\gt")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()

    if a.self_test:
        rng = np.random.default_rng(0)
        n = SR * 5
        t = np.arange(n) / SR
        ref = sum(np.sin(2 * np.pi * 150 * k * t) / k for k in range(1, 8)) * \
            (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)) ** 2
        interf = sum(np.sin(2 * np.pi * 230 * k * t) / k for k in range(1, 8))
        est = ref + 0.1 * interf
        est = np.concatenate([np.zeros(320), est])[:n]          # 20 ms late
        e, r, lag, edge = align(est, ref)
        print(f"self-test: injected 320-sample delay -> lag={lag} "
              f"({lag/SR*1000:.1f} ms), SI-SDR after align = {si_sdr(e, r):.2f} dB")
        assert lag == -320, f"expected -320, got {lag}"
        print("self-test OK")
        return

    print(f"{'pair':<6}{'who':<5}{'lag_ms':>9}{'SI-SDR mix':>13}{'SI-SDR est':>13}{'SI-SDRi':>10}")
    all_rows = []
    for p in a.pairs:
        all_rows += eval_pair(p, a.dir)
    for r in all_rows:
        flag = "  <-- edge" if r["edge"] else ""
        print(f"{r['pair']:<6}{r['who']:<5}{r['lag_ms']:>9}{r['sdr_mix']:>13}{r['sdr_est']:>13}"
              f"{r['sdr_i']:>10}{flag}")
    if all_rows:
        print(f"\nmean SI-SDRi = {np.mean([r['sdr_i'] for r in all_rows]):.2f} dB "
              f"over {len(all_rows)} rows")


if __name__ == "__main__":
    sys.exit(main())
