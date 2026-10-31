"""The ducked mask baseline: what replaced the hard 1/0 gate.

Context: a delivered job was 41.7 % exact digital silence (18 gaps, longest
8.0 s) cut out of a continuous background bed, because ``GatedBaseline``
writes zeros outside the target's speech. ``DuckedBaseline`` keeps the target
at unity and attenuates everything else to a floor instead of switching it
off. These tests pin that behaviour down; they do not claim any separation of
overlapping sources.
"""
import numpy as np
import pytest

from focus_ml.voice.extractor import (
    DEFAULT_FLOOR_DB, DuckedBaseline, GatedBaseline, build_extractor, target_mask,
)
from focus_ml.voice.types import OTHER, SAMPLE_RATE, TARGET, UNCERTAIN, LabelledRegion

SR = SAMPLE_RATE
FLOOR = 10 ** (DEFAULT_FLOOR_DB / 20)


def _regions():
    return [
        LabelledRegion(1.0, 2.0, TARGET, "A", .9, "voice_match"),
        LabelledRegion(2.0, 3.0, OTHER, "B", .1, "voice_match"),
        LabelledRegion(3.0, 3.5, UNCERTAIN, "B", .4, "overlap"),
    ]


def test_ducked_baseline_ducks_the_background_instead_of_muting_it():
    x = np.full(SR * 4, 0.5, dtype=np.float32)
    out = DuckedBaseline().extract(x, _regions())

    assert len(out) == len(x)
    # the target keeps its own level
    assert out[SR + 8000] == pytest.approx(0.5, abs=1e-4)
    # everything outside the target is attenuated by 12 dB, not deleted
    assert out[0] == pytest.approx(0.5 * FLOOR, rel=1e-3)
    assert out[2 * SR + 8000] == pytest.approx(0.5 * FLOOR, rel=1e-3)
    assert not np.any(out == 0.0), "a ducked baseline must never write digital silence"
    assert 20 * np.log10(abs(out[0]) / 0.5) == pytest.approx(DEFAULT_FLOOR_DB, abs=0.1)


def test_ducked_fade_runs_30ms_inside_the_region_edge():
    x = np.ones(SR * 4, dtype=np.float32)
    out = DuckedBaseline(fade_ms=30.0).extract(x, _regions())

    assert out[SR] == pytest.approx(FLOOR, abs=2e-3)                       # ramp start
    assert out[SR + int(0.015 * SR)] == pytest.approx((FLOOR + 1) / 2, abs=0.02)  # midpoint
    assert out[SR + int(0.030 * SR)] == pytest.approx(1.0, abs=2e-3)       # steady state
    assert np.max(np.abs(np.diff(out))) < 0.01                             # no step at the edge


def test_ducked_fade_is_smoother_than_the_old_gate():
    x = np.ones(SR * 4, dtype=np.float32)
    ducked = np.max(np.abs(np.diff(DuckedBaseline(fade_ms=30.0).extract(x, _regions()))))
    gated = np.max(np.abs(np.diff(GatedBaseline(fade_ms=10.0).extract(x, _regions()))))
    assert ducked < gated / 2


def test_short_pauses_are_bridged_so_the_bed_does_not_pump():
    x = np.ones(SR * 4, dtype=np.float32)
    # two target spans 100 ms apart: one speaker's own pause
    regions = [LabelledRegion(1.0, 1.5, TARGET, "A", .9, ""),
               LabelledRegion(1.6, 2.0, TARGET, "A", .9, "")]
    bridged = DuckedBaseline(bridge_ms=250.0).extract(x, regions)
    assert bridged[int(1.55 * SR)] == pytest.approx(1.0, abs=0.02)

    unbridged = DuckedBaseline(bridge_ms=0.0).extract(x, regions)
    assert unbridged[int(1.55 * SR)] == pytest.approx(FLOOR, abs=0.02)


def test_bridge_does_not_swallow_a_long_gap():
    x = np.ones(SR * 6, dtype=np.float32)
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, ""),
               LabelledRegion(3.0, 4.0, TARGET, "A", .9, "")]
    out = DuckedBaseline(bridge_ms=250.0).extract(x, regions)
    assert out[int(2.5 * SR)] == pytest.approx(FLOOR, abs=0.02)   # 1 s gap stays ducked


def test_floor_and_fade_are_validated():
    with pytest.raises(ValueError):
        DuckedBaseline(floor_db=3.0)
    with pytest.raises(ValueError):
        DuckedBaseline(fade_ms=0.0)
    with pytest.raises(ValueError):
        DuckedBaseline(bridge_ms=-1.0)
    with pytest.raises(ValueError):
        target_mask(10, [], floor=1.5)


def test_target_mask_still_defaults_to_the_hard_gate():
    m = target_mask(SR * 2, [LabelledRegion(0.5, 1.5, TARGET, "A", .9, "")])
    assert m[0] == 0.0 and m[SR] == 1.0


def test_build_extractor_defaults_to_ducked_and_reads_the_environment():
    assert isinstance(build_extractor(env={}), DuckedBaseline)
    assert isinstance(build_extractor(env={"FOCUS_VOICE_EXTRACTOR": "gated"}), GatedBaseline)

    tuned = build_extractor(env={"FOCUS_VOICE_FLOOR_DB": "-18", "FOCUS_VOICE_FADE_MS": "20",
                                 "FOCUS_VOICE_BRIDGE_MS": "150"})
    assert isinstance(tuned, DuckedBaseline)
    assert (tuned.floor_db, tuned.fade_ms, tuned.bridge_ms) == (-18.0, 20.0, 150.0)
    assert tuned.floor == pytest.approx(10 ** (-18 / 20))

    with pytest.raises(ValueError, match="unknown extractor"):
        build_extractor(env={"FOCUS_VOICE_EXTRACTOR": "magic"})


def test_audio_only_engine_accepts_the_ducked_extractor_explicitly():
    from focus_ml.voice.engine import AudioOnlyEngine
    from fakes import FakeDiarizer, FakeEmbedder

    engine = AudioOnlyEngine(FakeDiarizer([]), FakeEmbedder(), extractor=build_extractor(env={}))
    assert engine.extractor.name == "ducked_baseline"
    assert engine.extractor.params() == {"floor_db": DEFAULT_FLOOR_DB, "fade_ms": 30.0,
                                         "bridge_ms": 250.0}


def test_explicit_extractor_still_wins():
    from focus_ml.voice.engine import AudioOnlyEngine
    from fakes import FakeDiarizer, FakeEmbedder

    engine = AudioOnlyEngine(FakeDiarizer([]), FakeEmbedder(), extractor=GatedBaseline())
    assert engine.extractor.name == "gated_baseline"
