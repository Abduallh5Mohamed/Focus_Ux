"""The opt-in Demucs pre-cleaner, exercised with a fake separator.

No torch and no weights here: these tests pin the blend maths, the failure
behaviour (never a silent fallback) and the wiring. The real separator is
verified on a machine with the Demucs environment via
``product/tools/demucs_setup.py``.
"""
import numpy as np
import pytest

from focus_ml.errors import ModelUnavailableError
from focus_ml.voice.extractor import build_extractor
from focus_ml.voice.music import DemucsSeparator, MusicSuppressedBaseline
from focus_ml.voice.types import OTHER, SAMPLE_RATE, TARGET, LabelledRegion

SR = SAMPLE_RATE
FLOOR = 10 ** (-12 / 20)


class FakeSeparator:
    """Returns a known 'vocals' track: the bed is dropped exactly."""
    name = "fake"
    model = "fake-model"

    def __init__(self, voice):
        self.voice = np.asarray(voice, dtype=np.float32)

    def separate(self, samples, rate=SR):
        return self.voice


class BrokenSeparator:
    name = "broken"
    model = "broken-model"

    def separate(self, samples, rate=SR):
        raise ModelUnavailableError("weights missing", retryable=False, detail="test")


def _scene(seconds=4.0):
    t = np.arange(int(seconds * SR)) / SR
    voice = np.zeros_like(t, dtype=np.float32)
    inside = (t >= 1.0) & (t < 2.0)
    voice[inside] = 0.4 * np.sin(2 * np.pi * 220 * t[inside])
    bed = 0.3 * np.sin(2 * np.pi * 90 * t)
    return (voice + bed).astype(np.float32), voice.astype(np.float32), bed.astype(np.float32)


def test_bed_is_gone_inside_speech_and_ducked_outside():
    mix, voice, bed = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, ""),
               LabelledRegion(2.0, 3.0, OTHER, "B", .1, "")]
    out = MusicSuppressedBaseline(separator=FakeSeparator(voice)).extract(mix, regions)

    assert len(out) == len(mix)
    # inside the target: the separator's vocals only, so no bed remains
    assert np.corrcoef(out[SR + 3000:2 * SR - 3000], voice[SR + 3000:2 * SR - 3000])[0, 1] > 0.99
    # outside: the accompaniment (mix - vocals), ducked
    gap = slice(2 * SR + 3000, 3 * SR - 3000)
    assert np.corrcoef(out[gap], bed[gap])[0, 1] > 0.99
    assert 20 * np.log10(np.max(np.abs(out[gap])) / np.max(np.abs(bed[gap]))) == pytest.approx(-12.0, abs=0.2)


def test_a_broken_separator_never_falls_back_to_the_mask():
    mix, voice, _ = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, "")]
    with pytest.raises(ModelUnavailableError):
        MusicSuppressedBaseline(separator=BrokenSeparator()).extract(mix, regions)


def test_missing_separator_python_is_reported_before_any_work():
    with pytest.raises(ModelUnavailableError, match="not installed"):
        DemucsSeparator(python=None).check_ready()
    with pytest.raises(ModelUnavailableError, match="not installed"):
        DemucsSeparator(python="C:/definitely/not/here/python.exe").check_ready()


def test_build_extractor_wires_the_music_choice():
    extractor = build_extractor(env={"FOCUS_VOICE_EXTRACTOR": "music"})
    assert isinstance(extractor, MusicSuppressedBaseline)
    params = extractor.params()
    assert params["separator"] == "demucs" and params["floor_db"] == -12.0


def test_music_extractor_keeps_the_target_level():
    mix, voice, _ = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, "")]
    out = MusicSuppressedBaseline(separator=FakeSeparator(voice)).extract(mix, regions)
    steady = slice(SR + 3000, 2 * SR - 3000)
    assert np.sqrt(np.mean(out[steady] ** 2)) == pytest.approx(np.sqrt(np.mean(voice[steady] ** 2)), rel=0.02)
