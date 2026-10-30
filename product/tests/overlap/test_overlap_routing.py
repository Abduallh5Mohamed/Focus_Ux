"""Production routing: disabled by default, strict vs continuity, fallback labelling, preflight, metrics.
Tone fakes only: this is not model or GPU evidence."""
import numpy as np
import pytest

from fakes import SR, FakeDiarizer, FakeEmbedder, scene
from helpers import ToneExtractor, enrollment_for, voiceprint_for
from focus_ml.isolation_engines import write_wav
from focus_ml.overlap.acceptance import build_case, score_case
from focus_ml.overlap.base import BlockedError
from focus_ml.overlap.hybrid import HybridExtractor
from focus_ml.overlap.preflight import run_preflight
from focus_ml.voice.engine import AudioOnlyEngine
from focus_ml.voice.extractor import GatedBaseline
from focus_ml.voice.preprocess import load_canonical
from focus_ml.voice.routing import (CONTINUITY, CONTINUITY_NOTICE, RoutedExtractor, RoutingConfig,
                                    routing_from_env)
from focus_ml.voice.types import OTHER, TARGET, UNCERTAIN, LabelledRegion


def R(a, b, label, reason="x"):
    return LabelledRegion(a, b, label, None, None, reason)


def hyb(ex):
    return HybridExtractor(ex, voiceprint_for("A"), enrollment_for("A"), FakeEmbedder())


X = scene([("A", 0, 4), ("A", 4, 8), ("B", 4, 8), ("B", 8, 12)], 12)
REGS = [R(0, 4, TARGET), R(4, 8, UNCERTAIN, "overlap"), R(8, 12, OTHER)]


def test_disabled_by_default_equals_gated_baseline():
    r = RoutedExtractor()
    out = r.extract(X, REGS)
    assert np.array_equal(out, GatedBaseline().extract(X, REGS))
    rep = r.last_report
    assert rep["overlap_extraction"] == "disabled" and rep["fallback_used"] is False
    assert rep["isolation_claim"] == "strict_isolation"
    cfg, name = routing_from_env({})
    assert cfg.mode == "strict" and name is None
    assert routing_from_env({"FOCUS_ISOLATION_MODE": "continuity", "FOCUS_OVERLAP_EXTRACTOR": "wesep_bsrnn"})[1] == "wesep_bsrnn"
    with pytest.raises(ValueError):
        RoutingConfig(mode="loose")
    with pytest.raises(ValueError):
        RoutingConfig(continuity_gain_db=3)


def test_strict_routes_overlap_to_extractor_and_mutes_other_only():
    ex = ToneExtractor()
    r = RoutedExtractor(hyb(ex))
    out = r.extract(X, REGS)
    assert len(out) == len(X) and ex.batches == [1]            # one inference, one window
    assert np.abs(out[5 * SR:7 * SR]).max() > 0.1             # overlap was extracted, not muted
    assert np.abs(out[8 * SR + 400:]).max() < 1e-6            # other-only suppressed
    assert r.last_report["overlap_extraction"] == "ran" and r.last_report["fallback_used"] is False


def test_unverified_extraction_stays_muted_in_strict():
    out = RoutedExtractor(hyb(ToneExtractor(wrong=True))).extract(X, REGS)
    assert np.abs(out[4 * SR + 400:]).max() < 1e-6


def test_continuity_plays_reduced_mix_smoothly_and_flags_fallback():
    cfg = RoutingConfig(mode=CONTINUITY, continuity_gain_db=-18)
    r = RoutedExtractor(None, cfg)
    out = r.extract(X, REGS)
    assert len(out) == len(X)
    rep = r.last_report
    assert rep["fallback_used"] and rep["isolation_claim"] == "not_isolation" and CONTINUITY_NOTICE in rep["notices"]
    assert "not speaker isolation" in CONTINUITY_NOTICE
    seg = out[9 * SR:11 * SR]
    ratio = np.abs(seg).max() / np.abs(X[9 * SR:11 * SR]).max()
    assert ratio == pytest.approx(10 ** (-18 / 20), rel=0.02) and np.abs(seg).max() > 0     # reduced, not silent
    assert np.abs(np.diff(out)).max() < 0.05                                              # no clicks
    assert np.abs(out[:3 * SR] - X[:3 * SR]).max() < 1e-3                                  # target untouched
    assert rep["fallback_seconds"] == pytest.approx(8.0, abs=0.2)


def test_continuity_never_clips_and_reports_no_fallback_when_everything_kept():
    loud = np.clip(scene([("A", 0, 4), ("B", 0, 4)], 4, amp=0.9), -1, 1)
    r = RoutedExtractor(None, RoutingConfig(mode=CONTINUITY, continuity_gain_db=-1, ceiling=0.95))
    out = r.extract(loud, [R(0, 4, UNCERTAIN, "overlap")])
    assert np.abs(out).max() <= 0.95 + 1e-6
    r2 = RoutedExtractor(None, RoutingConfig(mode=CONTINUITY))
    r2.extract(loud, [R(0, 4, TARGET)])
    assert r2.last_report["fallback_used"] is False and r2.last_report["isolation_claim"] == "strict_isolation"


def test_continuity_with_extractor_only_falls_back_where_unverified():
    r = RoutedExtractor(hyb(ToneExtractor(silent=True)), RoutingConfig(mode=CONTINUITY))
    out = r.extract(X, REGS)
    assert r.last_report["fallback_used"] and np.abs(out[5 * SR:7 * SR]).max() > 0
    r_ok = RoutedExtractor(hyb(ToneExtractor()), RoutingConfig(mode=CONTINUITY))
    r_ok.extract(X[:8 * SR], [R(0, 4, TARGET), R(4, 8, UNCERTAIN, "overlap")])
    assert r_ok.last_report["fallback_used"] is False


