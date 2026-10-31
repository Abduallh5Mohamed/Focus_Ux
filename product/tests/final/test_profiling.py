import json
import os
import time

import numpy as np
import pytest

from focus_ml.isolation_engines import write_wav
from focus_ml.voice import preprocess
from focus_ml.voice.profile import (
    ResidencyPolicy, ResourceMonitor, StageProfiler, classify_idle, plan_residency, supported_audio_seconds)
from helpers import make_engine


def test_stage_profiler_records_time_cpu_ram_and_gpu_with_injected_readers():
    mon = ResourceMonitor(0.01, rss=lambda: 123.0, gpu=lambda: {"util": 80.0, "used_mib": 900.0, "total_mib": 4096.0})
    with StageProfiler("cpu", mon) as _:
        pass
    mon.start()
    prof = StageProfiler("cpu", mon)
    with prof.stage("busy"):
        t = time.perf_counter()
        while time.perf_counter() - t < 0.1:
            sum(range(1000))
    mon.stop()
    s = prof.stages["busy"]
    assert s["seconds"] >= 0.09 and s["cpu_cores_busy"] > 0.5
    assert s["peak_ram_mib"] == 123.0 and s["gpu_util_mean_pct"] == 80.0 and s["gpu_mem_peak_mib"] == 900.0
    assert s["idle"] == "both_busy"
    d = prof.as_dict()
    assert d["peak_ram_mib"] == 123.0 and d["peak_vram_mib"] is None   # CPU run: no VRAM invented


def test_unavailable_readings_stay_none_not_zero():
    mon = ResourceMonitor(0.01, rss=lambda: None, gpu=lambda: None).start()
    prof = StageProfiler("cpu", mon)
    with prof.stage("x"):
        pass
    mon.stop()
    s = prof.stages["x"]
    assert s["peak_ram_mib"] is None and s["gpu_util_mean_pct"] is None
    assert s["idle"].endswith("gpu_unmeasured")


@pytest.mark.parametrize("cpu,gpu,expected", [
    (1.0, 5.0, "gpu_idle_waiting_for_cpu"), (0.1, 90.0, "cpu_idle_waiting_for_gpu"),
    (1.0, 90.0, "both_busy"), (0.1, 5.0, "both_idle"), (None, 5.0, "unknown")])
def test_classify_idle(cpu, gpu, expected):
    assert classify_idle(cpu, gpu) == expected


def test_residency_default_unloads_everything_and_policy_keeps_named_models():
    class M:
        unloaded = 0

        def unload(self):
            M.unloaded += 1
    m = M()
    assert ResidencyPolicy().release("embedder", m) is True
    assert ResidencyPolicy(("embedder",)).release("embedder", m) is False and M.unloaded == 1


def test_plan_residency_uses_only_measured_peaks():
    plan = plan_residency({"embedder": 600.0, "diarizer": 1500.0}, 4096.0, headroom_mib=1024.0)
    assert plan["keep"] == ["embedder", "diarizer"]
    tight = plan_residency({"embedder": 600.0, "diarizer": 2800.0}, 4096.0, headroom_mib=1024.0)
    assert tight["keep"] == ["embedder"] and "diarizer" in tight["unload"]
    unknown = plan_residency({"embedder": 600.0}, 4096.0)
    assert unknown["keep"] == ["embedder"] and "diarizer" in unknown["unload"]   # no measurement: never kept


def test_supported_length_is_only_what_was_measured():
    runs = [{"audio_seconds": 60, "real_time_factor": 0.3, "peak_vram_mib": 2000, "ok": True},
            {"audio_seconds": 180, "real_time_factor": 0.5, "peak_vram_mib": 2500, "ok": True},
            {"audio_seconds": 600, "real_time_factor": 1.4, "peak_vram_mib": 3000, "ok": True}]
    r = supported_audio_seconds(runs, 0.8, vram_budget_mib=3600)
    assert r["supported_audio_s"] == 180 and r["measured_lengths_s"] == [60, 180, 600]
    runs[2]["real_time_factor"] = 0.7
    assert supported_audio_seconds(runs, 0.8, 3600)["supported_audio_s"] == 600
    assert supported_audio_seconds(runs, 0.8, 2400)["supported_audio_s"] == 60      # VRAM budget stops at 180 s
    runs[0]["ok"] = False
    assert supported_audio_seconds(runs, 0.8)["supported_audio_s"] is None          # nothing measured to pass
    runs[0]["ok"] = True
    runs[1]["peak_vram_mib"] = None                                                 # missing reading fails a budget
    assert supported_audio_seconds(runs, 0.8, 3600)["supported_audio_s"] == 60


