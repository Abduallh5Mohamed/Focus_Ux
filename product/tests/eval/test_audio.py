import numpy as np
import pytest

from eval_helpers import SR, voice, write_wav
from focus_eval.audio import AudioError, align, aligned_si_sdr, lag_of, load_audio, si_sdr


def test_known_delay_is_recovered_with_legacy_sign():
    ref = voice(150, 1, 5.0)
    est = np.concatenate([np.zeros(320), ref])[: len(ref)]  # 20 ms late
    lag, edge = lag_of(est, ref)
    assert lag == -320 and not edge
    e, r, _, _ = align(est, ref)
    assert si_sdr(e, r) > 40


def test_early_estimate_has_positive_lag():
    ref = voice(150, 1, 5.0)
    est = ref[200:]
    assert lag_of(est, ref)[0] == 200


def test_si_sdr_orders_clean_above_interfered():
    a, b = voice(150, 1), voice(230, 2)
    assert aligned_si_sdr(a + 0.05 * b, a)[0] > aligned_si_sdr(a + b, a)[0]
    assert aligned_si_sdr(b, a)[0] < -10


def test_lag_at_search_edge_is_flagged():
    ref = voice(150, 1, 5.0)
    est = np.concatenate([np.zeros(790), ref])[: len(ref)]
    assert lag_of(est, ref)[1] is True


def test_load_stereo_and_resample(tmp_path):
    sig = voice(150, 1, 2.0)
    write_wav(tmp_path / "s.wav", sig, rate=8000, channels=2)
    out = load_audio(tmp_path / "s.wav")
    assert abs(len(out) - len(sig) * 2) <= 1
    assert out.ndim == 1


def test_bad_files_raise(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"not a wav")
    with pytest.raises(AudioError):
        load_audio(tmp_path / "x.wav")
