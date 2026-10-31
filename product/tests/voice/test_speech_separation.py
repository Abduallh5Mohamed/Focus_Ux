"""The opt-in speech-separation extractor, exercised with a fake separator.

Context: on a real job the "background" was another human voice (Demucs put
99.4 % of the mix in its vocals stem), so the fix has to be a speech separator.
Measured on that file with the real MossFormer2_SS_16K: the two stems are
complementary (corr(sum, mix) = 0.9716) and nearly uncorrelated with each other
(0.0493), and the chosen stem sits 18.7 dB below the mix outside the target
regions.

These tests pin the selection rule, the blend and the failure behaviour. The
real model is verified on a machine with the ClearerVoice environment via
``product/tools/clearervoice_setup.py``.
"""
import numpy as np
import pytest

from focus_ml.errors import ModelUnavailableError
from focus_ml.voice.extractor import build_extractor
from focus_ml.voice.separation import ClearerVoiceSeparator, SpeechSeparationBaseline
from focus_ml.voice.types import OTHER, SAMPLE_RATE, TARGET, LabelledRegion

SR = SAMPLE_RATE
FLOOR = 10 ** (-12 / 20)


class FakeSeparator:
    name = "fake_ss"
    model = "fake-model"

    def __init__(self, stems):
        self.stems = [np.asarray(s, dtype=np.float32) for s in stems]

    def separate(self, samples, rate=SR):
        return [s[: len(samples)] for s in self.stems]


class BrokenSeparator:
    name = "broken"
    model = "broken-model"

    def separate(self, samples, rate=SR):
        raise ModelUnavailableError("weights missing", retryable=False, detail="test")


def _scene(seconds=4.0):
    """speaker A talks 1-2 s, speaker B talks 2-3 s, nothing outside."""
    t = np.arange(int(seconds * SR)) / SR
    a = np.zeros_like(t)
    b = np.zeros_like(t)
    a[(t >= 1.0) & (t < 2.0)] = 0.4 * np.sin(2 * np.pi * 220 * t[(t >= 1.0) & (t < 2.0)])
    b[(t >= 2.0) & (t < 3.0)] = 0.4 * np.sin(2 * np.pi * 330 * t[(t >= 2.0) & (t < 3.0)])
    return (a + b).astype(np.float32), a.astype(np.float32), b.astype(np.float32)


def test_the_enrolled_speaker_is_picked_by_target_contrast():
    mix, a, b = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, ""),
               LabelledRegion(2.0, 3.0, OTHER, "B", .1, "")]
    # B is listed first on purpose: the picker must not rely on ordering.
    out = SpeechSeparationBaseline(separator=FakeSeparator([b, a])).extract(mix, regions)

    assert np.corrcoef(out[SR + 3000:2 * SR - 3000], a[SR + 3000:2 * SR - 3000])[0, 1] > 0.99
    # Target-only output must not deliberately reintroduce the other speaker.
    other = slice(2 * SR + 3000, 3 * SR - 3000)
    assert np.max(np.abs(out[other])) == 0


def test_full_overlap_without_timing_evidence_refuses_arbitrary_first_source():
    from focus_ml.errors import ProcessingError
    mix, a, b = _scene()
    regions = [LabelledRegion(0, 4, TARGET, "A", .9, "")]
    with pytest.raises(ProcessingError, match="confidently"):
        SpeechSeparationBaseline(separator=FakeSeparator([a, b])).extract(mix, regions)


def test_target_contrast_separates_the_two_speakers():
    _, a, b = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, "")]
    assert SpeechSeparationBaseline.target_contrast(a, regions) > 10.0
    assert SpeechSeparationBaseline.target_contrast(b, regions) < -10.0


def test_a_broken_separator_never_falls_back_to_the_mask():
    mix, _, _ = _scene()
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", .9, "")]
    with pytest.raises(ModelUnavailableError):
        SpeechSeparationBaseline(separator=BrokenSeparator()).extract(mix, regions)


def test_missing_environment_is_reported_before_any_work():
    with pytest.raises(ModelUnavailableError, match="not installed"):
        ClearerVoiceSeparator(python=None).check_ready()
    with pytest.raises(ModelUnavailableError, match="not installed"):
        ClearerVoiceSeparator(python="C:/definitely/not/here/python.exe").check_ready()


def test_missing_checkpoint_is_reported(tmp_path):
    fake_python = tmp_path / "python.exe"
    fake_python.write_bytes(b"")
    separator = ClearerVoiceSeparator(python=str(fake_python), home=str(tmp_path / "cv"))
    with pytest.raises(ModelUnavailableError, match="weights"):
        separator.check_ready()


def test_build_extractor_wires_the_separation_choice():
    extractor = build_extractor(env={"FOCUS_VOICE_EXTRACTOR": "separation"})
    assert isinstance(extractor, SpeechSeparationBaseline)
    params = extractor.params()
    assert params["separator"] == "clearervoice_ss" and params["model"] == "MossFormer2_SS_16K"
