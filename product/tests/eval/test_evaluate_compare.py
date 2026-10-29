import json

import pytest

from eval_helpers import make_dataset, make_run
from focus_eval.cli import main, make_template
from focus_eval.compare import Thresholds, compare_reports
from focus_eval.dataset import load_dataset, validate_dataset
from focus_eval.evaluate import evaluate


@pytest.fixture
def env(tmp_path):
    ds_dir = tmp_path / "ds"
    sigs = make_dataset(ds_dir)
    return tmp_path, ds_dir, sigs


def _report(env, name, **kw):
    tmp, ds_dir, sigs = env
    run = make_run(tmp / name, sigs, label=name, **kw)
    return evaluate(load_dataset(ds_dir), run)


def test_good_run_scores(env):
    rep = _report(env, "good")
    s = rep["summary"]
    assert rep["not_ready_clips"] == ["c2"]
    assert s["n_targets"] == 2 and s["n_audio_ok"] == 2
    assert s["wrong_person"] == {"evaluable": 2, "wrong": 0, "rate": 0.0, "ambiguous": 0}
    assert s["si_sdri_db"]["mean"] > 5
    assert s["text_verified"]["cer"] == 0.0
    assert rep["by_tag"]["overlap"]["n_targets"] == 2
    row = next(r for r in rep["rows"] if r["speaker_id"] == "a")
    assert row["margin_db"] > 20 and abs(row["lag_ms"]) < 1


def test_swapped_output_is_wrong_person(env):
    rep = _report(env, "swap", swap=True)
    wp = rep["summary"]["wrong_person"]
    assert wp["wrong"] == 2 and wp["rate"] == 1.0
    assert rep["summary"]["si_sdri_db"]["mean"] < 0


def test_missing_audio_is_counted_not_skipped(env):
    rep = _report(env, "drop", drop_b=True)
    s = rep["summary"]
    assert s["n_targets"] == 2 and s["n_missing_audio"] == 1
    row = next(r for r in rep["rows"] if r["speaker_id"] == "b")
    assert row["audio_status"] == "missing_audio" and "si_sdri" not in row


def test_provisional_references_stay_separate(tmp_path):
    ds_dir = tmp_path / "ds"
    sigs = make_dataset(ds_dir, status_b="provisional_asr")
    rep = evaluate(load_dataset(ds_dir), make_run(tmp_path / "r", sigs, text_b="شئ مختلف تماما"))
    s = rep["summary"]
    assert s["text_verified"]["n_scored"] == 1 and s["text_verified"]["cer"] == 0.0
    assert s["text_provisional"]["n_scored"] == 1 and s["text_provisional"]["cer"] > 0.5


def test_missing_hypothesis_is_reported(env):
    tmp, ds_dir, sigs = env
    run = make_run(tmp / "nohyp", sigs)
    (run / "c1" / "a.txt").unlink()
    rep = evaluate(load_dataset(ds_dir), run)
    assert rep["summary"]["n_text_missing_hypothesis"] == 1


def test_compare_identical_reports_has_no_regressions(env):
    rep = _report(env, "good")
    cmp = compare_reports(rep, rep)
    assert cmp["ok"] and cmp["status"] == "pass" and cmp["n_compared"] == 2


def test_compare_flags_each_regression_kind(env):
    base = _report(env, "base")
    bad = _report(env, "bad", swap=True, text_a="كلام تاني خالص", drop_b=False)
    kinds = {r["kind"] for r in compare_reports(base, bad)["regressions"]}
    assert {"si_sdri_drop", "wrong_person", "cer_increase", "cer_increase_overall"} <= kinds

    lost = _report(env, "lost", drop_b=True)
    kinds = {r["kind"] for r in compare_reports(base, lost)["regressions"]}
    assert "audio_lost" in kinds


def test_compare_thresholds_are_configurable(env):
    base = _report(env, "base")
    worse = _report(env, "worse", text_a="أنا كنت معيدة في الجامعه ونص")
    assert not compare_reports(base, worse, Thresholds(cer_increase=0.01))["ok"]
    assert compare_reports(base, worse, Thresholds(cer_increase=0.9))["ok"]


def test_compare_ignores_provisional_text_unless_asked(tmp_path):
    ds_dir = tmp_path / "ds"
    sigs = make_dataset(ds_dir, status_b="provisional_asr")
    ds = load_dataset(ds_dir)
    base = evaluate(ds, make_run(tmp_path / "b", sigs, label="b"))
    cand = evaluate(ds, make_run(tmp_path / "c", sigs, label="c", text_b="غلط تماما هنا"))
    assert compare_reports(base, cand)["ok"]
    assert not compare_reports(base, cand, Thresholds(include_provisional=True))["ok"]


