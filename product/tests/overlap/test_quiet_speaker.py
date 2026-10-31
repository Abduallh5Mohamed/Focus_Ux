"""Quiet-speaker repair regressions. MOCKS: tone 'speakers', FakeEmbedder and ToneExtractor stand in for
real voices and for WeSep. They prove the routing, checks and reports, not model quality, GPU speed or
real-world success."""
import numpy as np
import pytest

from fakes import FREQS, SR, FakeEmbedder, scene, tone
from helpers import ToneExtractor, enrollment_for, info, voiceprint_for
from focus_ml.overlap.acceptance import score_case
from focus_ml.overlap.base import BlockedError, OverlapExtractor, resample, rms
from focus_ml.overlap.hybrid import HybridConfig, HybridExtractor
from focus_ml.voice.extractor import GatedBaseline
from focus_ml.voice.match import MatchConfig, classify_regions
from focus_ml.voice.diarizer import from_turns
from focus_ml.voice.routing import (CONTINUITY, RoutedExtractor, RoutingConfig, limit_peak, summarize_routing)
from focus_ml.voice.types import OTHER, TARGET, UNCERTAIN, LabelledRegion, Segment, Voiceprint


def R(a, b, label, reason="x", speaker=None):
    return LabelledRegion(a, b, label, speaker, None, reason)


def routed(ex=None, mode="strict", **hcfg):
    h = HybridExtractor(ex, voiceprint_for("A"), enrollment_for("A"), FakeEmbedder(),
                        HybridConfig(**hcfg)) if ex is not None else None
    return RoutedExtractor(h, RoutingConfig(mode=mode), requested="fake" if ex else None)


def quiet_case(amp_a=0.03, amp_b=0.3, secs=8):
    """Target A (quiet) fully overlapped by B (loud) for the whole clip."""
    a, b = tone(FREQS["A"], secs, amp_a), tone(FREQS["B"], secs, amp_b)
    return a + b, a, b


def score(out, mix, a, b):
    return score_case("t", out, mix, a, [b], 0.0, None)


# ---- controlled mixtures: retention vs leakage ----------------------------------------------------
def test_target_alone_is_kept_and_other_alone_is_muted():
    mix = scene([("A", 0, 4), ("B", 4, 8)], 8)
    regs = [R(0, 4, TARGET), R(4, 8, OTHER)]
    out = routed().extract(mix, regs)
    s = score_case("t", out, mix, scene([("A", 0, 4)], 8), [scene([("B", 4, 8)], 8)], 0, None)
    assert s["target_retention"] > 0.95 and s["leakage"] < 0.01 and s["sync_lag_samples"] == 0


@pytest.mark.parametrize("label,reason", [(OTHER, "voice_match"), (UNCERTAIN, "overlap"), (UNCERTAIN, "voice_match")])
def test_quiet_target_under_louder_speaker_is_recovered_by_extraction(label, reason):
    """The diarization/matching label is wrong or weak (the mixture sounds like B): extraction still runs."""
    mix, a, b = quiet_case()
    r = routed(ToneExtractor())
    out = r.extract(mix, [R(0, 8, label, reason)])
    s = score(out, mix, a, b)
    assert s["target_retention"] > 0.9 and s["leakage"] < 0.02
    assert rms(out) < rms(mix)                    # extracted, not an amplified or passed-through mixture
    rep = summarize_routing(r.last_report)
    assert "genuine_extraction" in rep["route_labels"] and rep["engine_path"] == "extractor"
    assert rep["isolation_claim"] == "strict_isolation" and not rep["target_may_be_lost"]


def test_gated_baseline_alone_loses_the_quiet_target():
    mix, a, b = quiet_case()
    out = GatedBaseline().extract(mix, [R(0, 8, OTHER, "voice_match")])
    assert score(out, mix, a, b)["target_retention"] < 0.01          # the failure this task repairs


def test_a_temporal_mask_or_amplified_mixture_is_not_a_pass():
    mix, a, b = quiet_case()
    assert score(mix * 3, mix, a, b)["leakage"] > 0.5                # the mixture keeps the interferer
    # an extractor that just returns the (amplified) mixture is rejected: wrong voiceprint, clamped level
    class Echo(ToneExtractor):
        def _extract_batch(self, windows, voiceprint, enrollment):
            return [w * 3 for w in windows]
    r = routed(Echo())
    out = r.extract(mix, [R(0, 8, OTHER, "voice_match")])
    assert score(out, mix, a, b)["target_retention"] < 0.05 and np.max(np.abs(out)) < 1e-6