def test_decode_cache_reuses_decode_and_cannot_serve_changed_audio(tmp_path):
    p = tmp_path / "a.wav"
    write_wav(str(p), np.full(16000, 0.1, dtype=np.float32), 16000)
    preprocess.clear_decode_cache()
    n0 = preprocess.decode_count
    first = preprocess.load_canonical(str(p))
    again = preprocess.load_canonical(str(p))
    assert preprocess.decode_count == n0 + 1 and first is again and not first.flags.writeable
    st = os.stat(p)
    write_wav(str(p), np.full(16000, -0.1, dtype=np.float32), 16000)   # same size, new content
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))                    # same mtime too
    changed = preprocess.load_canonical(str(p))
    assert preprocess.decode_count == n0 + 2 and changed[100] < 0


def test_prefetch_matches_plain_loading_in_order(tmp_path):
    paths = []
    for i in range(3):
        p = tmp_path / f"{i}.wav"
        write_wav(str(p), np.full(8000, 0.05 * (i + 1), dtype=np.float32), 16000)
        paths.append(str(p))
    preprocess.clear_decode_cache()
    got = list(preprocess.prefetch_decoded(paths))
    assert [g[0] for g in got] == paths
    for path, samples in got:
        assert np.array_equal(samples, preprocess.load_canonical(path))
    assert list(preprocess.prefetch_decoded([])) == []


def test_profile_clips_reports_stages_rtf_and_decodes_once(tmp_path):
    import profile_pipeline
    from helpers import make_dataset
    ds = make_dataset(tmp_path / "ds", with_video=False)
    preprocess.clear_decode_cache()
    result = profile_pipeline.profile_clips(make_engine(), [str(ds / "clips/c1/mix.wav")])
    runs, r = result["runs"], result["runs"][0]
    assert r["ok"] and r["real_time_factor"] is not None and result["audio_decodes"] == 1
    assert {"decode", "diarize", "speaker_embeddings", "match", "extract"} <= set(r["stages"])
    limits = profile_pipeline.limits_from_runs(runs, {"gpu_name": None}, 0.8)
    assert limits["format"] == "focus-speed-limits/1" and limits["supported_audio_s"] is None
    assert limits["device"] == "cpu only" and limits["measured_on_target_laptop"] is False
    laptop = profile_pipeline.limits_from_runs(
        [dict(r, peak_vram_mib=2000.0) for r in runs], {"gpu_name": "NVIDIA GeForce RTX 3050", "gpu_total_vram_mib": 4096}, 0.8)
    assert laptop["supported_audio_s"] == 18.0 and laptop["measured_on_target_laptop"] is True
    long_clip = profile_pipeline.make_long(str(ds / "clips/c1/mix.wav"), 40.0, str(tmp_path / "long.wav"))
    assert long_clip["synthetic_repetition"] is True
    assert len(preprocess.load_canonical(str(tmp_path / "long.wav"))) == 40 * 16000


# -- regressions: supported length must come from every attempt and from wall-clock time ----------
LAPTOP = {"gpu_name": "NVIDIA GeForce RTX 3050 Laptop GPU", "gpu_total_vram_mib": 4096}


def _clips(tmp_path):
    from fakes import SR
    from helpers import make_dataset
    ds = make_dataset(tmp_path / "ds", with_video=False)
    mix = preprocess.load_canonical(str(ds / "clips/c1/mix.wav"))
    short = tmp_path / "short_fail.wav"
    write_wav(str(short), np.array(mix[: 6 * SR]), 16000)
    return str(short), str(ds / "clips/c1/mix.wav")


def _with_vram(runs, mib=2000.0):
    return [dict(r, peak_vram_mib=mib) for r in runs]


