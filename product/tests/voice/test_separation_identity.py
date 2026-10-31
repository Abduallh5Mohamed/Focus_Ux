"""Enrollment-embedding source selection for the speech-separation extractor.

These tests pin the SEMANTICS of the extraction hook with deterministic fakes:
a fake separator that returns fixed stems and a fake embedder that maps a
window to the one-hot vector of its dominant frequency bin. Nothing here is
evidence about the real MossFormer2_SS_16K / ECAPA quality; that still needs
the real weights and evaluation on real recordings. The tests only prove which
stem is selected or refused under which voiceprint evidence.
"""
import wave
import numpy as np
import pytest

from focus_ml.errors import ProcessingError
from focus_ml.voice.engine import AudioOnlyEngine
from focus_ml.voice.extractor import DuckedBaseline
from focus_ml.voice.match import MatchConfig
from focus_ml.voice.separation import SpeechSeparationBaseline
from focus_ml.voice.types import (
    Segment, Diarization, SAMPLE_RATE, TARGET, UNCERTAIN, LabelledRegion, Voiceprint)

SR = SAMPLE_RATE
MATCH = MatchConfig(target_threshold=0.6, other_threshold=0.3)


class FakeEmbedder:
    """Deterministic test double: one-hot vector of the dominant FFT bin.

    Two different tones give orthogonal vectors; the same tone in any window
    repeats the same vector, so enrollment vs. stem similarity is 1.0 for the
    enrolled tone and 0.0 for the other. NOT a real embedding model.
    """
    name = "fake-signal"

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.loads = 0
        self.unloads = 0
        self.embeds_after_unload = 0

    def load(self) -> None:
        self.loads += 1

    def unload(self) -> None:
        self.unloads += 1

    def embed(self, samples) -> np.ndarray:
        if self.unloads > 0:
            self.embeds_after_unload += 1
        x = np.asarray(samples, dtype=np.float64).reshape(-1)
        spec = np.abs(np.fft.rfft(x * np.hanning(x.size)))
        n = int(x.size)
        freqs = np.fft.rfftfreq(n, 1.0 / SR)
        bins = np.array([spec[(freqs >= k * 125.0) & (freqs < (k + 1) * 125.0)].sum()
                         for k in range(self.dim)])
        v = np.zeros(self.dim)
        if bins.sum() <= 0:
            raise ValueError("test embedder got a silent or non-finite window")
        v[int(np.argmax(bins))] = 1.0
        return v


class FixedEmbedder(FakeEmbedder):
    """Returns one fixed vector whatever it hears (identity-blind fake)."""

    def __init__(self, vector):
        super().__init__()
        self._vector = np.asarray(vector, dtype=np.float64)

    def embed(self, samples) -> np.ndarray:
        if self.unloads > 0:
            self.embeds_after_unload += 1
        return self._vector / np.linalg.norm(self._vector)


class FakeSeparator:
    name = "fake_ss"
    model = "fake-model"

    def __init__(self, stems):
        self.stems = [np.asarray(s, dtype=np.float32) for s in stems]

    def separate(self, samples, rate=SR):
        if any(len(s) != len(samples) for s in self.stems):
            raise AssertionError("fake separator stem length mismatch")
        return [np.asarray(s, dtype=np.float32) for s in self.stems]


