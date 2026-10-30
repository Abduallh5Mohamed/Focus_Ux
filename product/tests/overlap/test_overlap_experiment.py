import numpy as np
import pytest

from focus_ml.overlap import experiment as EX
from focus_ml.overlap import experiment_metrics as X

SR = 16000


def _scene():
    rng = np.random.default_rng(1)
    n = SR * 4
    t, o = rng.standard_normal(n) * 0.1, rng.standard_normal(n) * 0.1
    regions = [{"start": 0, "end": 1, "active": ["T"]}, {"start": 1, "end": 3, "active": ["T", "O"]},
               {"start": 3, "end": 4, "active": ["O"]}]
    return t.astype(np.float32), o.astype(np.float32), (t + o).astype(np.float32), regions


def test_overlap_mask_is_only_where_target_and_another_talk():
    _, _, mix, regions = _scene()
    m = X.overlap_mask(regions, "T", len(mix))
    assert m.sum() == 2 * SR and m[SR] and not m[SR - 1] and not m[3 * SR]


def test_perfect_target_has_full_retention_and_no_leakage():
    t, o, mix, regions = _scene()
    s = X.score_output(t, mix, {"T": t, "O": o}, "T", regions)["overlap"]
    assert s["target_retention"] == pytest.approx(1.0, abs=0.01) and s["leakage_share"] < 0.01
    assert s["si_sdri_db"] > 20 and s["muted_share"] == 0.0


def test_untouched_mixture_leaks_everything_and_muted_output_scores_the_floor():
    t, o, mix, regions = _scene()
    s = X.score_output(mix, mix, {"T": t, "O": o}, "T", regions)["overlap"]
    assert s["leakage_share"] == pytest.approx(1.0, abs=0.01) and s["leakage_ratio"] == pytest.approx(1.0, abs=0.05)
    z = X.score_output(np.zeros_like(mix), mix, {"T": t, "O": o}, "T", regions)["overlap"]
    assert z["muted_share"] == 1.0 and z["si_sdr_db"] == X.SDR_FLOOR_DB and z["target_retention"] == 0.0
    assert z["leakage_ratio"] is None and z["stoi"] is None and "silent" in z["quality_errors"][0]


def test_inverted_output_is_not_retained():
    t, o, mix, regions = _scene()
    assert X.score_output(-t, mix, {"T": t, "O": o}, "T", regions)["overlap"]["target_retention"] == 0.0


def test_rule_requires_improvement_retention_and_low_leakage():
    good = {"si_sdri_db": 5.0, "target_retention": 0.8, "leakage_ratio": 0.1}
    assert X.improves(good)["improves"]
    for bad in ({**good, "si_sdri_db": 0.5}, {**good, "target_retention": 0.1}, {**good, "leakage_ratio": 0.9},
                {**good, "leakage_ratio": None}):
        assert not X.improves(bad)["improves"] and X.improves(bad)["reasons"]
    assert not X.improves(None)["improves"]


def test_groups_are_pooled_separately_and_none_is_skipped():
    metas = [{"id": "a", "n_overlap": 2, "target_rel_db": 0.0, "scenario": "full"},
             {"id": "b", "n_overlap": 3, "target_rel_db": 0.0, "scenario": "full"}]
    row = lambda v: {"overlap": {"si_sdri_db": v, "target_retention": 1.0}, "clip": {"si_sdri_db": v}}
    pooled = EX.pool_report(metas, {"x:hybrid": {"a": row(10.0), "b": row(2.0)}})
    assert pooled["2"]["x:hybrid"]["overlap"]["si_sdri_db"] == 10.0
    assert pooled["3"]["x:hybrid"]["overlap"]["si_sdri_db"] == 2.0
    assert X.pool([None, {"si_sdri_db": 4.0}])["si_sdri_db"] == 4.0


def test_error_record_keeps_the_exact_text():
    try:
        raise RuntimeError("exact failure text 123")
    except RuntimeError as exc:
        rec = EX.error_record(exc)
    assert rec["type"] == "RuntimeError" and rec["message"] == "exact failure text 123"