def test_failed_short_clip_ends_the_range_even_when_a_longer_clip_succeeds(tmp_path):
    import profile_pipeline
    short, long_ = _clips(tmp_path)
    engine = make_engine()
    real = engine.analyze

    def flaky(path, *a, **k):
        if "short_fail" in str(path):
            raise RuntimeError("out of memory")
        return real(path, *a, **k)
    engine.analyze = flaky
    preprocess.clear_decode_cache()
    runs = profile_pipeline.profile_clips(engine, [short, long_])["runs"]
    assert runs[0]["ok"] is False and runs[0]["audio_seconds"] == pytest.approx(6.0)   # length kept
    assert runs[1]["ok"] is True
    limits = profile_pipeline.limits_from_runs(_with_vram(runs), LAPTOP, 0.8)
    assert limits["supported_audio_s"] is None            # 18 s must not pass because 6 s failed


def test_a_failure_in_the_middle_keeps_only_the_shorter_lengths():
    import profile_pipeline
    good = {"real_time_factor": 0.3, "peak_vram_mib": 2000.0, "wall_seconds": 1.0, "peak_ram_mib": 500.0}
    runs = [dict(good, audio_seconds=60.0, ok=True),
            dict(good, audio_seconds=180.0, ok=False, real_time_factor=None),
            dict(good, audio_seconds=600.0, ok=True)]
    assert profile_pipeline.limits_from_runs(runs, LAPTOP, 0.8)["supported_audio_s"] == 60.0


def test_unknown_length_or_no_runs_cannot_make_a_valid_limits_file(tmp_path):
    import profile_pipeline
    from services.api.focus_api.config import load_speed_limit
    good = {"real_time_factor": 0.3, "peak_vram_mib": 2000.0, "wall_seconds": 1.0, "peak_ram_mib": 500.0, "ok": True}
    for runs in ([], [dict(good, audio_seconds=None), dict(good, audio_seconds=60.0)]):
        limits = profile_pipeline.limits_from_runs(runs, LAPTOP, 0.8)
        assert limits["supported_audio_s"] is None and limits["not_installable_reason"]
        path = tmp_path / "l.json"
        path.write_text(json.dumps(limits))
        with pytest.raises(ValueError):
            load_speed_limit(str(path))     # the API keeps its 180 s default instead


def test_real_time_factor_is_end_to_end_wall_time_not_the_sum_of_stages(tmp_path):
    import profile_pipeline
    short, long_ = _clips(tmp_path)
    engine = make_engine()
    real = engine.isolate

    def slow_isolate(*a, **k):
        time.sleep(0.6)                 # work outside every instrumented stage
        return real(*a, **k)
    engine.isolate = slow_isolate
    preprocess.clear_decode_cache()
    r = profile_pipeline.profile_clips(engine, [long_])["runs"][0]
    assert r["wall_seconds"] >= 0.6
    assert r["stage_sum_seconds"] < r["wall_seconds"] - 0.5      # the sum misses the sleep
    assert r["real_time_factor"] == pytest.approx(r["wall_seconds"] / r["audio_seconds"], abs=0.002)
    assert r["real_time_factor"] > r["stage_sum_seconds"] / r["audio_seconds"]
    # and that slower wall-clock RTF is what decides the limit
    assert profile_pipeline.limits_from_runs([dict(r, peak_vram_mib=2000.0)], LAPTOP, rtf_target=0.02)["supported_audio_s"] is None


def test_laptop_limit_still_needs_target_device_and_default_stays_180s(monkeypatch):
    import profile_pipeline
    from services.api.focus_api.config import DEFAULT_MAX_VIDEO_MS, Settings
    run = {"audio_seconds": 60.0, "real_time_factor": 0.3, "peak_vram_mib": 2000.0, "ok": True}
    assert profile_pipeline.limits_from_runs([run], {"gpu_name": "NVIDIA A100", "gpu_total_vram_mib": 40000}, 0.8)["supported_audio_s"] is None
    monkeypatch.delenv("FOCUS_API_SPEED_LIMITS", raising=False)
    monkeypatch.delenv("FOCUS_API_MAX_VIDEO_MS", raising=False)
    assert DEFAULT_MAX_VIDEO_MS == 180_000 and Settings.from_env().max_video_ms == 180_000
