import json
import os
import sys
import wave

import numpy as np
import pytest

_EVAL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "eval"))
sys.path.insert(0, _EVAL)

from focus_eval.voice_dataset import validate  # noqa: E402
from focus_eval.voice_metrics import (calibrate_thresholds, der, eer, far_frr,  # noqa: E402
                                      gate_metrics, verification_trials)
from focus_eval.voice_mix import activity_segments, build_mix, plan_conversation  # noqa: E402

SR = 16000


def test_eer_far_frr_and_calibration():
    tgt = [0.9, 0.8, 0.85, 0.7, 0.6]
    oth = [0.1, 0.2, 0.3, 0.65, 0.15]
    e = eer(tgt, oth)
    assert 0 <= e["eer"] <= 0.3
    r = far_frr(tgt, oth, 0.5)
    assert r["far"] == pytest.approx(0.2) and r["frr"] == 0.0
    cal = calibrate_thresholds(tgt, oth, max_far=0.0, max_target_as_other=0.0)
    assert cal["target_threshold"] > 0.65 and cal["other_threshold"] <= cal["target_threshold"] - 0.05
    with pytest.raises(ValueError):
        eer([0.5], [])


def test_verification_trials_split():
    rng = np.random.default_rng(0)
    base = {"a": np.eye(4)[0], "b": np.eye(4)[1]}
    emb = {s: [(v + 0.05 * rng.standard_normal(4)) / 1 for _ in range(6)] for s, v in base.items()}
    emb = {s: [x / np.linalg.norm(x) for x in v] for s, v in emb.items()}
    t, o = verification_trials(emb, enroll_n=3)
    assert len(t) == 6 and len(o) == 6 and min(t) > max(o)


def test_der_perfect_and_confused_and_mapping():
    ref = {"A": [(0, 5)], "B": [(5, 10)]}
    assert der(ref, {"x": [(0, 5)], "y": [(5, 10)]}, 10)["der"] == pytest.approx(0)   # labels are free
    d = der(ref, {"x": [(0, 10)]}, 10)
    assert d["der"] == pytest.approx(0.5) and d["confusion"] == pytest.approx(0.5)
    d = der(ref, {"x": [(0, 5)]}, 10)
    assert d["miss"] == pytest.approx(0.5)


def test_gate_metrics_retention_and_wrong_person():
    target, other = [(0, 4), (8, 10)], [(4, 8), (9, 10)]   # overlap 9-10
    m = gate_metrics([(0, 3), (4, 5)], target, other, 10)
    assert m["target_solo_s"] == pytest.approx(5.0)
    assert m["target_retention"] == pytest.approx(3 / 5)
    assert m["wrong_person_rate"] == pytest.approx(1 / 4)
    assert m["overlap_s"] == pytest.approx(1.0)


def test_mix_has_exact_refs_truth_and_overlap():
    t = np.arange(SR * 30) / SR
    clips = {"A": 0.3 * np.sin(2 * np.pi * 220 * t), "B": 0.3 * np.sin(2 * np.pi * 440 * t)}
    plan = plan_conversation(["A", "B"], 4, 3.0, 1.0)
    assert [p["start"] for p in plan] == [0.0, 2.0, 4.0, 6.0]
    mix, refs, truth = build_mix(clips, plan, {"A": 3.0})
    assert np.allclose(mix, sum(refs.values()))
    assert len(mix) == 9 * SR
    a, b = truth["A"], truth["B"]
    assert a and b and a[0][0] < 0.1 and b[0][0] == pytest.approx(2.0, abs=0.1)
    assert activity_segments(np.zeros(SR)) == []
    with pytest.raises(ValueError):
        plan_conversation(["A"], 3, 3.0, 0.0)


def _wav(path, seconds):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"\x00\x00" * int(SR * seconds))


def test_manifest_validation(tmp_path):
    _wav(tmp_path / "audio/s1.wav", 70)
    _wav(tmp_path / "audio/o1.wav", 10)
    (tmp_path / "annotations").mkdir()
    (tmp_path / "annotations/o1.json").write_text("{}")
    m = {"schema": "focus-voice-recordings/1", "dataset_id": "t",
         "consents": [{"id": "C1", "speaker_id": "S1", "signed": True},
                      {"id": "C2", "speaker_id": "S2", "signed": False}],
         "recordings": [
             {"id": "r1", "kind": "solo", "file": "audio/s1.wav", "speakers": ["S1"], "consent_ids": ["C1"],
              "conditions": {"volume": "normal", "distance_m": 0.3, "noise": "quiet", "room": "small"}},
             {"id": "r2", "kind": "overlap", "file": "audio/o1.wav", "speakers": ["S1", "S2"],
              "consent_ids": ["C1", "C2"], "annotation": "annotations/o1.json"},
             {"id": "r3", "kind": "solo", "file": "audio/missing.wav", "speakers": ["S1"], "consent_ids": []}]}
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    rep = validate(tmp_path)
    errs = " | ".join(rep["errors"])
    assert "consent C2: not signed" in errs and "file missing" in errs
    assert "speaker S1: no signed consent" in errs
    warns = " | ".join(rep["warnings"])
    assert "at least 3" in warns and "no solo recording" in warns and "leaves_frame" in warns
    assert rep["coverage"]["solo_seconds"]["S1"] == 70.0
