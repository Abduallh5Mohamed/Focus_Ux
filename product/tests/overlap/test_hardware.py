"""GPU detection and sizing with injected probes. Not GPU evidence: no GPU, model or speed is involved."""
import pytest
from types import SimpleNamespace

from focus_ml import hardware
from focus_ml.overlap.base import CandidateInfo

INFO = CandidateInfo(name="x", title="x", mechanism="target_conditioned", code_licence="", weights_licence="",
                     model_rate=8000, vram_base_mib=500, vram_per_window_s_mib=70)


def probes(free, total=None, name="Any NVIDIA GPU", cuda=True, driver=True):
    total = total or free
    pr = {"torch": {"version": "2", "cuda_build": "12.1" if cuda else None, "cuda_available": cuda}}
    if cuda:
        pr["gpu"] = {"name": name, "capability": [8, 0], "total_mib": total, "free_mib": free}
    if driver:
        pr["driver"] = {"name": name, "driver": "550.1", "total_mib": total, "free_mib": free}
    return pr


def test_detect_usable_and_blockers():
    d = hardware.detect(probes(6000, 8000, "GPU-A"))
    assert d["usable"] and d["device"] == "GPU-A" and d["vram_free_mib"] == 6000 and d["driver"] == "550.1"
    cpu = hardware.detect(probes(0, cuda=False))
    assert not cpu["usable"] and any("CPU-only" in b for b in cpu["blockers"])
    none = hardware.detect({"torch": None})
    assert not none["usable"] and len(none["blockers"]) == 2


def test_plan_scales_with_free_vram_and_never_exceeds_it():
    small = hardware.plan_for(INFO, 2000)
    mid = hardware.plan_for(INFO, 3500)
    big = hardware.plan_for(INFO, 24000)
    assert big.window_s == 4.0 and big.batch_size > mid.batch_size >= small.batch_size >= 1
    assert big.batch_size <= hardware.MAX_BATCH
    for p in (small, mid, big):
        assert p.fits
        assert INFO.vram_base_mib + INFO.vram_per_window_s_mib * p.window_s * p.batch_size <= p.vram_budget_mib or p.batch_size == 1


def test_plan_reports_when_nothing_fits():
    p = hardware.plan_for(INFO, 900)
    assert not p.fits and p.window_s == 2.0 and p.batch_size == 1 and p.notes
    assert hardware.required_free_mib(INFO) > 900


def test_overrides_come_from_gpu_then_settings():
    det = hardware.detect(probes(8000))
    kw = hardware.hybrid_overrides(INFO, env={}, detection=det)
    assert kw["vram_budget_mib"] == 8000 - hardware.RESERVE_MIB and kw["plan"]["source"] == "detected"
    kw = hardware.hybrid_overrides(INFO, env={"FOCUS_OVERLAP_WINDOW_S": "2", "FOCUS_OVERLAP_BATCH_SIZE": "3"}, detection=det)
    assert kw["window_s"] == 2.0 and kw["batch_size"] == 3 and kw["plan"]["source"] == "settings"
    no_gpu = hardware.detect(probes(0, cuda=False))
    assert hardware.hybrid_overrides(INFO, env={}, detection=no_gpu) == {}
    with pytest.raises(ValueError):
        hardware.hybrid_overrides(INFO, env={"FOCUS_OVERLAP_WINDOW_S": "abc"}, detection=no_gpu)
    with pytest.raises(ValueError):
        hardware.hybrid_overrides(INFO, env={"FOCUS_OVERLAP_BATCH_SIZE": "0"}, detection=no_gpu)


def test_engine_keeps_defaults_off_cuda(monkeypatch):
    from focus_ml.overlap.hybrid import HybridConfig
    from focus_ml.voice.engine import AudioOnlyEngine
    from fakes import FakeDiarizer, FakeEmbedder
    from helpers import ToneExtractor
    ext = ToneExtractor()
    e = AudioOnlyEngine(FakeDiarizer([]), FakeEmbedder(), overlap_extractor=ext)
    assert e._hybrid_config() == HybridConfig()
    ext.device = "cuda"
    det = hardware.detect(probes(7000))
    monkeypatch.setattr(hardware, "detect", lambda *a, **k: det)
    cfg = e._hybrid_config()
    assert cfg.vram_budget_mib == 7000 - hardware.RESERVE_MIB and cfg.plan["source"] == "detected"


def test_preflight_uses_model_size_not_a_gpu_name():
    from focus_ml.overlap.preflight import run_preflight
    r = run_preflight("wesep_bsrnn", probes=probes(2000, 2048, "Some Small GPU"), ready=lambda: None, has_module=lambda m: True)
    assert r["ok"]
    r = run_preflight("wesep_bsrnn", probes=probes(1000, 2048, "Some Small GPU"), ready=lambda: None, has_module=lambda m: True)
    assert not r["ok"]
