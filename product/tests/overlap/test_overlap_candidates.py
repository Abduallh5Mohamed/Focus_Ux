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


# --- regressions found by running the real weights (CPU, LibriSpeech mixes)
def test_extracted_output_gets_the_polarity_and_level_it_has_in_the_mixture():
    rng = np.random.default_rng(0)
    target, other = rng.standard_normal(4000).astype(np.float32) * 0.1, rng.standard_normal(4000).astype(np.float32) * 0.1
    mix = target + other
    for gain in (-3.1, 58925.0, 0.002):                  # inverted/loud/quiet model output
        out = C.match_to_mixture(gain * target, mix)
        assert abs(float(np.dot(out, target) / np.dot(target, target)) - 1.0) < 0.1     # target level, right sign
    assert np.array_equal(C.match_to_mixture(np.zeros(4, np.float32), mix[:4]), np.zeros(4, np.float32))


def test_spexplus_checkpoint_keys_lose_their_sep_network_prefix():
    state = {"model": {"module.sep_network.a.weight": 1, "sep_network.b.bias": 2, "other": 3}}
    assert C._strip_state(state, "sep_network.") == {"a.weight": 1, "b.bias": 2, "other": 3}
    assert C._strip_state(state) == {"sep_network.a.weight": 1, "sep_network.b.bias": 2, "other": 3}


def test_usef_setup_fetches_the_wsj0_config_and_every_imported_helper():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    import setup_overlap as S
    assert "models/local/torch_audio_backend.py" in S.USEF_CODE_FILES      # dataio imports it
    calls, revs = [], []

    class F:
        def hf_file(self, repo, filename, dest, token=None, revision=None):
            calls.append(filename)
            revs.append(revision)

        def url_file(self, url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("x")
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as t:
        S.step_usef(F(), Path(t), None)
    assert revs and set(revs) == {S.USEF_HF_REVISION}                       # pinned, not the mutable default
    assert "chkpt/USEF-SepFormer/wsj0-2mix/config.yaml" in calls         # not .../USEF-SepFormer/config.yaml


def test_optional_wespeaker_frontends_get_a_stub_that_raises_only_on_use(monkeypatch):
    import sys
    for top in ("s3prl", "whisper", "transformers", "peft"):
        monkeypatch.setitem(sys.modules, top, None)       # importing them raises ImportError
    C._shim_optional_frontends()
    import whisper
    with pytest.raises(RuntimeError):
        whisper.load_model("x")
    assert not hasattr(whisper, "__path_missing__")
    for top in ("s3prl", "s3prl.nn", "whisper", "transformers", "peft"):
        sys.modules.pop(top, None)


def test_usef_pickle_is_not_loaded_unless_its_hash_matches(tmp_path):
    f = tmp_path / "temp_best.pth.tar"
    f.write_bytes(b"not the reviewed checkpoint")
    with pytest.raises(BlockedError) as e:
        C.verify_sha256(f, C.USEF_CHECKPOINT_SHA256)
    assert "not the reviewed checkpoint" in e.value.message and "sha256" in e.value.evidence
    import hashlib
    C.verify_sha256(f, hashlib.sha256(f.read_bytes()).hexdigest())      # matching hash passes