@pytest.mark.parametrize("speakers", [("A", "B"), ("A", "B", "C")])
def test_two_and_three_overlapping_speakers(speakers):
    mix = scene([(s, 0, 8) for s in speakers], 8)
    a = scene([("A", 0, 8)], 8)
    others = [scene([(s, 0, 8)], 8) for s in speakers[1:]]
    out = routed(ToneExtractor()).extract(mix, [R(0, 8, UNCERTAIN, "overlap")])
    s = score_case("t", out, mix, a, others, 0, None)
    assert s["target_retention"] > 0.9 and s["leakage"] < 0.02


def test_missed_overlap_and_short_overlap():
    mix = scene([("A", 0, 8), ("B", 3, 3.25)], 8)           # 0.25 s of overlap that diarization labelled OTHER
    a, b = scene([("A", 0, 8)], 8), scene([("B", 3, 3.25)], 8)
    out = routed(ToneExtractor()).extract(mix, [R(0, 3, TARGET), R(3, 3.25, OTHER), R(3.25, 8, TARGET)])
    assert score(out, mix, a, b)["target_retention"] > 0.85       # target kept around/within the short overlap
    strict = routed(ToneExtractor(), verify_short_by_window=False)
    out2 = strict.extract(mix, [R(0, 3, TARGET), R(3, 3.25, UNCERTAIN, "overlap"), R(3.25, 8, TARGET)])
    pieces = strict.hybrid.last_report["pieces"]
    assert pieces[0]["reason"] == "too_short_to_verify" and score(out2, mix, a, b)["leakage"] < 0.02


def test_wrong_voiceprint_is_rejected_everywhere():
    mix, a, b = quiet_case(0.3, 0.3)
    r = routed(ToneExtractor(wrong=True))                  # the extractor returns the other speaker
    out = r.extract(mix, [R(0, 8, UNCERTAIN, "overlap")])
    assert score(out, mix, a, b)["leakage"] < 0.01 and np.max(np.abs(out)) < 1e-6
    assert r.hybrid.last_report["pieces"][0]["reason"] == "below_voiceprint_threshold"


def test_other_regions_are_not_attempted_when_recovery_is_overlap_only():
    ex = ToneExtractor()
    routed(ex, recovery="overlap").extract(scene([("B", 0, 4)], 4), [R(0, 4, OTHER, "voice_match")])
    assert ex.batches == []


# ---- identity vs extraction quality, 8 kHz output -----------------------------------------------------
class HFEmbedder(FakeEmbedder):
    """Identity also depends on 6 kHz content, which an 8 kHz model cannot output (a MOCK of band loss)."""
    def embed(self, samples):
        spec = np.abs(np.fft.rfft(np.asarray(samples, dtype=np.float64), n=SR))
        v = np.array([spec[217:224].sum(), spec[437:444].sum(), 3.0 * spec[5997:6004].sum()]) + 1e-3
        return v / np.linalg.norm(v)


class LowRateExtractor(ToneExtractor):
    info = info(name="fake8k")

    def _extract_batch(self, windows, voiceprint, enrollment):
        outs = []
        for w in windows:
            spec = np.fft.rfft(w.astype(np.float64)); f = np.fft.rfftfreq(len(w), 1 / SR)
            spec[np.abs(f - 220) > 3] = 0                  # 8 kHz output: only the low tone survives
            outs.append(np.fft.irfft(spec, len(w)).astype(np.float32))
        return outs


