import numpy as np
import pytest

from focus_ml.config import AdapterConfig
from focus_ml.fast_landmarks import MESH_TO_68, mesh_to_68
from focus_ml.windows import (
    merge_windows, normalize_input, normalize_output, plan_windows,
)

SR = 16000


def test_defaults_are_four_seconds_half_overlap():
    cfg = AdapterConfig()
    assert (cfg.window_s, cfg.window_overlap, cfg.merge) == (4.0, 0.5, "crossfade")
    cfg = AdapterConfig.from_env({"FOCUS_WINDOW_S": "3", "FOCUS_LANDMARKS": "mediapipe"})
    assert cfg.window_s == 3.0 and cfg.landmark_backend == "mediapipe"
    with pytest.raises(ValueError):
        AdapterConfig(window_overlap=1.0)


def test_plan_covers_clip_and_last_window_is_full():
    n = int(15.3 * SR)
    spans = plan_windows(n, SR, 4.0, 0.5)
    assert spans[0] == (0, 4 * SR) and spans[-1][1] == n
    assert all(e - s == 4 * SR for s, e in spans)
    for (s1, e1), (s2, _) in zip(spans, spans[1:]):
        assert s2 <= e1 and s2 > s1


def test_plan_short_clip_and_zero_overlap():
    assert plan_windows(SR, SR, 4.0) == [(0, SR)]
    assert plan_windows(0, SR, 4.0) == []
    assert plan_windows(8 * SR, SR, 4.0, 0.0) == [(0, 4 * SR), (4 * SR, 8 * SR)]


def test_merge_of_consistent_estimates_is_identity():
    n = int(9.7 * SR)
    signal = np.random.default_rng(0).standard_normal(n).astype(np.float32)
    spans = plan_windows(n, SR, 4.0, 0.5)
    merged = merge_windows([signal[s:e] for s, e in spans], spans, n)
    assert np.allclose(merged, signal, atol=1e-5)


def test_merge_has_no_seam_jump_between_different_windows():
    n = 12 * SR
    spans = plan_windows(n, SR, 4.0, 0.5)
    merged = merge_windows([np.full(e - s, 1.0 + i * 0.1) for i, (s, e) in enumerate(spans)], spans, n)
    assert np.max(np.abs(np.diff(merged))) < 1e-3


def test_normalize_levels_and_never_clips():
    quiet = (0.01 * np.sin(np.arange(SR) / 10)).astype(np.float32)
    boosted, gain = normalize_input(quiet)
    assert gain > 0 and np.sqrt(np.mean(boosted ** 2)) > 0.05
    peaky = np.zeros(SR, np.float32)
    peaky[10] = 0.9
    peaky[:2000] += 0.001
    out, _ = normalize_output(peaky)
    assert np.max(np.abs(out)) <= 0.97 + 1e-6
    silent = np.zeros(100, np.float32)
    assert normalize_input(silent)[1] == 0.0 and normalize_output(silent)[1] == 0.0


def test_mesh_to_68_picks_anchor_and_mouth_points():
    mesh = np.zeros((478, 2))
    mesh[:, 0] = np.arange(478) / 1000.0
    mesh[:, 1] = 0.5
    pts = mesh_to_68(mesh, 224, 100)
    assert pts.shape == (68, 2)
    for dlib_idx, mp_idx in ((33, 2), (36, 33), (39, 133), (42, 362), (45, 263), (48, 61), (54, 291)):
        assert MESH_TO_68[dlib_idx] == mp_idx
        assert pts[dlib_idx, 0] == pytest.approx(mp_idx / 1000.0 * 224)
        assert pts[dlib_idx, 1] == pytest.approx(50)
    with pytest.raises(ValueError):
        mesh_to_68(np.zeros((10, 2)), 1, 1)


def test_compare_tool_si_sdr_and_settings():
    import importlib.util, os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "compare_isolation.py")
    spec = importlib.util.spec_from_file_location("compare_isolation", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rng = np.random.default_rng(1)
    ref = rng.standard_normal(SR)
    assert mod.si_sdr(ref * 0.5, ref) > 60
    assert mod.si_sdr(rng.standard_normal(SR), ref) < 5
    s = mod.settings(AdapterConfig(), "m.task")
    assert list(s) == ["old_2s", "overlap_4s", "overlap_4s_fast_lm"]
    assert s["old_2s"].window_s == 2.0 and s["overlap_4s_fast_lm"].landmark_backend == "mediapipe"


def test_direct_mode_matches_legacy_spans_and_audio():
    n = int(7.3 * SR)
    spans = plan_windows(n, SR, 2.0, 0.0)
    legacy, start = [], 0
    while start < n:
        legacy.append((start, min(start + 2 * SR, n)))
        start += 2 * SR
    assert spans == legacy and spans[-1][1] - spans[-1][0] < 2 * SR
    signal = np.random.default_rng(2).standard_normal(n).astype(np.float32)
    merged = merge_windows([signal[s:e] for s, e in spans], spans, n)
    assert np.array_equal(merged, signal)
