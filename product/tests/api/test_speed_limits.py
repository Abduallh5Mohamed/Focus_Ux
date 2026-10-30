import json

import pytest

from services.api.focus_api.config import DEFAULT_MAX_VIDEO_MS, Settings, load_speed_limit


def write(path, **over):
    data = {"format": "focus-speed-limits/1", "measured_on_target_laptop": True, "supported_audio_s": 420, "device": "NVIDIA RTX 3050 Laptop GPU",
            "measured_at": "2026-11-02", **over}
    path.write_text(json.dumps(data))
    return str(path)


def test_measured_limit_is_loaded_with_its_provenance(tmp_path):
    ms, source = load_speed_limit(write(tmp_path / "l.json"))
    assert ms == 420_000 and "RTX 3050" in source and "2026-11-02" in source


@pytest.mark.parametrize("bad", [{"supported_audio_s": None}, {"supported_audio_s": 0}, {"format": "other"}, {"measured_on_target_laptop": False}, {"device": "cpu only"}])
def test_unmeasured_or_wrong_file_fails_at_startup(tmp_path, bad):
    with pytest.raises(ValueError, match="FOCUS_API_SPEED_LIMITS"):
        load_speed_limit(write(tmp_path / "l.json", **bad))


def test_missing_file_fails_instead_of_falling_back(tmp_path):
    with pytest.raises(ValueError, match="FOCUS_API_SPEED_LIMITS"):
        load_speed_limit(str(tmp_path / "nope.json"))


def test_settings_default_names_the_limit_as_unmeasured(monkeypatch):
    monkeypatch.delenv("FOCUS_API_SPEED_LIMITS", raising=False)
    monkeypatch.delenv("FOCUS_API_MAX_VIDEO_MS", raising=False)
    s = Settings.from_env()
    assert s.max_video_ms == DEFAULT_MAX_VIDEO_MS and "not been measured" in s.limit_source


def test_settings_use_measured_file_and_operator_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FOCUS_API_SPEED_LIMITS", write(tmp_path / "l.json"))
    monkeypatch.delenv("FOCUS_API_MAX_VIDEO_MS", raising=False)
    assert Settings.from_env().max_video_ms == 420_000
    monkeypatch.setenv("FOCUS_API_MAX_VIDEO_MS", "100000")
    s = Settings.from_env()
    assert s.max_video_ms == 100_000 and "operator" in s.limit_source


def test_refusal_message_states_the_limit_and_where_it_came_from(make_api, make_settings_for):
    from .fixtures_media import make_mp4_bytes
    api = make_api(settings=make_settings_for(max_video_ms=1000, limit_source="a measured test limit"))
    body = api.upload(make_mp4_bytes(duration_ms=1001)).json()
    assert "1s limit (a measured test limit)" in json.dumps(body)