def test_8khz_output_is_not_muted_by_the_full_band_voiceprint():
    from focus_ml.overlap.base import CandidateInfo
    low = CandidateInfo(name="fake8k", title="x", mechanism="target_conditioned", code_licence="t",
                        weights_licence="t", model_rate=8000, categories=("overlap_2",))
    LowRateExtractor.info = low
    full = tone(220, 6) + tone(6000, 6, 0.3)               # enrollment: full band
    emb = HFEmbedder()
    vp = Voiceprint(list(emb.embed(full[:SR * 2])), "ecapa", 2.0, {})
    mix = tone(220, 4) + tone(6000, 4, 0.3)
    regs = [R(0, 4, UNCERTAIN, "overlap")]
    ok = HybridExtractor(LowRateExtractor("cpu", False), vp, full, emb, HybridConfig())
    out = ok.extract(mix, regs)
    assert ok.last_report["band_matched_reference"] and ok.last_report["pieces"][0]["status"] == "extracted"
    assert np.max(np.abs(out)) > 0.1
    off = HybridExtractor(LowRateExtractor("cpu", False), vp, full, emb, HybridConfig(band_match_reference=False))
    off.extract(mix, regs)
    assert off.last_report["pieces"][0]["reason"] == "below_voiceprint_threshold"   # the old behaviour
    wrong = scene([("B", 0, 4)], 4)                          # a wrong speaker is still rejected at 8 kHz
    w = HybridExtractor(LowRateExtractor("cpu", False), vp, full, emb, HybridConfig())
    assert np.max(np.abs(w.extract(wrong, regs))) < 1e-6


def test_piece_reports_identity_separately_from_quality():
    mix, a, b = quiet_case()
    r = routed(ToneExtractor())
    r.extract(mix, [R(0, 8, OTHER, "voice_match")])
    p = r.hybrid.last_report["pieces"][0]
    assert p["identity_score"] == p["score"] and {"rms_db", "mixture_rms_db", "silent", "negligible"} <= set(p["quality"])


# ---- fallbacks and failures are labelled --------------------------------------------------------------
def test_strict_reports_possible_loss_and_continuity_is_not_isolation():
    mix = scene([("A", 0, 4), ("B", 4, 8)], 8)
    regs = [R(0, 4, TARGET), R(4, 8, UNCERTAIN, "voice_match")]
    s = routed(); out = s.extract(mix, regs)
    rs = summarize_routing(s.last_report)
    assert rs["target_may_be_lost"] and "strict_muting" in rs["route_labels"] and rs["mode"] == "strict"
    assert np.max(np.abs(out[5 * SR:7 * SR])) < 1e-6 and any("may be partly missing" in n for n in rs["notices"])
    c = routed(mode=CONTINUITY); out = c.extract(mix, regs)
    rc = summarize_routing(c.last_report)
    assert rc["isolation_claim"] == "not_isolation" and "continuity_fallback" in rc["route_labels"]
    assert "genuine_extraction" not in rc["route_labels"] and not rc["target_may_be_lost"]
    assert 0 < np.max(np.abs(out[5 * SR:7 * SR])) < np.max(np.abs(mix[5 * SR:7 * SR]))


@pytest.mark.parametrize("make", [
    lambda: BlockedError("weights missing", "missing_weights", "no checkpoint"),
    lambda: RuntimeError("boom"),
])
def test_missing_or_failed_extractor_is_an_explicit_warning_even_without_overlap(make):
    class Broken(ToneExtractor):
        def check_ready(self):
            raise make()
    r = routed(Broken())
    out = r.extract(scene([("A", 0, 4)], 4), [R(0, 4, TARGET)])          # no window would run
    rs = summarize_routing(r.last_report)
    assert rs["overlap_extraction"] == "failed" and "extraction_failed" in rs["route_labels"]
    assert "genuine_extraction" not in rs["route_labels"] and any("FAILED" in n for n in rs["notices"])
    assert len(out) == 4 * SR


def test_failure_while_running_is_reported_not_raised():
    class Crash(ToneExtractor):
        def _extract_batch(self, *a):
            raise ValueError("bad tensor")
    r = routed(Crash())
    r.extract(quiet_case()[0], [R(0, 8, UNCERTAIN, "overlap")])
    assert r.last_report["overlap_extraction"] == "failed"
    assert r.last_report["overlap_error"]["kind"] == "extractor_error"


def test_skipped_extraction_is_labelled():
    r = RoutedExtractor(None, RoutingConfig(), skip_reason="no clean enrollment audio", requested="fake")
    r.extract(scene([("A", 0, 4)], 4), [R(0, 4, TARGET)])
    rs = summarize_routing(r.last_report)
    assert rs["overlap_extraction"] == "skipped" and "extraction_skipped" in rs["route_labels"]
    assert any("SKIPPED" in n for n in rs["notices"])


