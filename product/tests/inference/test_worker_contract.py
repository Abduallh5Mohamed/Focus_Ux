"""Worker/backend contract and disconnect handling. Synthetic payloads only (no real worker or GPU)."""
import tempfile
import time
from pathlib import Path

import pytest

from focus_ml.code_version import ISOLATE_CONTRACT, code_version
from services.api.focus_api.interfaces import ProviderError
from services.api.focus_api.remote_inference import validate_routing

from test_bridge_audio import AUTH, remote, run, vp  # noqa: F401
from test_wesep_website import ROUTING


def test_check_endpoint_reports_the_backend_code_version(remote):
    _app, client, _bridge, _tmp = remote
    body = client.get("/worker/check", headers=AUTH).json()
    assert body["code_version"] == code_version() and body["isolate_contract"] == ISOLATE_CONTRACT


def test_code_version_ignores_line_endings_and_changes_with_content(tmp_path):
    (tmp_path / "voice").mkdir(); (tmp_path / "overlap").mkdir()
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    one = code_version(tmp_path)
    (tmp_path / "a.py").write_bytes(b"x = 1\r\n")
    assert code_version(tmp_path) == one
    (tmp_path / "a.py").write_bytes(b"x = 2\n")
    assert code_version(tmp_path) != one


def test_routing_with_new_fields_is_kept_and_checked():
    ok = validate_routing({**ROUTING, "mode": "continuity", "fallback_used": True, "fallback_seconds": 1.0,
                           "isolation_claim": "not_isolation", "route_labels": ["continuity_fallback"],
                           "target_may_be_lost": False, "notices": ["Continuity mode: not isolation"]}, 12_000)
    assert ok["route_labels"] == ["continuity_fallback"] and ok["isolation_claim"] == "not_isolation"
    assert ok["notices"] == ["Continuity mode: not isolation"]


@pytest.mark.parametrize("bad", [
    {"route_labels": ["continuity_fallback"]},                        # continuity claimed as isolation
    {"route_labels": ["made_up"]},
    {"mode": "loose"},
    {"overlap_extraction": "failed", "extractor_ran": False, "reason": "x", "route_labels": ["genuine_extraction"]},
])
def test_routing_that_misreports_what_ran_is_refused(bad):
    with pytest.raises(ValueError):
        validate_routing({**ROUTING, **bad}, 12_000)


def test_a_worker_that_goes_silent_mid_task_gives_a_clear_error(remote):
    _app, client, bridge, tmp = remote
    bridge.silent_after_s = 0.4
    pool, future, _task = run(client, bridge, tmp, "isolate", {"voiceprint": vp(), "diarization": {}})
    with pytest.raises(ProviderError, match="stopped responding"):
        future.result(timeout=5)
    pool.shutdown()


def test_a_worker_that_never_takes_the_task_gives_a_clear_error(remote):
    _app, client, bridge, tmp = remote
    bridge.offline_after_s = 0.3
    source = tmp / "t.wav"
    source.write_bytes(b"\x00" * 100)
    start = time.monotonic()
    with pytest.raises(ProviderError, match="went offline"):
        bridge.call(kind="isolate", video_id="v", video_path=str(source),
                    payload={"voiceprint": vp(), "diarization": {}}, timeout_s=10)
    assert time.monotonic() - start < 5