def test_candidate_missing_a_baseline_row_is_a_regression(env):
    base = _report(env, "base")
    cand = _report(env, "cand")
    cand["rows"] = [r for r in cand["rows"] if r["speaker_id"] != "b"]
    kinds = [r["kind"] for r in compare_reports(base, cand)["regressions"]]
    assert kinds == ["missing_in_candidate"]


def test_template_has_ten_clips_and_validates_as_incomplete(tmp_path):
    t = make_template()
    assert len(t["clips"]) == 10
    assert {tag for c in t["clips"] for tag in c["tags"]} == {
        "baseline", "head_motion", "face_disappears", "similar_voices", "overlap"}
    assert main(["init-template", "--out", str(tmp_path / "d")]) == 0
    assert main(["init-template", "--out", str(tmp_path / "d")]) == 2  # no overwrite
    ds = load_dataset(tmp_path / "d")
    assert all("template" in p for p in validate_dataset(ds))
    assert main(["validate", "--dataset", str(tmp_path / "d")]) == 0


def test_validate_catches_bad_ready_clip(env):
    _, ds_dir, _ = env
    (ds_dir / "clips" / "c1" / "a_ref.wav").unlink()
    problems = validate_dataset(load_dataset(ds_dir))
    assert any("ref_audio missing" in p for p in problems)
    assert main(["validate", "--dataset", str(ds_dir)]) == 1


def test_cli_end_to_end_exit_codes(env, capsys):
    tmp, ds_dir, sigs = env
    good = make_run(tmp / "good", sigs, label="good")
    bad = make_run(tmp / "bad", sigs, label="bad", swap=True)
    out_g, out_b = tmp / "g.json", tmp / "b.json"
    assert main(["evaluate", "--dataset", str(ds_dir), "--run", str(good), "--out", str(out_g)]) == 0
    assert main(["evaluate", "--dataset", str(ds_dir), "--run", str(bad), "--out", str(out_b)]) == 0
    assert json.loads(out_g.read_text(encoding="utf-8"))["run_label"] == "good"
    assert main(["compare", "--baseline", str(out_g), "--candidate", str(out_g)]) == 0
    assert main(["compare", "--baseline", str(out_g), "--candidate", str(out_b)]) == 1
    assert "REGRESSION" in capsys.readouterr().out
    assert main(["evaluate", "--dataset", str(ds_dir), "--run", str(tmp / "nope")]) == 2


def test_compare_with_nothing_scored_is_inconclusive_not_green(tmp_path, capsys):
    ds_dir = tmp_path / "tpl"
    assert main(["init-template", "--out", str(ds_dir)]) == 0
    runs = []
    for name in ("r1", "r2"):
        run = tmp_path / name
        run.mkdir()
        out = tmp_path / f"{name}.json"
        assert main(["evaluate", "--dataset", str(ds_dir), "--run", str(run), "--out", str(out)]) == 0
        runs.append(out)
    cmp = compare_reports(*(json.loads(p.read_text(encoding="utf-8")) for p in runs))
    assert cmp["status"] == "inconclusive" and not cmp["ok"]
    assert main(["compare", "--baseline", str(runs[0]), "--candidate", str(runs[1])]) == 3
    assert "INCONCLUSIVE" in capsys.readouterr().out


def test_compare_with_all_audio_missing_is_inconclusive(env):
    base = _report(env, "m1", drop_b=True)
    cand = _report(env, "m2", drop_b=True)
    for rep in (base, cand):
        for r in rep["rows"]:
            r["audio_status"] = "missing_audio"
    assert compare_reports(base, cand)["status"] == "inconclusive"


def test_compare_different_datasets_is_inconclusive(env, tmp_path):
    good = _report(env, "good")
    other = json.loads(json.dumps(good))
    other["dataset_id"] = "another-dataset"
    cmp = compare_reports(good, other)
    assert cmp["status"] == "inconclusive" and not cmp["ok"]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(good), encoding="utf-8")
    b.write_text(json.dumps(other), encoding="utf-8")
    assert main(["compare", "--baseline", str(a), "--candidate", str(b)]) == 3


def test_regression_status_and_exit_code_stay_distinct(env):
    base = _report(env, "base")
    bad = _report(env, "bad", swap=True)
    assert compare_reports(base, bad)["status"] == "regression"
