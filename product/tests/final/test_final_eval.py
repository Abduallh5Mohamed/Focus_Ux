import json
from pathlib import Path

import pytest

import eval_runner
import final_eval
import speed_tune
from focus_eval.dataset import load_dataset
from focus_eval.final_report import build_report, overlap_type, stable_metrics
from focus_eval.listening import build_kit, summarize_answers
from focus_eval.stress import CONDITIONS, degrade
from helpers import TOTAL, make_dataset, make_engine

import numpy as np


def settings(**over):
    return {"enroll": "mix_span", "embedder": "ecapa", **over}


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    return make_dataset(tmp_path_factory.mktemp("ds"))


def test_one_command_writes_report_run_and_kit(dataset, tmp_path):
    rep = final_eval.run_final(str(dataset), str(tmp_path / "out"), make_engine(), settings(stress=["noise_10db"]),
                               listening_seed=3, command="final_eval.py --dataset x")
    out = tmp_path / "out"
    assert (out / "report.json").is_file() and (out / "report.md").is_file()
    assert (out / "listening" / "key.json").is_file()
    m = rep["metrics"]
    assert m["targets_scored"] == 2 and rep["run_failures"] == []
    # three tones never overlap three at once; the 16-18 s overlap is two speakers.
    assert list(m["by_overlap_type"]) == ["two_speakers"]
    assert m["wrong_person"]["wrong"] == 0
    assert m["overall"]["all"]["target_retention"] > 0.9
    lf = m["target_leaves_the_frame"]
    assert lf["status"] == "measured" and len(lf["targets"]) == 2
    assert m["verification"]["status"] == "measured"
    noisy = m["limitations"]["noise_reverb_synthetic"]["conditions"]["noise_10db"]
    assert noisy["synthetic"] is True and noisy["n_audio_ok"] == 2
    assert m["limitations"]["whisper"] == {"status": "no_clips"}
    assert rep["timing"]["rtf_worst"] is not None


def test_visibility_independence_checks_video_blacked_out_video_and_audio_only(dataset, tmp_path):
    rep = final_eval.run_final(str(dataset), str(tmp_path / "o"), make_engine(), settings())
    vi = rep["metrics"]["visibility_independence"]
    assert vi["status"] == "pass" and vi["n_checked"] == 1
    assert len(vi["clips"]["c1"]["sha256"]) == 3


def test_report_says_when_not_measured_on_the_laptop(dataset, tmp_path):
    rep = final_eval.run_final(str(dataset), str(tmp_path / "o"), make_engine(), settings(visibility_check=False))
    assert rep["measured_on_target_laptop"] is False
    assert "NOT measured on an NVIDIA GPU" in rep["headline_warning"]
    assert rep["metrics"]["visibility_independence"]["status"] == "not_run"


def test_report_is_reproducible_from_manifest_and_settings(dataset, tmp_path):
    a = final_eval.run_final(str(dataset), str(tmp_path / "a"), make_engine(), settings(), command="x")
    b = final_eval.run_final(str(dataset), str(tmp_path / "b"), make_engine(), settings(), command="x")
    assert stable_metrics(a) == stable_metrics(b)
    assert a["reproducibility"]["settings"]["enroll"] == "mix_span"
    # a different recorded setting is visible in the report and changes the fingerprint of the run
    c = final_eval.run_final(str(dataset), str(tmp_path / "c"), make_engine(),
                             settings(match_max_chunk_s=1.0), command="x")
    assert stable_metrics(a) != stable_metrics(c)


def test_ref_enrollment_mode_runs_end_to_end(dataset, tmp_path):
    rep = final_eval.run_final(str(dataset), str(tmp_path / "r"), make_engine(),
                               {"embedder": "ecapa", "enroll": "ref", "visibility_check": False})
    assert rep["run_failures"] == [] and rep["metrics"]["wrong_person"]["wrong"] == 0


def test_no_ready_clips_is_refused(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 1, "dataset_id": "x", "clips": []}))
    with pytest.raises(ValueError, match="nothing to evaluate"):
        final_eval.run_final(str(tmp_path), str(tmp_path / "o"), make_engine(), settings())


def test_failed_target_is_recorded_not_hidden(dataset, tmp_path):
    engine = make_engine()
    engine.match.target_threshold = 5.0   # unreachable, but this only changes labels, so break enrollment instead
    real = engine.enroll_file

    def boom(*a, **k):
        raise RuntimeError("enrolment exploded")
    engine.enroll_file = boom
    rep = final_eval.run_final(str(dataset), str(tmp_path / "o"),
                               engine, {"embedder": "ecapa", "enroll": "ref", "visibility_check": False})
    assert len(rep["run_failures"]) == 2 and "exploded" in rep["run_failures"][0]["error"]
    assert rep["metrics"]["targets_scored"] == 0


def test_prefetch_and_cache_decode_each_mix_once(dataset, tmp_path):
    from focus_ml.voice import preprocess
    preprocess.clear_decode_cache()
    meta = eval_runner.produce_run(load_dataset(dataset), tmp_path / "p", make_engine(),
                                   settings(visibility_check=False, verification=False, prefetch=True))
    # one mix decode (analysis + both targets reuse it); no per-target re-decode
    assert meta["audio_decodes"] == 1


