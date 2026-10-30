"""Engine selection, missing-weights errors, lip-sync speaker choice and the gate.

All audio/landmarks here are synthetic; no model, GPU or network is used.
"""
import json
import os
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from focus_ml import isolation_engines as ie
from focus_ml.clearervoice_backend import SS_MODEL, TSE_MODEL, require_weights
from focus_ml.config import AdapterConfig
from focus_ml.engine_report import (
    EngineRun, EngineSetResult, gate_verdict, render_compare_html, render_gate_html, si_sdri,
)
from focus_ml.errors import ModelUnavailableError
from focus_ml.types import ExtractionResult
from focus_ml.speaker_select import (
    choose_source, energy_envelope, mouth_openness, score_sources, sync_score,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

SR, FPS, N_FRAMES = 16000, 25, 100


def talking_pattern(seed):
    rng = np.random.default_rng(seed)
    return np.repeat(rng.random(N_FRAMES // 5 + 1) > 0.5, 5)[:N_FRAMES].astype(float)


def voice_for(pattern, seed):
    rng = np.random.default_rng(seed + 100)
    per = SR // FPS
    gate = np.repeat(pattern, per)
    return (rng.normal(0, 0.1, len(gate)) * gate).astype(np.float32)


def landmarks_for(pattern):
    out = []
    for p in pattern:
        lm = np.zeros((68, 2))
        lm[48], lm[54] = (0, 0), (10, 0)
        lm[[61, 62, 63]] = (5, 0)
        lm[[67, 66, 65]] = (5, 0.2 + 4 * p)
        out.append(lm)
    return out


def write(path, samples, sr=SR):
    ie.write_wav(str(path), samples, sr)
    return str(path)


# ---- selection --------------------------------------------------------
def test_config_default_is_dolphin_and_env_selects_engine():
    assert AdapterConfig().isolation_engine == "dolphin"
    assert AdapterConfig.from_env({}).isolation_engine == "dolphin"
    cfg = AdapterConfig.from_env({"FOCUS_ISOLATION_ENGINE": "separate_select"})
    assert cfg.isolation_engine == "separate_select"
    with pytest.raises(ValueError, match="isolation_engine"):
        AdapterConfig(isolation_engine="falcon")


def test_build_engine_picks_class_by_config():
    adapter, models = object(), lambda: None
    for name, cls in (("dolphin", ie.DolphinEngine), ("av_mossformer2", ie.AvMossFormer2Engine),
                      ("separate_select", ie.SeparateSelectEngine)):
        engine = ie.build_engine(AdapterConfig(isolation_engine=name), adapter, models,
                                 backend=SimpleNamespace(base_dir=None))
        assert isinstance(engine, cls) and engine.name == name


def test_dolphin_engine_wraps_adapter_and_labels_result():
    seen = {}

    class Adapter:
        def extract_target(self, video, target, job_dir, models, progress, video_id=None):
            seen.update(video=video, face=target.face_id, models=models, vid=video_id)
            return ExtractionResult("o.wav", 1000, 0)

    result = ie.DolphinEngine(Adapter(), lambda: "M").run("v1", "a.mp4", "f1", "/tmp")
    assert result.engine == "dolphin"
    assert seen == {"video": "a.mp4", "face": "f1", "models": "M", "vid": "v1"}


def test_runtime_uses_selected_engine(tmp_path):
    from focus_ml.runtime import LocalEngine
    local = LocalEngine(AdapterConfig(isolation_engine="av_mossformer2",
                                      clearervoice_dir=str(tmp_path)))
    assert isinstance(local.isolation, ie.AvMossFormer2Engine)
    assert isinstance(LocalEngine(AdapterConfig()).isolation, ie.DolphinEngine)


# ---- missing weights --------------------------------------------------
def test_missing_install_and_weights_give_clear_errors(tmp_path):
    with pytest.raises(ModelUnavailableError, match="Setup-ClearerVoice") as e:
        require_weights(None, (TSE_MODEL,))
    assert not e.value.retryable
    with pytest.raises(ModelUnavailableError, match="not installed"):
        require_weights(str(tmp_path / "nope"), (TSE_MODEL,))
    (tmp_path / "checkpoints" / TSE_MODEL).mkdir(parents=True)  # empty folder
    with pytest.raises(ModelUnavailableError, match=TSE_MODEL):
        require_weights(str(tmp_path), (TSE_MODEL,))
    (tmp_path / "checkpoints" / TSE_MODEL / "w.pt").write_bytes(b"x")
    require_weights(str(tmp_path), (TSE_MODEL,))


def test_initialize_fails_before_loading_when_engine_weights_missing(tmp_path):
    from focus_ml.runtime import LocalEngine
    src = tmp_path / "src"
    (src / "assets").mkdir(parents=True)
    (src / "Inference.py").write_text("")
    (src / "assets" / "20words_mean_face.npy").write_bytes(b"")
    cache = tmp_path / "cache"; cache.mkdir()
    local = LocalEngine(AdapterConfig(
        model_source=str(src), model_cache=str(cache),
        isolation_engine="separate_select", clearervoice_dir=str(tmp_path / "missing")))
    with pytest.raises(ModelUnavailableError, match="Setup-ClearerVoice"):
        local.initialize()
    assert local.models is None


# ---- lip-sync speaker choice -----------------------------------------
def test_sync_selects_voice_matching_the_lips():
    target, other, third = talking_pattern(1), talking_pattern(2), talking_pattern(3)
    sources = [voice_for(other, 2), voice_for(target, 1), voice_for(third, 3)]
    mouth = mouth_openness(landmarks_for(target))
    selection = choose_source(score_sources(sources, SR, mouth, FPS))
    assert selection.index == 1
    assert selection.confidence == "ok" and not selection.warnings
    assert [s["index"] for s in selection.as_dict()["sources"]] == [0, 1, 2]


def test_tolerates_small_av_offset():
    p = talking_pattern(4)
    mouth = mouth_openness(landmarks_for(np.roll(p, 2)))
    score, lag = sync_score(mouth, energy_envelope(voice_for(p, 4), SR, FPS, N_FRAMES))
    assert score > 0.8 and lag != 0


def test_weak_and_ambiguous_confidence_warn_and_silent_source_scores_zero():
    flat = mouth_openness(landmarks_for(np.zeros(N_FRAMES)))  # lips never move
    sources = [voice_for(talking_pattern(5), 5), np.zeros(N_FRAMES * SR // FPS, np.float32)]
    scores = score_sources(sources, SR, flat, FPS)
    assert scores[1].score == 0.0
    weak = choose_source(scores)
    assert weak.confidence == "weak" and "weak lip-sync" in weak.warnings[0]
    p = talking_pattern(6)
    twin = score_sources([voice_for(p, 6), voice_for(p, 6)], SR,
                         mouth_openness(landmarks_for(p)), FPS)
    assert choose_source(twin).confidence == "ambiguous"
    with pytest.raises(ValueError):
        choose_source([])


# ---- ClearerVoice engines with fake tracking/model --------------------
class FakeTracker:
    def __init__(self, tmp, pattern):
        self.tmp, self.pattern = tmp, pattern

    def track(self, video_id, video_path, face_id):
        self.face_id = face_id
        return {"boxes": [(10, 20, 110, 140)] * N_FRAMES, "landmarks": landmarks_for(self.pattern),
                "warnings": ["tracker note"], "frame_size": (320, 240), "n_frames": N_FRAMES}

    def extract_audio(self, video_path, job_dir):
        return write(Path(job_dir) / "mix.wav", np.zeros(N_FRAMES * SR // FPS, np.float32) + 0.01)


class FakeBackend:
    base_dir = None

    def __init__(self, tmp, patterns):
        self.tmp, self.patterns = tmp, patterns
        self.crop_seen = None

    def extract_target_speaker(self, video, out_dir):
        self.crop_seen = video
        os.makedirs(out_dir)
        return [write(Path(out_dir) / "t.wav", voice_for(self.patterns[0], 0), 8000)]

    def separate(self, wav, out_dir):
        os.makedirs(out_dir)
        return [write(Path(out_dir) / f"s{i}.wav", voice_for(p, i)) for i, p in enumerate(self.patterns)]


def ready(engine):
    engine.check_ready = lambda: None
    return engine


def test_separate_select_end_to_end_with_fakes(tmp_path):
    target = talking_pattern(11)
    patterns = [talking_pattern(10), talking_pattern(12), target]
    cfg = AdapterConfig(isolation_engine="separate_select")
    engine = ready(ie.SeparateSelectEngine(FakeTracker(tmp_path, target),
                                           FakeBackend(tmp_path, patterns), cfg))
    result = engine.run("vid", "v.mp4", "face-2", str(tmp_path))
    assert result.engine == "separate_select" and result.source_offset_ms == 0
    assert result.duration_ms == 4000
    assert result.details["selected_source"] == 2
    assert len(result.details["sources"]) == 3  # every separated source is recorded
    assert "tracker note" in result.warnings
    assert {"detect_track", "separate", "select", "total"} <= set(result.timings)
    with wave.open(result.wav_path) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (SR, 1, 64000)


def test_av_mossformer2_uses_target_crop_and_fixes_rate_and_length(tmp_path):
    cfg = AdapterConfig(isolation_engine="av_mossformer2")
    backend = FakeBackend(tmp_path, [talking_pattern(1)])
    engine = ready(ie.AvMossFormer2Engine(FakeTracker(tmp_path, talking_pattern(1)), backend, cfg))
    crops = []
    result = engine.run("vid", "v.mp4", "face-1", str(tmp_path),
                        cropper=lambda v, region, out: crops.append(region) or out)
    assert crops == [(0, 6, 126, 146)] or crops[0][2] % 2 == 0
    assert backend.crop_seen.endswith("face_crop.mp4")
    assert result.engine == "av_mossformer2"
    with wave.open(result.wav_path) as w:  # 8 kHz model output resampled to 16 kHz, same length as mix
        assert (w.getframerate(), w.getnframes()) == (SR, 64000)
    assert any("crop" in w for w in result.warnings)


def test_crop_region_is_even_clamped_and_rejects_tiny():
    x, y, w, h = ie.crop_region([(0, 0, 100, 100), None, (50, 50, 300, 260)], (320, 240))
    assert (x, y) == (0, 0) and w % 2 == 0 and h % 2 == 0 and x + w <= 320 and y + h <= 240
    with pytest.raises(Exception):
        ie.crop_region([(0, 0, 4, 4)], (320, 240))


# ---- gate and pages ---------------------------------------------------
def result(engine, sdri, warm=3.0, clip=15.0, errors=0):
    return EngineSetResult(engine, sdri, [warm] * 3, clip, errors)


def test_gate_requires_all_three_conditions():
    good = result("a", [11, 12, 13])
    v = gate_verdict([good, result("b", [20, 20], warm=9.0)], {"a": True, "b": True})
    assert v["status"] == "pass" and v["winner"] == "a"
    assert gate_verdict([good], {})["status"] == "fail"             # no listening pass
    assert gate_verdict([result("a", [9, 9, 12])], {"a": True})["status"] == "fail"
    assert gate_verdict([result("a", [12], clip=8)], {"a": True})["status"] == "fail"
    assert gate_verdict([result("a", [12], errors=1)], {"a": True})["status"] == "fail"


def test_gate_failure_names_closest_engine():
    v = gate_verdict([result("far", [2, 3], warm=9), result("near", [9, 9])],
                     {"far": False, "near": True})
    assert v["status"] == "fail" and v["winner"] is None and v["closest"] == "near"
    assert "No engine passed" in v["message"] and "near" in v["message"]
    assert "No engine passed" in render_gate_html(v)


def test_si_sdri_and_compare_page():
    rng = np.random.default_rng(0)
    ref, noise = rng.normal(size=8000), rng.normal(size=8000)
    mix = ref + noise
    assert si_sdri(ref + 0.1 * noise, mix, ref) > 10
    runs = [EngineRun("dolphin", "dolphin.wav", {"tse": 1.2}, 4.0, 2.5, 12.3, ["w<b>"]),
            EngineRun("av_mossformer2", error="weights missing")]
    page = render_compare_html("clip.mp4", "original_mix.wav", runs, True)
    assert page.count("<audio") == 2  # original + one engine with output
    assert "12.30 dB" in page and "weights missing" in page and "w&lt;b&gt;" in page
    assert "tse: 1.2s" in page
    assert "no clean reference" in render_compare_html("c", "m.wav", runs[:1], False)


# ---- 3-speaker set and setup -----------------------------------------
def test_three_speaker_plan_and_exact_mix():
    import three_speaker_set as t
    plans = t.plan_mixes(["a", "b", "c"])
    assert len(plans) >= 10 and len({p["id"] for p in plans}) == len(plans)
    assert all(sorted(p["order"]) == ["a", "b", "c"] for p in plans)
    assert len({tuple(p["order"]) for p in plans}) == 6
    with pytest.raises(ValueError):
        t.plan_mixes(["a", "b"])
    rng = np.random.default_rng(1)
    sigs = [rng.normal(size=1000) * 0.5 for _ in range(3)]
    mix, refs = t.mix_signals(sigs, [3.0, -3.0, 0.0])
    assert np.allclose(mix, sum(refs)) and np.abs(mix).max() <= 0.9 + 1e-9


def test_setup_refuses_to_change_protected_packages():
    import setup_clearervoice as s
    report = {"install": [{"metadata": {"name": "librosa", "version": "0.10"}},
                          {"metadata": {"name": "torch", "version": "2.9"}},
                          {"metadata": {"name": "NumPy", "version": "1"}}]}
    wanted, blocked = s.plan_install(report)
    assert wanted == ["librosa==0.10"] and blocked == ["torch==2.9", "NumPy==1"]
    wanted, blocked = s.plan_install({"install": [{"metadata": {"name": "numpy", "version": "2"}}]})
    assert blocked == ["numpy==2"]


def test_setup_declined_downloads_nothing(monkeypatch, tmp_path, capsys):
    import setup_clearervoice as s
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    monkeypatch.setattr(s, "_pip", lambda *a: pytest.fail("must not install"))
    assert s.main(tmp_path / "cv") == 1
    assert not (tmp_path / "cv").exists()
