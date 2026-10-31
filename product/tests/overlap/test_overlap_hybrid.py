import numpy as np
import pytest

from fakes import SR, FakeEmbedder, scene, tone
from helpers import ToneExtractor, enrollment_for, voiceprint_for
from focus_ml.engine_report import si_sdr
from focus_ml.overlap.base import BlockedError
from focus_ml.overlap.hybrid import (HybridConfig, HybridExtractor, compose, merge_spans, overlap_spans,
                                     plan_region_windows, split_check_chunks, subtract_spans)
from focus_ml.voice.types import OTHER, TARGET, UNCERTAIN, LabelledRegion


def R(a, b, label, reason="x"):
    return LabelledRegion(a, b, label, None, None, reason)


def hybrid(ex, **cfg):
    return HybridExtractor(ex, voiceprint_for("A"), enrollment_for("A"), FakeEmbedder(), HybridConfig(**cfg))


def test_window_selection_only_overlap_minus_target():
    regs = [R(0, 4, TARGET), R(4, 8, UNCERTAIN, "overlap"), R(8, 12, OTHER), R(12, 13, UNCERTAIN, "low_confidence"),
            R(3, 5, UNCERTAIN, "overlap")]
    spans = overlap_spans(regs, 13 * SR)
    assert spans == [(4 * SR, 8 * SR)]
    assert subtract_spans([(0, 10)], [(2, 4), (6, 20)]) == [(0, 2), (4, 6)]
    assert merge_spans([(5, 9), (0, 3), (2, 4)]) == [(0, 4), (5, 9)]


def test_region_windows_short_centered_long_covers():
    n, w = 20 * SR, 4 * SR
    (s, e), = plan_region_windows(9 * SR, 11 * SR, n, w, 0.5)
    assert e - s == w and s <= 9 * SR and e >= 11 * SR
    (s, e), = plan_region_windows(0, SR, n, w, 0.5)
    assert s == 0
    wins = plan_region_windows(2 * SR, 12 * SR, n, w, 0.5)
    assert wins[0][0] == 2 * SR and wins[-1][1] == 12 * SR and all(b - a == w for a, b in wins)


def test_check_chunks():
    parts = split_check_chunks(0, 10 * SR, 3 * SR, SR // 2)
    assert parts[0][0] == 0 and parts[-1][1] == 10 * SR and all(b - a <= 3 * SR for a, b in parts)
    assert split_check_chunks(0, 100, 3 * SR, SR // 2) == [(0, 100)]


def test_seam_crossfade_has_no_jump_or_level_change():
    n = 2 * SR
    x = np.ones(n, np.float32)
    ext = np.ones(n, np.float32)
    out = compose(x, [(SR // 2, SR)], [(SR, 3 * SR // 2)], ext, 320, 80)
    inner = out[SR // 2 + 400:3 * SR // 2 - 400]
    assert np.allclose(inner, 1.0, atol=1e-3)               # no dip at the seam
    ext2 = np.full(n, 0.5, np.float32)
    out = compose(x, [(SR // 2, SR)], [(SR, 3 * SR // 2)], ext2, 320, 80)
    assert np.abs(np.diff(out)).max() < 0.01                 # no click anywhere
    assert out[SR - 400] == pytest.approx(1.0, abs=1e-3) and out[SR + 400] == pytest.approx(0.5, abs=1e-3)
    assert np.all(out[:SR // 2 - 1] == 0) and np.all(out[3 * SR // 2:] == 0) and len(out) == n


def test_hybrid_passthrough_mute_extract_and_length():
    x = scene([("A", 0, 4), ("A", 4, 8), ("B", 4, 8), ("B", 8, 12)], 12)
    ref = scene([("A", 0, 8)], 12)
    regs = [R(0, 4, TARGET), R(4, 8, UNCERTAIN, "overlap"), R(8, 12, OTHER)]
    h = hybrid(ToneExtractor())
    out = h.extract(x, regs)
    assert len(out) == len(x)
    assert si_sdr(out[:8 * SR], ref[:8 * SR]) > 25
    assert np.abs(out[8 * SR + 400:]).max() < 1e-6
    assert np.abs(out[:2 * SR] - x[:2 * SR]).max() < 1e-6 or si_sdr(out[:2 * SR], x[:2 * SR]) > 40
    rep = h.last_report
    assert rep["windows"] == 1 and rep["uncertain_muted_seconds"] == 0 and rep["peak_vram_mib"] is None
    assert rep["pieces"][0]["status"] == "extracted" and rep["seconds_per_window"] is not None


def test_no_overlap_means_extractor_not_called():
    ex = ToneExtractor()
    x = scene([("A", 0, 4), ("B", 4, 8)], 8)
    out = hybrid(ex).extract(x, [R(0, 4, TARGET), R(4, 8, OTHER)])
    assert ex.batches == [] and np.abs(out[4 * SR + 400:]).max() < 1e-6


@pytest.mark.parametrize("kw,reason", [({"wrong": True}, "below_voiceprint_threshold"),
                                       ({"silent": True}, "silent_output")])
def test_uncertain_output_is_muted(kw, reason):
    x = scene([("A", 0, 4), ("B", 0, 4)], 4)
    h = hybrid(ToneExtractor(**kw))
    out = h.extract(x, [R(0, 4, UNCERTAIN, "overlap")])
    assert np.abs(out).max() < 1e-6
    assert h.last_report["pieces"][0]["reason"] == reason and h.last_report["uncertain_muted_seconds"] == 4


def test_too_short_region_is_muted():
    x = scene([("A", 0, 4), ("B", 1, 1.3)], 4)
    h = hybrid(ToneExtractor())
    out = h.extract(x, [R(1, 1.3, UNCERTAIN, "overlap")])
    assert np.abs(out).max() < 1e-6 and h.last_report["pieces"][0]["reason"] == "too_short_to_verify"


@pytest.mark.parametrize("delta", [-100, 250])
def test_length_fitting(delta):
    ex = ToneExtractor(resize=delta)
    w = scene([("A", 0, 4), ("B", 0, 4)], 4)
    out = ex.extract(w, voiceprint_for("A"), enrollment_for("A"))
    assert len(out) == len(w)


def test_batching_and_oom_backoff():
    x = scene([("A", 0, 30), ("B", 0, 30)], 30)
    regs = [R(2 * i * 3.0, 2 * i * 3.0 + 2.0, UNCERTAIN, "overlap") for i in range(5)]
    ex = ToneExtractor(max_ok_batch=2)
    h = hybrid(ex, batch_size=4)
    h.extract(x, regs)
    assert ex.batches[0] == 4 and max(ex.batches[1:]) <= 2 and h.last_report["oom_backoffs"] == 1
    with pytest.raises(BlockedError) as e:
        hybrid(ToneExtractor(oom_always=True)).extract(x, regs)
    assert e.value.kind == "out_of_memory"