def test_blocked_extractor_is_reported_and_falls_back_to_strict():
    class Blocked(ToneExtractor):
        def check_ready(self):
            raise BlockedError("no weights", "missing_weights", "x")
    r = RoutedExtractor(hyb(Blocked()))
    out = r.extract(X, REGS)
    assert np.abs(out[5 * SR:7 * SR]).max() < 1e-6
    assert r.last_report["overlap_extraction"] == "failed" and r.last_report["overlap_error"]["kind"] == "missing_weights"


# ---- engine integration
TURNS = [("A", 0.0, 6.0), ("B", 6.0, 12.0), ("A", 12.0, 16.0), ("A", 16.0, 18.0), ("B", 16.0, 18.0)]


def run_engine(tmp_path, **kw):
    path = tmp_path / "s.wav"
    write_wav(str(path), scene(TURNS, 18.0), 16000)
    e = AudioOnlyEngine(FakeDiarizer(TURNS), FakeEmbedder(), **kw)
    a = e.analyze(str(path))
    vp = next(s for s in a["speakers"] if s["speaker"] == "A")["voiceprint"]
    return e.isolate(str(path), vp, a["diarization"], str(tmp_path)), load_canonical(str(path))


def test_engine_default_is_strict_gate_without_extractor(tmp_path):
    res, src = run_engine(tmp_path)
    out = load_canonical(res.wav_path)
    assert np.abs(out[16 * SR:18 * SR]).max() < 1e-3
    assert res.details["routing"]["overlap_extraction"] == "disabled" and not res.details["routing"]["fallback_used"]


def test_engine_with_overlap_extractor_uses_enrollment_audio_and_loads_once(tmp_path):
    ex = ToneExtractor()
    res, src = run_engine(tmp_path, overlap_extractor=ex)
    out = load_canonical(res.wav_path)
    assert len(out) == len(src) and np.abs(out[16 * SR + 800:18 * SR - 800]).max() > 0.1
    assert res.details["routing"]["overlap_extraction"] == "ran"
    assert ex.batches == [1]                                  # inference ran once for the one window


def test_engine_continuity_reports_fallback_in_result_and_warnings(tmp_path):
    res, _ = run_engine(tmp_path, routing=RoutingConfig(mode=CONTINUITY))
    assert res.details["routing"]["fallback_used"] and CONTINUITY_NOTICE in res.warnings
    out = load_canonical(res.wav_path)
    assert np.abs(out[7 * SR:11 * SR]).max() > 0


def test_voice_file_enrollment_without_audio_skips_extraction_visibly(tmp_path):
    e = AudioOnlyEngine(FakeDiarizer(TURNS), FakeEmbedder(), overlap_extractor=ToneExtractor())
    from focus_ml.voice.types import Voiceprint
    vp = Voiceprint([1.0, 0, 0, 0], "ecapa", 5.0, {"kind": "voice_file"})
    routed = e._routed(scene(TURNS, 18.0), vp, None)
    assert routed.hybrid is None and "enrollment" in routed.skip_reason


# ---- preflight and metrics
def test_preflight_reports_each_failure_and_passes_when_all_ok():
    bad = run_preflight("wesep_bsrnn", probes={"torch": None}, ready=lambda: None, has_module=lambda m: False)
    assert not bad["ok"] and {c["name"] for c in bad["checks"] if c["status"] == "fail"} >= {"pytorch", "gpu_model", "dependencies"}
    good = run_preflight("wesep_bsrnn", probes={
        "torch": {"version": "2.4", "cuda_build": "12.1", "cuda_available": True},
        "gpu": {"name": "RTX 3050", "capability": [8, 6], "total_mib": 4096, "free_mib": 3500}},
        ready=lambda: None, has_module=lambda m: True)
    assert good["ok"]
    low = run_preflight("wesep_bsrnn", probes={
        "torch": {"version": "2.4", "cuda_build": "12.1", "cuda_available": True},
        "gpu": {"name": "RTX 3050", "capability": [8, 6], "total_mib": 4096, "free_mib": 900}},
        ready=lambda: None, has_module=lambda m: True)
    assert not low["ok"] and any(c["name"] == "free_vram" and c["status"] == "fail" for c in low["checks"])


def test_acceptance_metrics_distinguish_good_and_wrong_output():
    t, o = scene([("A", 0, 8)], 8), scene([("B", 0, 8)], 8)
    mix, tr, orf, regs = build_case("C", t, [o])
    good = score_case("C", t, mix, tr, orf, 1.0, None)
    assert good["target_retention"] == pytest.approx(1, abs=0.01) and good["leakage"] < 0.01 and good["si_sdri_db"] > 20
    assert good["sync_lag_samples"] == 0 and good["length_equal"]
    wrong = score_case("C", o, mix, tr, orf, 1.0, None)
    assert wrong["leakage"] > 0.9 and wrong["target_retention"] < 0.05
    silent = score_case("C", np.zeros_like(mix), mix, tr, orf, 1.0, None)
    assert silent["silent_pct"] == 100.0
    shifted = score_case("C", np.roll(t, 160), mix, tr, orf, 1.0, None)
    assert shifted["sync_lag_samples"] == 160
    b = build_case("B", t, [o])
    assert b[1] is None and score_case("B", o, b[0], None, b[2], 1, None)["target_retention"] is None
    with pytest.raises(ValueError):
        build_case("D", t, [o])