class ShortSeparator:
    """Deliberately wrong stem length, to exercise the defensive check."""
    name = "short_ss"
    model = "fake-model"

    def __init__(self, stems):
        self.stems = [np.asarray(s, dtype=np.float32) for s in stems]

    def separate(self, samples, rate=SR):
        return [s[: len(samples) // 2] for s in self.stems]


def tone(t0, t1, freq, amp=0.4, length=4.0):
    t = np.arange(int(length * SR)) / SR
    out = np.zeros_like(t)
    out[(t >= t0) & (t < t1)] = amp * np.sin(2 * np.pi * freq * t[(t >= t0) & (t < t1)])
    return out.astype(np.float32)


def sequential_scene():
    """A talks 1-2 s (target), B talks 2-3 s, nothing outside."""
    return tone(1.0, 2.0, 220), tone(2.0, 3.0, 330)


def overlap_scene():
    """Both voices talk for the whole file, so timing cannot tell them apart."""
    a = tone(0.0, 4.0, 220)
    b = tone(0.0, 4.0, 330)
    return (a + b).astype(np.float32), a, b


def fused_overlap_scene():
    """A talks 0-3 s, B talks 2-4 s; 2-3 s is a turn overlap (UNCERTAIN)."""
    a = tone(0.0, 3.0, 220)
    b = tone(2.0, 4.0, 330)
    return (a + b).astype(np.float32), a, b


FUSED_REGIONS = [LabelledRegion(0.0, 2.0, TARGET, "A", 0.9, "voice_match"),
                 LabelledRegion(2.0, 3.0, UNCERTAIN, None, None, "overlap"),
                 LabelledRegion(3.0, 4.0, "other", "B", 0.1, "voice_match")]


def vp_of(embedder_on, samples, duration_s=1.0):
    vec = embedder_on.embed(samples)
    return Voiceprint([float(x) for x in vec], "fake-signal", duration_s,
                      {"kind": "test"}).as_dict()


def identity_baseline(stems, vp, embedder=None, separator_cls=FakeSeparator):
    base = SpeechSeparationBaseline(separator=separator_cls(list(stems)))
    base.set_context(vp, embedder or FakeEmbedder(), MATCH)
    return base


def test_full_stem_preserves_selected_source_and_discloses_local_uncertainty():
    mix, a, b = overlap_scene()
    extractor = SpeechSeparationBaseline(separator=FakeSeparator([b, a]), output_mode='stem')
    extractor.set_context(vp_of(FakeEmbedder(), a), FakeEmbedder(), MATCH)
    regions = [LabelledRegion(0, 4, UNCERTAIN, None, None, 'overlap')]
    out = extractor.extract(mix, regions)
    np.testing.assert_array_equal(out, a)
    assert extractor.last_identity['local_identity_verified'] is False
    assert extractor.last_identity['warnings']


def test_full_stem_still_refuses_ambiguous_identity():
    mix, a, b = overlap_scene()
    extractor = SpeechSeparationBaseline(separator=FakeSeparator([a, a]), output_mode='stem')
    extractor.set_context(vp_of(FakeEmbedder(), a), FakeEmbedder(), MATCH)
    with pytest.raises(ProcessingError):
        extractor.extract(mix, [LabelledRegion(0, 4, UNCERTAIN, None, None, 'overlap')])


def window_correlation(out, reference, t0, t1):
    a, b = int(t0 * SR), int(t1 * SR)
    return float(np.corrcoef(out[a:b], reference[a:b])[0, 1])


# -- reversed source order -----------------------------------------------------

def test_reversed_source_order_selects_by_embedding():
    a, b = sequential_scene()
    vp = vp_of(FakeEmbedder(), a)                      # enrolled on A's clean span
    extractor = identity_baseline([b, a], vp)          # B listed first on purpose
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", 0.9, "voice_match")]
    out = extractor.extract((a + b).astype(np.float32), regions)
    assert window_correlation(out, a, 1.15, 1.85) > 0.99
    assert np.max(np.abs(out[2 * SR + 3000:3 * SR - 3000])) == 0.0   # B never re-added
    ident = extractor.last_identity
    assert ident["selection"] == "enrollment_embedding" and ident["refusal"] is None
    assert ident["target_index"] == 1                  # identity, not stem order
    assert ident["similarities"][1] > 0.6 >= (ident["similarities"][0] or 0.0)
    assert ident["required_margin"] == pytest.approx(0.3)


def test_forward_order_picks_first_stem_by_embedding():
    a, b = sequential_scene()
    vp = vp_of(FakeEmbedder(), a)
    regions = [LabelledRegion(1.0, 2.0, TARGET, "A", 0.9, "voice_match")]
    extractor = identity_baseline([a, b], vp)
    out = extractor.extract((a + b).astype(np.float32), regions)
    assert window_correlation(out, a, 1.15, 1.85) > 0.99
    assert extractor.last_identity["target_index"] == 0


# -- fully overlapping timing ----------------------------------------------------

def test_fully_overlapping_timing_chooses_the_embedded_source():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    regions = [LabelledRegion(0.0, 4.0, TARGET, "A", 0.9, "voice_match")]
    # With only this one all-span TARGET region the timing contrast is 0 for
    # both stems: the OLD path refuses. The voiceprint must make the choice.
    extractor = identity_baseline([b, a], vp)
    out = extractor.extract(mix, regions)
    assert window_correlation(out, a, 0.25, 0.75) > 0.99
    assert window_correlation(out, a, 3.25, 3.75) > 0.99
    assert extractor.last_identity["target_index"] == 1


# -- refusals ---------------------------------------------------------------------

def test_ambiguous_embedding_refuses_the_first_stem():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    # Identity-blind embedder: both stems score 1.0. The old timing path would
    # take the first stem on ties; a margin must refuse instead.
    for stems in ([a, b], [b, a]):
        with pytest.raises(ProcessingError, match="ambiguous"):
            identity_baseline(stems, vp, FixedEmbedder(vp["vector"])).extract(mix, FUSED_REGIONS)


def test_wrong_identity_refuses():
    mix, a, b = overlap_scene()
    vp = Voiceprint([1.0, 0.0, 0.0], "fake-signal", 1.0, {"kind": "test"}).as_dict()
    embedder = FixedEmbedder([0.0, 1.0, 0.0])           # cosine to enrollment = 0
    regions = [LabelledRegion(0.5, 2.0, TARGET, "A", 0.9, "voice_match")]
    with pytest.raises(ProcessingError, match="matches the enrolled voice"):
        identity_baseline([a, b], vp, embedder).extract(mix, regions)


def test_uncertain_identity_refuses():
    mix, a, b = overlap_scene()
    target = np.array([1.0, 0.0, 0.0])
    mixed = target + 2.0 * np.array([0.0, 1.0, 0.0])    # cosine to enrollment ~0.45
    vp = Voiceprint([1.0, 0.0, 0.0], "fake-signal", 1.0, {"kind": "test"}).as_dict()
    embedder = FixedEmbedder(mixed)
    regions = [LabelledRegion(0.5, 2.0, TARGET, "A", 0.9, "voice_match")]
    extractor = identity_baseline([a, b], vp, embedder)
    with pytest.raises(ProcessingError, match="do not clearly match"):
        extractor.extract(mix, regions)
    assert extractor.last_identity["refusal"] == "uncertain_identity"
    # Between the thresholds: never assigned to the target and never reported chosen.
    assert 0.3 < extractor.last_identity["similarities"][0] < 0.6


def test_too_short_target_speech_refuses():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    regions = [LabelledRegion(0.0, 0.2, TARGET, "A", 0.9, "voice_match")]  # < 0.5 s window
    with pytest.raises(ProcessingError, match="too short or too quiet"):
        identity_baseline([a, b], vp).extract(mix, regions)


def test_silent_or_nonfinite_stems_are_never_selected():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    zero = np.zeros_like(a)
    bad = np.full_like(a, np.nan)
    regions = [LabelledRegion(0.0, 3.0, TARGET, "A", 0.9, "voice_match")]
    with pytest.raises(ProcessingError, match="too short or too quiet"):
        identity_baseline([zero, bad], vp).extract(mix, regions)
    extractor = identity_baseline([bad, a], vp)         # one dead stem, one alive
    out = extractor.extract(mix, regions)
    assert window_correlation(out, a, 1.0, 2.0) > 0.99
    ident = extractor.last_identity
    assert ident["target_index"] == 1 and ident["similarities"][0] is None


def test_embedder_mismatch_refuses():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    wrong = FixedEmbedder(np.asarray(vp["vector"]))
    wrong.name = "some-other-embedder"
    regions = [LabelledRegion(0.5, 2.0, TARGET, "A", 0.9, "voice_match")]
    with pytest.raises(ProcessingError, match="different embedder"):
        identity_baseline([a, b], vp, wrong).extract(mix, regions)


def test_short_stems_are_rejected_not_guessed():
    a, b = overlap_scene()[1:]
    vp = vp_of(FakeEmbedder(), a)
    extractor = SpeechSeparationBaseline(separator=ShortSeparator([a, b]))
    extractor.set_context(vp, FakeEmbedder(), MATCH)
    with pytest.raises(ProcessingError, match="wrong length"):
        extractor.extract((a + b).astype(np.float32), FUSED_REGIONS)


def test_a_separator_failure_never_falls_back_to_the_mask():
    class Broken:
        name = "broken"
        model = "x"

        def separate(self, samples, rate=SR):
            raise ProcessingError("the speech separator failed", retryable=True)

    vp = vp_of(FakeEmbedder(), tone(0.0, 1.0, 220))
    extractor = SpeechSeparationBaseline(separator=Broken())
    extractor.set_context(vp, FakeEmbedder(), MATCH)
    with pytest.raises(ProcessingError, match="separator"):
        extractor.extract(np.zeros(SR, dtype=np.float32), FUSED_REGIONS)


def test_no_target_region_refuses():
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    regions = []
    with pytest.raises(ProcessingError, match="no confirmed target speech"):
        identity_baseline([a, b], vp).extract(mix, regions)


# -- overlap handling on the chosen source ---------------------------------------

def test_overlap_kept_only_where_the_stem_matches_the_enrollment():
    mix, a, b = fused_overlap_scene()
    vp = vp_of(FakeEmbedder(), a[0:2 * SR], 2.0)        # enrolled on A's solo span
    extractor = identity_baseline([b, a], vp)
    out = extractor.extract(mix, FUSED_REGIONS)
    ident = extractor.last_identity
    assert ident["overlap"]["kept_s"] > 0.9             # 1 s overlap retained
    assert window_correlation(out, a, 2.2, 2.8) > 0.9   # A survives the overlap
    assert np.max(np.abs(out[3 * SR + 3000:4 * SR - 3000])) == 0.0   # B still excluded


def test_overlap_muted_when_the_stem_does_not_continue_there():
    # A stops at 2 s; in the overlap the chosen stem is silence, so identity is
    # unmeasurable. It must be muted - never filled from B's stem.
    a = tone(0.0, 2.0, 220)
    b = tone(2.0, 4.0, 330)
    mix = (a + b).astype(np.float32)
    vp = vp_of(FakeEmbedder(), a[0:2 * SR], 2.0)
    extractor = identity_baseline([b, a], vp)
    out = extractor.extract(mix, FUSED_REGIONS)
    assert np.max(np.abs(out[2 * SR + 3000:3 * SR - 3000])) == 0.0
    ident = extractor.last_identity
    assert ident["overlap"]["kept_s"] == 0.0
    assert ident["overlap"]["unmeasured_s"] > 0.0
    assert any("muted" in w for w in ident["warnings"])


def test_overlap_chunk_of_the_other_speaker_is_muted():
    # In the overlap the chosen stem "contains" the other voice (simulated by
    # giving stem A B's tone there). A chunk that reads as B is not the target
    # and must be muted.
    a = tone(0.0, 3.0, 220)
    contaminated = a.copy()
    contaminated[2 * SR:3 * SR] = tone(2.0, 3.0, 330)[2 * SR:3 * SR]
    b = tone(2.0, 4.0, 330)
    mix = (a + b).astype(np.float32)
    vp = vp_of(FakeEmbedder(), a[0:2 * SR], 2.0)
    extractor = identity_baseline([b, contaminated], vp)
    out = extractor.extract(mix, FUSED_REGIONS)
    assert np.max(np.abs(out[2 * SR + 3000:3 * SR - 3000])) == 0.0
    ident = extractor.last_identity
    assert ident["overlap"]["kept_s"] == 0.0 and ident["overlap"]["muted_s"] > 0.0


# -- engine integration -----------------------------------------------------------

def write_wav(path, samples):
    pcm = (np.clip(np.asarray(samples, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getsampwidth() == 2 and w.getnchannels() == 1
        return (np.frombuffer(w.readframes(w.getnframes()), dtype="<i2") / 32767.0).astype(np.float32)


class FakeDiarizer:
    name = "fake-diarizer"
    model_id = "fake-diarization"

    def __init__(self, turns):
        self._d = Diarization(list(turns), [], list(turns))

    def diarize(self, samples):
        return self._d

    def unload(self) -> None:
        pass


def test_engine_feeds_context_and_defers_embedder_release(tmp_path):
    a, b = sequential_scene()
    mix = (a + b).astype(np.float32)
    wav = tmp_path / "in.wav"
    write_wav(wav, mix)
    vp = vp_of(FakeEmbedder(), a)
    turns = [Segment(1.0, 2.0, "A"), Segment(2.0, 3.0, "B")]
    diarizer = FakeDiarizer(turns)
    embedder = FakeEmbedder()
    extractor = SpeechSeparationBaseline(separator=FakeSeparator([b, a]))
    engine = AudioOnlyEngine(diarizer, embedder, match=MATCH, extractor=extractor)
    result = engine.isolate(str(wav), vp, diarizer._d.as_dict(), str(tmp_path))
    audio = read_wav(result.wav_path)
    assert len(audio) == len(mix)
    assert window_correlation(audio, a, 1.15, 1.85) > 0.9
    assert np.max(np.abs(audio[2 * SR + 3000:3 * SR - 3000])) < 1e-4
    ident = result.details["identity"]
    assert ident["selection"] == "enrollment_embedding" and ident["target_index"] == 1
    assert ident["similarities"][1] > 0.6
    assert result.details["extractor"] == "speech_separation"
    # The embedder is released once, AFTER extract's final identity use: no
    # embedding may happen after the release.
    assert embedder.unloads == 1 and embedder.embeds_after_unload == 0


def test_engine_mask_extractor_has_no_identity_claim_and_early_release(tmp_path):
    a, _ = sequential_scene()
    wav = tmp_path / "in.wav"
    write_wav(wav, a)
    vp = vp_of(FakeEmbedder(), a)
    diarizer = FakeDiarizer([Segment(1.0, 2.0, "A")])
    embedder = FakeEmbedder()
    engine = AudioOnlyEngine(diarizer, embedder, match=MATCH, extractor=DuckedBaseline())
    result = engine.isolate(str(wav), vp, diarizer._d.as_dict(), str(tmp_path))
    assert result.details["identity"] is None   # a mask never claims separation


def test_engine_ambiguous_identity_refuses_with_metadata(tmp_path):
    # Identity-blind embedder: every window scores the same similarity, so the
    # regions look target-coded but the N separated sources are tied - the
    # margin must refuse at engine level instead of taking the first stem.
    a, b = sequential_scene()
    mix = (a + b).astype(np.float32)
    wav = tmp_path / "in.wav"
    write_wav(wav, mix)
    vp = Voiceprint([1.0, 0.0, 0.0], "fake-signal", 1.0, {"kind": "test"}).as_dict()
    diarizer = FakeDiarizer([Segment(1.0, 2.0, "A"), Segment(2.0, 3.0, "B")])
    engine = AudioOnlyEngine(diarizer, FixedEmbedder([3.0, 1.0, 0.0]),   # cosine ~0.95
                             match=MATCH,
                             extractor=SpeechSeparationBaseline(separator=FakeSeparator([a, b])))
    with pytest.raises(ProcessingError, match="ambiguous"):
        engine.isolate(str(wav), vp, diarizer._d.as_dict(), str(tmp_path))
    # last_identity survived inside the extractor for diagnostics.
    assert engine.extractor.last_identity["refusal"] == "ambiguous"


def test_params_reports_the_active_selection_mode():
    legacy = SpeechSeparationBaseline(separator=FakeSeparator([]))
    assert legacy.params()["selection"] == "timing_contrast"
    assert legacy.params()["other_source_added"] is False
    vp = vp_of(FakeEmbedder(), tone(0.0, 0.8, 220), 0.8)
    with_context = SpeechSeparationBaseline(separator=FakeSeparator([]))
    with_context.set_context(vp, FakeEmbedder(), MATCH)
    assert with_context.params()["selection"] == "enrollment_embedding"
    assert with_context.params()["overlap_policy"] == "evidence_gated"


def test_real_classification_full_overlap_reaches_separated_identity(tmp_path):
    from focus_ml.voice.diarizer import from_turns
    from focus_ml.voice.match import classify_regions
    mix, a, b = overlap_scene()
    diar = from_turns([Segment(0, 4, "A"), Segment(0, 4, "B")])
    embedder = FakeEmbedder()
    vp = vp_of(embedder, a)
    regions = classify_regions(mix, diar, Voiceprint.from_dict(vp), embedder, MATCH)
    assert regions and all(r.label == UNCERTAIN and r.reason == "overlap" for r in regions)
    wav = tmp_path / 'overlap.wav'
    write_wav(wav, mix)
    extractor = SpeechSeparationBaseline(separator=FakeSeparator([b, a]))
    engine = AudioOnlyEngine(FakeDiarizer([]), embedder, match=MATCH, extractor=extractor)
    result = engine.isolate(str(wav), vp, diar.as_dict(), str(tmp_path))
    assert window_correlation(read_wav(result.wav_path), a, .2, 3.8) > .99
    assert result.details['identity']['overlap']['kept_s'] == 4
    assert extractor._context is None
    assert not any('result is silent' in w for w in result.warnings)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 0.0])
def test_invalid_embedding_refuses_without_selecting_source(bad):
    class Invalid(FakeEmbedder):
        def embed(self, samples):
            return np.full(64, bad)
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    with pytest.raises(ProcessingError, match='identity could not be measured'):
        identity_baseline([a, b], vp, Invalid()).extract(mix, FUSED_REGIONS)


def test_engine_releases_embedder_and_context_on_refusal(tmp_path):
    mix, a, b = overlap_scene()
    vp = vp_of(FakeEmbedder(), a)
    embedder = FixedEmbedder(vp['vector'])
    extractor = SpeechSeparationBaseline(separator=FakeSeparator([a, b]))
    engine = AudioOnlyEngine(FakeDiarizer([]), embedder, match=MATCH, extractor=extractor)
    wav = tmp_path / 'ambiguous.wav'
    write_wav(wav, mix)
    from focus_ml.voice.diarizer import from_turns
    diar = from_turns([Segment(0, 4, 'A'), Segment(0, 4, 'B')])
    with pytest.raises(ProcessingError, match='ambiguous'):
        engine.isolate(str(wav), vp, diar.as_dict(), str(tmp_path))
    assert embedder.unloads == 1
    assert extractor._context is None
