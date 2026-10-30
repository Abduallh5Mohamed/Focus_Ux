"""Website side of WeSep: routing report to the job response, reference audio, worker ZIP.
Synthetic payloads and fake extractors only; no real model or GPU result."""
import base64
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from services.api.focus_api import inference, remote_inference, worker_kit
from services.api.focus_api.remote_inference import validate_enrollment, validate_routing

from test_bridge_audio import AUTH, KEY, remote, run, vp, wav_bytes  # noqa: F401

ROUTING = {
    "extractor_requested": "wesep_bsrnn", "extractor_ran": True, "overlap_extraction": "ran", "reason": None,
    "mode": "strict", "overlap_seconds": 4.0, "windows": 2, "pieces_extracted": 1, "pieces_muted": 1,
    "muted_seconds": 1.0, "fallback_used": False, "fallback_seconds": 0.0, "isolation_claim": "strict_isolation",
    "regions": [{"start_ms": 1000, "end_ms": 4000, "route": "wesep_bsrnn", "status": "extracted", "reason": "voiceprint_match"}],
}


def post_isolate(client, bridge, tmp, routing):
    pool, future, task = run(client, bridge, tmp, "isolate", {"voiceprint": vp(), "diarization": {}})
    url = f"/worker/tasks/{task['task_id']}"
    body = {"regions": [{"start_ms": 0, "end_ms": 900, "label": "target", "reason": "voice_match"}]}
    if routing is not None:
        body["routing"] = routing
    status = client.post(url + "/regions", headers=AUTH, json=body).status_code
    return pool, future, url, status


def test_routing_report_reaches_the_bridge_result(remote):
    _app, client, bridge, tmp = remote
    pool, future, url, status = post_isolate(client, bridge, tmp, ROUTING)
    assert status == 200
    headers = {**AUTH, "X-Focus-Engine": "audio_only", "Content-Type": "audio/wav"}
    assert client.post(url + "/audio", headers=headers, content=wav_bytes(12)).status_code == 200
    *_, routing = future.result(5)
    assert routing["extractor_ran"] is True and routing["pieces_extracted"] == 1
    assert routing["regions"][0]["status"] == "extracted"
    pool.shutdown()


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(isolation_claim="strict_isolation", fallback_used=True),   # fallback called isolation
    lambda r: r.update(overlap_extraction="maybe"),
    lambda r: r.update(pieces_extracted=-1),
    lambda r: r.update(regions=[{"start_ms": 0, "end_ms": 10 ** 9, "route": "x", "status": "x"}]),
    lambda r: r.update(regions=[{"start_ms": 0, "end_ms": 5, "route": "x", "status": "x"}] * 201),
])
def test_bad_routing_is_refused(remote, mutate):
    _app, client, bridge, tmp = remote
    bad = json.loads(json.dumps(ROUTING))
    mutate(bad)
    pool, future, url, status = post_isolate(client, bridge, tmp, bad)
    assert status == 400
    client.post(url.rsplit("/", 0)[0] + "/error", headers=AUTH, json={"code": "TIMEOUT"})
    pool.shutdown()


def test_reference_audio_is_checked_and_size_limited():
    ref = base64.b64encode(wav_bytes(5.0)).decode()
    ok = validate_enrollment({"voiceprint": vp(), "warnings": [], "reference_wav_b64": ref})
    assert ok["reference_wav_b64"] == ref
    assert "reference_wav_b64" not in validate_enrollment({"voiceprint": vp()})
    for bad in ("!!!", base64.b64encode(wav_bytes(12.0)).decode(), "A" * (remote_inference.MAX_REF_B64 + 1)):
        with pytest.raises(ValueError):
            validate_enrollment({"voiceprint": vp(), "reference_wav_b64": bad})


class FakeBridge:
    def __init__(self, routing):
        self.routing, self.payload = routing, None

    def call(self, **kw):
        self.payload = kw["payload"]
        return wav_bytes(12), 12_000, "audio_only", [
            {"start_ms": 0, "end_ms": 1000, "label": "target", "reason": "voice_match"}], self.routing


def provider(tmp_path, bridge, voiceprint):
    media = tmp_path / "media"
    media.mkdir()
    (media / "v.audio.wav").write_bytes(wav_bytes(12))
    video = SimpleNamespace(deleted=False, duration_ms=12_000, canonical_path=None, original_path=None)
    repo = SimpleNamespace(
        get_video=lambda _i: video,
        get_enrollment=lambda _i: {"status": "ready", "video_id": "v", "voiceprint": voiceprint},
        get_analysis=lambda _i: {"result": {"diarization": {"turns": []}}})
    p = inference.InferenceProviders(SimpleNamespace(media_dir=media, max_audio_s=180), repo, bridge=bridge)
    job = SimpleNamespace(enrollment_id="e", video_id="v")
    return p, job


def test_reference_travels_in_the_isolate_payload_and_routing_is_kept_with_the_job(tmp_path):
    ref = base64.b64encode(wav_bytes(5.0)).decode()
    bridge = FakeBridge(ROUTING)
    p, job = provider(tmp_path, bridge, dict(vp(), reference_wav_b64=ref))
    out = tmp_path / "job"
    out.mkdir()
    result = p.extract(job, str(out), lambda *a: None)
    assert bridge.payload["reference_wav_b64"] == ref
    assert "reference_wav_b64" not in bridge.payload["voiceprint"]
    stored = [w for w in result.warnings if w.startswith(inference.ROUTING_PREFIX)]
    assert json.loads(stored[0][len(inference.ROUTING_PREFIX):])["extractor_ran"] is True
    assert set(bridge.payload) == {"voiceprint", "diarization", "reference_wav_b64"}   # audio data only


def test_without_reference_or_routing_nothing_extra_is_sent(tmp_path):
    bridge = FakeBridge(None)
    p, job = provider(tmp_path, bridge, vp())
    out = tmp_path / "job"
    out.mkdir()
    result = p.extract(job, str(out), lambda *a: None)
    assert set(bridge.payload) == {"voiceprint", "diarization"}
    assert not any(w.startswith(inference.ROUTING_PREFIX) for w in result.warnings)


def test_worker_zip_is_complete_for_the_audio_only_worker():
    response = worker_kit.worker_kit()
    names = zipfile.ZipFile(io.BytesIO(response.body)).namelist()
    for needed in ("product/packages/ml/focus_ml/voice/engine.py",
                   "product/packages/ml/focus_ml/overlap/hybrid.py",
                   "product/packages/ml/focus_ml/overlap/preflight.py",
                   "product/tools/overlap_minimal_infer.py", "product/tools/overlap_e2e.py",
                   "Overlap-Validate.cmd"):
        assert needed in names, needed
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


def test_worker_zip_refuses_clearly_when_parts_are_missing(monkeypatch):
    monkeypatch.setattr(worker_kit, "REQUIRED_PACKAGE_DIRS", ("voice", "no_such_package"))
    response = worker_kit.worker_kit()
    assert response.status_code == 503
    assert b"full repo checkout" in response.body and b"no_such_package" in response.body


def test_worker_zip_includes_the_overlap_setup_path():
    names = zipfile.ZipFile(io.BytesIO(worker_kit.worker_kit().body)).namelist()
    for needed in ("Setup-Overlap.cmd", "product/tools/setup_overlap.py",
                   "product/tools/setup_clearervoice.py", "product/packages/ml/focus_ml/voice/weights.py",
                   "product/packages/ml/focus_ml/overlap/weights.py"):
        assert needed in names, needed
