import json

import numpy as np
import pytest

from fakes import FREQS, SR, tone
from focus_ml.overlap import metrics as M
from focus_ml.overlap.report import blind_labels, render_html
from helpers import info

REG = [{"start": 0, "end": 2, "active": ["T"]}, {"start": 2, "end": 4, "active": ["T", "O"]},
       {"start": 4, "end": 6, "active": ["O", "P"]}, {"start": 6, "end": 8, "active": ["T", "O", "P"]},
       {"start": 8, "end": 9, "active": ["O"]}]


def clip():
    t, o, p = (tone(FREQS[k], 9, 0.3) for k in "ABC")
    refs = {"T": t.copy(), "O": o.copy(), "P": p.copy()}
    for k, (a, b) in (("T", (2, 4)),):
        pass
    refs["T"][4 * SR:6 * SR] = 0
    refs["T"][8 * SR:] = 0
    refs["O"][:2 * SR] = 0
    refs["P"][:6 * SR] = 0
    refs["P"][7 * SR:] = 0
    mix = refs["T"] + refs["O"] + refs["P"]
    return mix, refs


def test_categories():
    assert M.region_category(["T"], "T") == "target_alone"
    assert M.region_category(["T", "O"], "T") == "overlap_2"
    assert M.region_category(["T", "O", "P"], "T") == "overlap_3plus"
    assert M.region_category(["O", "P"], "T") == "others_overlap"
    assert M.region_category(["O"], "T") is None


def test_perfect_muted_and_wrong():
    mix, refs = clip()
    rows = M.score_clip(refs["T"], mix, refs, "T", REG)
    ov = [r for r in rows if r["category"] == "overlap_2"][0]
    assert ov["retention"] > 0.99 and ov["wrong_person"] is False and ov["si_sdri_db"] > 5
    assert [r for r in rows if r["category"] == "others_overlap"][0]["muted"]
    rows = M.score_clip(np.zeros_like(mix), mix, refs, "T", REG)
    ov = [r for r in rows if r["category"] == "overlap_2"][0]
    assert ov["muted"] and ov["wrong_person"] is None and ov["retention"] == 0 and ov["si_sdr_db"] == M.SDR_FLOOR_DB
    wrong = refs["O"]
    rows = M.score_clip(wrong, mix, refs, "T", REG)
    assert [r for r in rows if r["category"] == "overlap_2"][0]["wrong_person"] is True
    agg = M.aggregate(rows)
    assert agg["overlap_2"]["wrong_person_rate"] == 1.0 and agg["overlap_3plus"]["regions"] == 1


def pooled(s, w=0.0, r=0.8):
    return {"regions": 4, "si_sdri_db_mean": s, "wrong_person_rate": w, "retention_mean": r}


def test_decision_paths():
    basis = {"language": "egyptian_arabic", "device": "cuda"}
    base = pooled(-5.0, r=0.0)
    s = {"a": {"overlap": pooled(4.0), "blocked": None}, "b": {"overlap": pooled(2.0), "blocked": None},
         "c": {"overlap": pooled(-5.2), "blocked": None},
         "d": {"overlap": None, "blocked": {"kind": "missing_weights"}},
         "e": {"overlap": pooled(9.0, w=0.5), "blocked": None},
         "f": {"overlap": pooled(8.0), "blocked": None, "categories": ["overlap_3plus"]}}
    d = M.decide(s, base, basis)
    assert d["status"] == "decided" and d["default"] == "a" and d["fallback"] == "b"
    assert d["three_plus_option"] == "f" and "c" in d["rejected"] and "e" in d["rejected"] and "d" in d["rejected"]
    d = M.decide(s, base, {"language": "english", "device": "cpu"})
    assert d["status"] == "decided_provisional" and "not an Egyptian" in d["text"]
    d = M.decide({"c": s["c"]}, base, basis)
    assert d["status"] == "no_candidate_improves" and "fine-tun" in d["fine_tuning_plan"]
    d = M.decide({"d": s["d"]}, base, basis)
    assert d["status"] == "no_measurements" and d["default"] is None


def test_blind_labels_and_report_html():
    lab = blind_labels(["x", "y", "z"], "s")
    assert sorted(lab) == ["A", "B", "C"] and sorted(lab.values()) == ["x", "y", "z"]
    assert lab == blind_labels(["z", "y", "x"], "s")
    cand = {"info": info("m", mechanism="blind_separation_then_voiceprint_selection").as_dict(), "blocked": None,
            "aggregate": {c: None for c in M.CATEGORIES}, "timing": {}, "overlap": None}
    cand["info"]["mechanism"] = "blind_separation_then_voiceprint_selection"
    blocked = {"info": info("w").as_dict(), "blocked": {"kind": "missing_weights", "message": "m", "evidence": "ev"}}
    rep = {"basis": {}, "baseline": {"aggregate": {c: None for c in M.CATEGORIES}},
           "candidates": {"m": cand, "w": blocked}, "decision": M.decide({}, {}, {}),
           "listening": [{"clip": "c", "mix": "m.wav", "items": [{"label": "A", "file": "A.wav"}],
                          "key": {"A": "m"}}], "real_clips": [], "limitations": ["lim"]}
    html = render_html(rep)
    assert "not voice-conditioned" in html and "Reveal which is which" in html and "ev" in html
    assert html.index("A.wav") < html.index("A = m")
