import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from fakes import FREQS, SR, FakeEmbedder, tone
from helpers import ToneExtractor, info
from focus_ml.isolation_engines import write_wav
from focus_ml.overlap.base import BlockedError, OverlapExtractor
from focus_ml.overlap.bakeoff import run_bakeoff

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class Missing(OverlapExtractor):
    info = info("missing")

    def check_ready(self):
        raise BlockedError("no weights", "missing_weights", "missing: weights/x")


@pytest.fixture
def mixset(tmp_path):
    solo = tmp_path / "solo"
    solo.mkdir()
    for k in "ABC":
        write_wav(str(solo / f"{k}.wav"), tone(FREQS[k], 40), SR)
    out = tmp_path / "set"
    metas = _tool("overlap_set").build(solo, out, "synthetic_tones", 6, None, seed=1)
    return out, metas


def test_set_builder_conditions_and_enrollment_reserved(mixset):
    out, metas = mixset
    assert len(metas) == 6 and {m["n_overlap"] for m in metas} == {2, 3}
    assert any(m["snr_db"] is not None for m in metas)
    assert (out / "enroll" / "A.wav").is_file() and (out / "mix01" / "mix.wav").is_file()
    assert json.loads((out / "set.json").read_text())["language"] == "synthetic_tones"
    cats = {tuple(r["active"]) for m in metas for r in m["regions"]}
    assert len(max(cats, key=len)) >= 2


def test_bakeoff_report_with_fakes(mixset, tmp_path):
    out, _ = mixset
    infos = {"good": info("good"), "missing": info("missing"), "wrong": info("wrong")}

    def build(name):
        return {"good": ToneExtractor(), "wrong": ToneExtractor(wrong=True), "missing": Missing()}[name]
    res = tmp_path / "res"
    rep = run_bakeoff(out, res, ["good", "missing", "wrong"], build, FakeEmbedder(),
                      {"data": "tones", "device": "cpu"}, infos, listen_mixes=2)
    assert rep["candidates"]["missing"]["blocked"]["kind"] == "missing_weights"
    good = rep["candidates"]["good"]
    assert good["overlap"]["si_sdri_db_mean"] > rep["baseline"]["overlap"]["si_sdri_db_mean"] + 1
    assert good["overlap"]["wrong_person_rate"] == 0
    assert rep["candidates"]["wrong"]["overlap"]["retention_mean"] < 0.1     # muted by the post-check
    assert rep["decision"]["default"] == "good" and rep["decision"]["status"] == "decided_provisional"
    for f in ("report.html", "report.json", "decision.md", "rows.json"):
        assert (res / f).is_file()
    assert len(rep["listening"]) == 2 and (res / rep["listening"][0]["items"][0]["file"]).is_file()
    names = {v for v in rep["listening"][0]["key"].values()}
    assert names == {"gated_baseline", "good", "wrong"}


def test_setup_is_approval_first(tmp_path, capsys):
    s = _tool("setup_overlap")

    class Boom:
        def __getattr__(self, n):
            raise AssertionError("downloaded without approval")
    called = []
    rc = s.main(tmp_path, fetcher=Boom(), ask=lambda _: "no", packages=lambda h: called.append(1) or 0)
    assert rc == 1 and not called and not (tmp_path / "overlap").exists()
    rc = s.main(tmp_path, ask=lambda _: "yes", packages=lambda h: 2, fetcher=Boom())
    assert rc == 2


def test_setup_reports_failed_candidate_and_continues(tmp_path):
    s = _tool("setup_overlap")

    class F:
        def hf_snapshot_local(self, repo, dest):
            dest.mkdir(parents=True)
            for f in ("hyperparams.yaml", "encoder.ckpt", "decoder.ckpt", "masknet.ckpt"):
                (dest / f).write_text("x")

        def __getattr__(self, n):
            def fail(*a, **k):
                raise RuntimeError("offline")
            return fail
    rc = s.main(tmp_path, only=["wesep_bsrnn", "sepformer_libri3mix"], ask=lambda _: "yes",
                packages=lambda h: 0, fetcher=F())
    assert rc == 3
    from focus_ml.overlap import weights as W
    assert W.missing_files("sepformer_libri3mix", tmp_path) == []
    assert W.missing_files("wesep_bsrnn", tmp_path)
