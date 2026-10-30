import numpy as np
import pytest

from fakes import FREQS, SR, FakeEmbedder, tone
from helpers import voiceprint_for
from focus_ml.overlap import candidates as C
from focus_ml.overlap import weights as W
from focus_ml.overlap.base import (BLIND_THEN_SELECT, TARGET_CONDITIONED, BlindSelectExtractor, BlockedError,
                                   resample, select_by_voiceprint)
from focus_ml.voice.weights import COMPLETE_MARKER


@pytest.mark.parametrize("name", C.ORDER)
def test_each_candidate_reports_missing_weights(name, tmp_path):
    ex = C.build_candidate(name, home=tmp_path, embedder=FakeEmbedder(), clearervoice_dir=str(tmp_path / "cv"))
    with pytest.raises(BlockedError) as e:
        ex.check_ready()
    assert e.value.kind == "missing_weights" and e.value.evidence
    assert C.candidate_status(tmp_path, str(tmp_path / "cv"))[name]["blocker"]["kind"] == "missing_weights"


def test_present_files_but_missing_package_is_reported(tmp_path):
    d = W.weights_dir("sepformer_libri3mix", tmp_path)
    d.mkdir(parents=True)
    for f in W.REQUIRED_FILES["sepformer_libri3mix"] + (COMPLETE_MARKER,):
        (d / f).write_text("x")
    ex = C.build_candidate("sepformer_libri3mix", home=tmp_path, embedder=FakeEmbedder())
    ex.check_ready()
    try:
        import speechbrain  # noqa: F401
        pytest.skip("speechbrain installed")
    except ImportError:
        pass
    with pytest.raises(BlockedError) as e:
        ex.load()
    assert e.value.kind == "missing_package"


def test_honest_labels():
    blind = {"mossformer2_ss_voiceprint", "sepformer_libri3mix", "pyannote_ami_pixit"}
    for n, i in C.INFO.items():
        assert i.mechanism == (BLIND_THEN_SELECT if n in blind else TARGET_CONDITIONED)
    assert C.INFO["sepformer_libri3mix"].categories == ("overlap_3plus",)
    assert C.INFO["pyannote_ami_pixit"].categories == ("overlap_3plus",)
    assert "CC-BY-NC" in C.INFO["usef_tse"].weights_licence


def test_select_by_voiceprint_and_blind_extractor():
    emb = FakeEmbedder()
    vp = voiceprint_for("B")
    srcs = [tone(FREQS["A"], 2), tone(FREQS["B"], 2), np.zeros(2 * SR, np.float32)]
    pick = select_by_voiceprint(srcs, vp, emb)
    assert pick["index"] == 1 and pick["scores"][2] == -1.0 and pick["margin"] > 0

    class Sep(BlindSelectExtractor):
        info = C.INFO["mossformer2_ss_voiceprint"]

        def check_ready(self):
            pass

        def _separate_batch(self, windows):
            return [[tone(FREQS["A"], 2), tone(FREQS["B"], 2)] for _ in windows]
    out = Sep(emb).extract(tone(FREQS["B"], 2), vp, tone(FREQS["B"], 4))
    assert np.allclose(out, tone(FREQS["B"], 2))
    with pytest.raises(ValueError):
        select_by_voiceprint(srcs, type(vp)(vp.vector, "other", 1, {}), emb)


def test_resample_fallback_lengths_and_tone():
    x = tone(440, 1)
    y = resample(x, 16000, 8000)
    assert len(y) == 8000
    assert len(resample(y, 8000, 16000)) == 16000