def test_overlap_type_counts_simultaneous_references():
    from helpers import SR
    from fakes import tone
    refs = {k: tone(f, 3.0) for k, f in (("a", 220), ("b", 440), ("c", 880))}
    assert overlap_type(refs) == "three_plus"
    assert overlap_type({"a": refs["a"], "b": np.zeros_like(refs["a"])}) == "none"


def test_speed_tune_runs_both_variants_and_returns_a_gate_verdict(dataset, tmp_path):
    ds = load_dataset(dataset)
    verdict = speed_tune.tune(ds, tmp_path / "t", lambda s: make_engine(),
                              {"prefetch": False, **settings()}, {"prefetch": True, **settings()}, 0.8)
    assert verdict["verdict"] in ("adopt", "reject", "inconclusive")
    assert (tmp_path / "t" / "verdict.json").is_file()
    assert verdict["quality"]["status"] in ("pass", "regression", "inconclusive")
    assert set(verdict["rtf"]["candidate"]) == {"c1"}


def test_stress_is_deterministic_and_changes_audio():
    x = np.sin(np.arange(16000) / 7).astype(np.float32) * 0.3
    for name in CONDITIONS:
        a, b = degrade(x, name, seed=1), degrade(x, name, seed=1)
        assert np.array_equal(a, b) and not np.allclose(a, x)
        assert len(a) == len(x)


def _pairs(tmp_path, n=4):
    from helpers import SR
    from fakes import tone
    from focus_ml.isolation_engines import write_wav
    pairs = []
    for i in range(n):
        for kind in ("o", "p"):
            write_wav(str(tmp_path / f"{kind}{i}.wav"), tone(200 + (i * 20 if kind == "o" else 5), 1.0), 16000)
        pairs.append({"clip_id": f"c{i}", "target": "a", "original": str(tmp_path / f"o{i}.wav"),
                      "processed": str(tmp_path / f"p{i}.wav"),
                      "reference": str(tmp_path / f"o{i}.wav")})
    return pairs


def test_listening_kit_is_anonymised_randomised_and_seeded(tmp_path):
    pairs = _pairs(tmp_path)
    a = build_kit(pairs, tmp_path / "k1", seed=5)
    b = build_kit(pairs, tmp_path / "k2", seed=5)
    c = build_kit(pairs, tmp_path / "k3", seed=6)
    ka = json.loads((tmp_path / "k1" / "key.json").read_text())
    kb = json.loads((tmp_path / "k2" / "key.json").read_text())
    kc = json.loads((tmp_path / "k3" / "key.json").read_text())
    assert ka == kb and ka != kc and a["n_items"] == 4 + 2
    names = sorted(p.name for p in (tmp_path / "k1" / "kit").iterdir())
    assert all(n.startswith("item_") or n in ("scoring_sheet.csv", "INSTRUCTIONS.txt") for n in names)
    assert sum(n.endswith("_ref.wav") for n in names) == 6
    assert not any("c0" in n or "processed" in n or "original" in n for n in names)
    sheet = (tmp_path / "k1" / "kit" / "scoring_sheet.csv").read_text()
    assert "processed" not in sheet and "c0" not in sheet
    # with enough items both sides get used for the processed clip
    assert {v["A"] for v in ka["items"].values() if v["kind"] == "test"} == {"processed", "original"}
    with pytest.raises(FileExistsError):
        build_kit(pairs, tmp_path / "k1", seed=5)


def test_listening_summary_unblinds_and_flags_bad_sheets(tmp_path):
    build_kit(_pairs(tmp_path, 6), tmp_path / "k", seed=1)
    key = json.loads((tmp_path / "k" / "key.json").read_text())["items"]
    header = (tmp_path / "k" / "kit" / "scoring_sheet.csv").read_text().splitlines()[0]
    lines = [header]
    for name, meta in key.items():
        if meta["kind"] == "control":
            lines.append(f"r1,{name},same,,,,,,,")
        else:
            pick = "A" if meta["A"] == "processed" else "B"   # rater always prefers the processed clip
            ca, cb = (5, 2) if pick == "A" else (2, 5)
            lines.append(f"r1,{name},{pick},{ca},{cb},1,3,1,2,")
    gone = next(n for n, m in key.items() if m["kind"] == "control")
    lines.remove(next(l for l in lines if l.split(",")[1] == gone))                                  # an item the rater never saw
    lines.append("r1,item_99,A,,,,,,,")                    # unknown item
    lines.append("r2,item_01,C,,,,,,,")                    # bad value
    sheet = tmp_path / "answers.csv"
    sheet.write_text("\n".join(lines) + "\n", encoding="utf-8")
    s = summarize_answers(tmp_path / "k" / "key.json", [sheet])
    assert any(gone in p and "missing" in p for p in s["problems"])
    assert s["processed_preferred"] == 6 and s["original_preferred"] == 0
    assert s["sign_test_p_two_sided"] == pytest.approx(0.0312, abs=1e-4)
    assert s["control_same_rate"] == 1.0 and s["control_warning"] is None
    assert s["mean_ratings"]["processed"]["target_clear"] == 5.0
    assert s["mean_ratings"]["original"]["target_clear"] == 2.0
    assert len(s["problems"]) == 3