# ---- audio quality ---------------------------------------------------------------------------------------
def test_no_clipping_and_no_amplification():
    loud = scene([("A", 0, 4), ("B", 0, 4)], 4, amp=0.9)
    r = routed(mode=CONTINUITY)
    out = r.extract(loud, [R(0, 4, UNCERTAIN, "voice_match")])
    assert np.max(np.abs(out)) <= 0.98 + 1e-6
    big = np.array([0.0, 1.5, -2.0], np.float32)
    lim = limit_peak(big, 0.98)
    assert np.max(np.abs(lim)) == pytest.approx(0.98) and np.array_equal(limit_peak(big * 0.1, 0.98), big * 0.1)


def test_extracted_audio_never_louder_than_the_mixture():
    class Loud(ToneExtractor):
        def _extract_batch(self, windows, voiceprint, enrollment):
            return [o * 6 for o in super()._extract_batch(windows, voiceprint, enrollment)]
    mix = scene([("A", 0, 4)], 4, amp=0.1)
    h = HybridExtractor(Loud(), voiceprint_for("A"), enrollment_for("A"), FakeEmbedder())
    out = h.extract(mix, [R(0, 4, UNCERTAIN, "overlap")])
    assert rms(out[SR // 2:-SR // 2]) <= rms(mix) * 10 ** (1.0 / 20) * 1.02
    assert h.last_report["pieces"][0]["quality"].get("gain_clamped_db", 0) > 0


@pytest.mark.parametrize("rate", [8000, 16000, 48000])
def test_resample_keeps_length_and_level(rate):
    x = tone(300, 2)
    y = resample(x, SR, rate)
    assert len(y) == 2 * rate and rms(y) == pytest.approx(rms(x), rel=0.05)
    back = resample(y, rate, SR)
    assert len(back) == len(x)


def test_polarity_gain_length_and_alignment_of_model_output():
    from focus_ml.overlap.candidates import match_to_mixture
    ref = tone(300, 2)
    for scale in (-1.0, 0.01, -40.0):
        fixed = match_to_mixture(ref * scale, ref)
        assert float(np.dot(fixed, ref)) > 0 and rms(fixed) == pytest.approx(rms(ref), rel=0.1)
    out = routed(ToneExtractor(resize=-7)).extract(quiet_case()[0], [R(0, 8, UNCERTAIN, "overlap")])
    assert len(out) == 8 * SR                                 # model output length error is repaired


def test_seams_are_crossfaded_without_clicks():
    mix = scene([("A", 0, 8)], 8)
    out = routed(ToneExtractor()).extract(mix, [R(0, 3, TARGET), R(3, 6, UNCERTAIN, "overlap"), R(6, 8, TARGET)])
    assert np.max(np.abs(np.diff(out))) < 0.06                # a 220 Hz tone at 0.3 steps ~0.026 per sample


# ---- short fragmented turns ---------------------------------------------------------------------------------
def test_short_turn_next_to_target_joins_the_target_but_wrong_speaker_does_not():
    diar = from_turns([Segment(0, 4, "S0"), Segment(4.05, 4.25, "S0"), Segment(4.3, 4.5, "S1")])
    x = scene([("A", 0, 4), ("A", 4.05, 4.25), ("B", 4.3, 4.5)], 5)
    regs = classify_regions(x, diar, voiceprint_for("A"), FakeEmbedder())
    short = {round(r.start, 2): r for r in regs if r.reason != "voice_match"}
    assert short[4.05].label == TARGET and short[4.05].reason == "short_turn_joined_to_target"
    assert short[4.3].label == UNCERTAIN


def test_missing_enrollment_recording_is_a_clear_error_and_missing_reference_skips_visibly(tmp_path):
    from focus_ml.voice.engine import AudioOnlyEngine
    from focus_ml.voice.errors import EnrollmentError
    e = AudioOnlyEngine(None, FakeEmbedder(), overlap_extractor=ToneExtractor())
    with pytest.raises(EnrollmentError, match="missing"):
        e._enrollment_audio(scene([("A", 0, 4)], 4), voiceprint_for("A"), str(tmp_path / "gone.wav"))
    vp = Voiceprint([1.0, 0, 0, 0], "ecapa", 5.0, {"kind": "voice_file"})
    routed_ = e._routed(scene([("A", 0, 4)], 4), vp, None)
    assert routed_.hybrid is None and routed_.skip_reason
