"""Audio-only flow through the real API, dispatcher, repository and worker.
Only the model-backed provider and runner are test doubles (tests/api rule)."""
from __future__ import annotations

import io
import wave

import pytest

from services.api.focus_api.interfaces import ProviderError

from .fakes import FakeAudioOnlyRunner, FakeAudioProvider, FakeTranscriber, make_wav_bytes
from .harness import make_settings


@pytest.fixture
def audio_api(make_api, tmp_path):
    def build(provider=None, runner=None, transcriber=None, **settings):
        settings.setdefault("isolation_engine", "audio_only")
        provider = provider or FakeAudioProvider()
        api = make_api(provider=provider, runner=runner or FakeAudioOnlyRunner(),
                       transcriber=transcriber, settings=make_settings(tmp_path / "audio", **settings))
        from .fixtures_media import make_mp4_bytes
        video_id, token, _ = api.upload_ok(data=make_mp4_bytes(duration_ms=12_000))
        api.drain()
        faces = api.get_faces(video_id, token).json()["faces"]
        return api, provider, video_id, token, faces[0]["face_id"]
    return build


def _get(api, path, token):
    return api.client.get(path, headers=api.auth(token))


def _post(api, path, token, **kwargs):
    return api.client.post(path, headers=api.auth(token), **kwargs)


def test_defaults_are_three_minutes_and_audio_only():
    from services.api.focus_api.config import Settings
    s = Settings(storage_root="/tmp/x-focus")
    assert (s.isolation_engine, s.max_video_ms) == ("audio_only", 180_000)
    assert s.max_audio_bytes > 180 * 32000


def test_config_reports_engine_and_limits(audio_api):
    api, *_ = audio_api()
    body = api.client.get("/config").json()
    assert body["engine"] == "audio_only" and body["max_video_ms"] == 180_000


def test_analysis_runs_beside_faces_is_cached_and_hides_voiceprints(audio_api):
    api, provider, video_id, token, _face = audio_api()
    response = _get(api, f"/videos/{video_id}/analysis", token)
    body = response.json()
    assert body["status"] == "ready" and [v["voice_id"] for v in body["voices"]] == ["voice-0", "voice-1", "voice-2"]
    assert "vector" not in response.text and "voiceprint" not in response.text
    assert body["voices"][2]["usable"] is False and body["voices"][2]["refusal"]
    assert provider.calls_analyze == 1
    sample = _get(api, body["voices"][0]["sample_url"].replace("/api", ""), token)
    assert sample.status_code == 200 and sample.content[:4] == b"RIFF"
    assert api.client.get(f"/videos/{video_id}/analysis").status_code == 401


def test_analysis_failure_is_reported_and_retryable(make_api, tmp_path):
    class Flaky(FakeAudioProvider):
        def analyze(self, **kwargs):
            if not self.calls_analyze:
                self.calls_analyze += 1
                raise ProviderError("the inference computer is offline", retryable=True)
            return super().analyze(**kwargs)
    api = make_api(provider=Flaky(), runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "f", isolation_engine="audio_only"))
    video_id, token, _ = api.upload_ok()
    api.drain()
    body = _get(api, f"/videos/{video_id}/analysis", token).json()
    assert body["status"] == "failed" and body["error"]["retryable"] is True
    _post(api, f"/videos/{video_id}/analysis/retry", token)
    api.drain()
    assert _get(api, f"/videos/{video_id}/analysis", token).json()["status"] == "ready"


def test_suggestion_ranks_the_voice_heard_while_the_face_is_visible(audio_api):
    api, _p, video_id, token, face = audio_api()
    assert _post(api, f"/videos/{video_id}/voice-suggestions", token, json={"face_id": face}).status_code == 202
    assert _get(api, f"/videos/{video_id}/voice-suggestions/{face}", token).json()["status"] == "pending"
    api.drain()
    body = _get(api, f"/videos/{video_id}/voice-suggestions/{face}", token).json()
    assert body["status"] == "ready" and body["evidence"] == "on_screen"
    assert body["candidates"][0]["voice_id"] == "voice-1" and body["candidates"][0]["suggested"] is True
    assert [c["suggested"] for c in body["candidates"]].count(True) == 1
    assert "اقتراح" in body["note"]


def test_suggestion_without_screen_evidence_is_honest(make_api, tmp_path):
    provider = FakeAudioProvider(visibility_error=ProviderError("face tracking failed"))
    api = make_api(provider=provider, runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "n", isolation_engine="audio_only"))
    video_id, token, _ = api.upload_ok()
    api.drain()
    face = api.get_faces(video_id, token).json()["faces"][0]["face_id"]
    _post(api, f"/videos/{video_id}/voice-suggestions", token, json={"face_id": face})
    api.drain()
    body = _get(api, f"/videos/{video_id}/voice-suggestions/{face}", token).json()
    assert body["evidence"] == "talk_time_only" and not any(c["suggested"] for c in body["candidates"])
    assert body["notice"]


def test_weak_evidence_gives_no_suggestion(make_api, tmp_path):
    provider = FakeAudioProvider(visible=[{"start_ms": 0, "end_ms": 700}])
    api = make_api(provider=provider, runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "w", isolation_engine="audio_only"))
    video_id, token, _ = api.upload_ok()
    api.drain()
    face = api.get_faces(video_id, token).json()["faces"][0]["face_id"]
    _post(api, f"/videos/{video_id}/voice-suggestions", token, json={"face_id": face})
    api.drain()
    body = _get(api, f"/videos/{video_id}/voice-suggestions/{face}", token).json()
    assert body["evidence"] == "on_screen" and not any(c["suggested"] for c in body["candidates"])


def test_enroll_from_detected_voice_and_refuse_short_one(audio_api):
    api, _p, video_id, token, face = audio_api()
    ok = _post(api, f"/videos/{video_id}/enrollments", token,
               json={"face_id": face, "source": "voice", "voice_id": "voice-1"})
    assert ok.status_code == 202 and ok.json()["status"] == "ready"
    assert "vector" not in ok.text
    short = _post(api, f"/videos/{video_id}/enrollments", token,
                  json={"face_id": face, "source": "voice", "voice_id": "voice-2"})
    assert short.status_code == 422 and short.json()["error"]["code"] == "ENROLLMENT_REFUSED"
    missing = _post(api, f"/videos/{video_id}/enrollments", token,
                    json={"face_id": face, "source": "voice", "voice_id": "voice-9"})
    assert missing.status_code == 404


def test_enroll_manual_range_validation_and_worker_result(audio_api):
    api, provider, video_id, token, face = audio_api()
    base = {"face_id": face, "source": "range"}
    for bad in ({"start_ms": 0, "end_ms": 1500}, ):
        r = _post(api, f"/videos/{video_id}/enrollments", token, json={**base, **bad})
        assert r.status_code == 422 and r.json()["error"]["code"] == "ENROLLMENT_REFUSED"
    for bad in ({"start_ms": 5000, "end_ms": 4000}, {"start_ms": -1, "end_ms": 6000},
                {"start_ms": 0, "end_ms": 99_000}, {"start_ms": 0}):
        r = _post(api, f"/videos/{video_id}/enrollments", token, json={**base, **bad})
        assert r.status_code == 422, bad
    r = _post(api, f"/videos/{video_id}/enrollments", token, json={**base, "start_ms": 5000, "end_ms": 11000})
    eid = r.json()["enrollment_id"]
    assert r.json()["status"] == "pending"
    api.drain()
    done = _get(api, f"/videos/{video_id}/enrollments/{eid}", token).json()
    assert done["status"] == "ready" and done["warnings"] == ["short sample"]
    assert provider.enroll_calls == [{"mode": "range", "start_ms": 5000, "end_ms": 11000}]


def test_worker_refusal_is_surfaced(make_api, tmp_path):
    provider = FakeAudioProvider(refuse="30% of the speech in this sample comes from other voices.")
    api = make_api(provider=provider, runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "r", isolation_engine="audio_only"))
    from .fixtures_media import make_mp4_bytes
    video_id, token, _ = api.upload_ok(data=make_mp4_bytes(duration_ms=12_000))
    api.drain()
    face = api.get_faces(video_id, token).json()["faces"][0]["face_id"]
    r = _post(api, f"/videos/{video_id}/enrollments", token,
              json={"face_id": face, "source": "range", "start_ms": 0, "end_ms": 8000})
    api.drain()
    body = _get(api, f"/videos/{video_id}/enrollments/{r.json()['enrollment_id']}", token).json()
    assert body["status"] == "failed" and body["error"]["code"] == "ENROLLMENT_REFUSED"
    assert "other voices" in body["error"]["message"]


def _wav(seconds):
    return make_wav_bytes(int(seconds * 1000))


def test_voice_file_upload_enrolls_and_is_not_kept(audio_api):
    api, provider, video_id, token, face = audio_api()
    r = api.client.post(f"/videos/{video_id}/enrollments/upload", headers=api.auth(token),
                        data={"face_id": face}, files={"file": ("me.wav", _wav(6), "audio/wav")})
    assert r.status_code == 202, r.text
    api.drain()
    assert _get(api, f"/videos/{video_id}/enrollments/{r.json()['enrollment_id']}", token).json()["status"] == "ready"
    assert provider.enroll_calls == [{"mode": "file", "existed": True}]
    assert not list(api.settings.media_dir.glob(f"{video_id}.voice-*"))


def test_voice_file_too_short_or_not_audio_is_refused(audio_api):
    api, provider, video_id, token, face = audio_api()
    short = api.client.post(f"/videos/{video_id}/enrollments/upload", headers=api.auth(token),
                            data={"face_id": face}, files={"file": ("me.wav", _wav(1.5), "audio/wav")})
    assert short.status_code == 422 and short.json()["error"]["code"] == "ENROLLMENT_REFUSED"
    junk = api.client.post(f"/videos/{video_id}/enrollments/upload", headers=api.auth(token),
                           data={"face_id": face}, files={"file": ("me.wav", b"not audio at all", "audio/wav")})
    assert junk.status_code == 400
    assert provider.enroll_calls == [] and not list(api.settings.media_dir.glob(f"{video_id}.voice-*"))


def test_enrollment_belongs_to_its_session(audio_api):
    api, _p, video_id, token, face = audio_api()
    eid = _post(api, f"/videos/{video_id}/enrollments", token,
                json={"face_id": face, "source": "voice", "voice_id": "voice-0"}).json()["enrollment_id"]
    other, other_token, _ = api.upload_ok()
    assert _get(api, f"/videos/{video_id}/enrollments/{eid}", other_token).status_code == 404
    assert _get(api, f"/videos/{other}/enrollments/{eid}", other_token).status_code == 404


def test_job_requires_enrollment_and_carries_it_not_a_face(audio_api):
    runner = FakeAudioOnlyRunner()
    transcriber = FakeTranscriber()
    api, _p, video_id, token, face = audio_api(runner=runner, transcriber=transcriber)
    no = _post(api, "/jobs", token, json={"video_id": video_id, "client_request_id": "a"})
    assert no.status_code == 409 and no.json()["error"]["code"] == "ENROLLMENT_REQUIRED"
    pending = _post(api, f"/videos/{video_id}/enrollments", token,
                    json={"face_id": face, "source": "range", "start_ms": 0, "end_ms": 6000}).json()
    early = _post(api, "/jobs", token, json={"video_id": video_id, "enrollment_id": pending["enrollment_id"],
                                             "client_request_id": "b"})
    assert early.status_code == 409
    api.drain()
    eid = pending["enrollment_id"]
    job = _post(api, "/jobs", token, json={"video_id": video_id, "enrollment_id": eid, "client_request_id": "c"})
    assert job.status_code == 202
    again = _post(api, "/jobs", token, json={"video_id": video_id, "enrollment_id": eid, "client_request_id": "c"})
    assert again.json() == job.json()
    api.drain()
    state = api.get_job(job.json()["job_id"], token).json()
    assert state["status"] == "completed" and state["transcript_enabled"] is False
    assert state["transcript_status"] == "pending" and transcriber.calls == []
    periods = state["result"]["follow_periods"]
    assert [(p["state"], p["output_allowed"]) for p in periods] == [("voice_follow", True), ("uncertain", False)]
    assert runner.calls[0]["video_id"] == video_id
    assert api.repo.find_job(job.json()["job_id"]).enrollment_id == eid
    assert api.get_audio(job.json()["job_id"], token).status_code == 200


def test_lip_engine_still_needs_a_face_and_keeps_its_15s_limit(make_api, tmp_path):
    from .fixtures_media import make_mp4_bytes
    api = make_api(provider=FakeAudioProvider(), runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "lip"))
    video_id, token, _ = api.upload_ok(data=make_mp4_bytes(duration_ms=20_000))
    api.drain()
    face = api.get_faces(video_id, token).json()["faces"][0]["face_id"]
    assert _get(api, f"/videos/{video_id}/analysis", token).json()["status"] == "failed"
    long = api.create_job(video_id, face, "x", token)
    assert long.status_code == 413 and long.json()["error"]["code"] == "LIMIT_EXCEEDED"
    short_id, short_token, _ = api.upload_ok()
    api.drain()
    missing = _post(api, "/jobs", short_token, json={"video_id": short_id, "client_request_id": "y"})
    assert missing.status_code == 422


def test_three_minute_clip_is_accepted(make_api, tmp_path):
    from .fixtures_media import make_mp4_bytes
    api = make_api(provider=FakeAudioProvider(), runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "long", isolation_engine="audio_only"))
    assert api.upload(make_mp4_bytes(duration_ms=179_000)).status_code == 201
    assert api.upload(make_mp4_bytes(duration_ms=181_000)).status_code == 413


def test_deleting_the_video_deletes_voiceprints_and_samples(audio_api):
    api, _p, video_id, token, face = audio_api()
    _post(api, f"/videos/{video_id}/enrollments", token,
          json={"face_id": face, "source": "voice", "voice_id": "voice-0"})
    _post(api, f"/videos/{video_id}/voice-suggestions", token, json={"face_id": face})
    api.drain()
    assert api.repo.voice_row_counts(video_id) == {"enrollments": 1, "suggestions": 1, "analyses": 1}
    assert list(api.settings.media_dir.glob(f"{video_id}.sample*.wav"))
    assert api.client.delete(f"/videos/{video_id}", headers=api.auth(token)).status_code == 202
    # Gone at once, before the file cleanup runs.
    assert api.repo.voice_row_counts(video_id) == {"enrollments": 0, "suggestions": 0, "analyses": 0}
    api.drain()
    assert not list(api.settings.media_dir.glob(f"{video_id}.*"))
    assert _get(api, f"/videos/{video_id}/analysis", token).status_code == 404


def test_late_results_do_not_revive_deleted_voice_data(audio_api):
    api, _p, video_id, token, _face = audio_api()
    api.repo.mark_video_deleted(video_id)
    assert api.repo.set_analysis(video_id, "ready", result={"x": 1}) is False
    assert api.repo.create_enrollment("e1", video_id, "f", "voice", {}) is False
    assert api.repo.voice_row_counts(video_id)["analyses"] == 0


def test_old_database_gains_job_columns(tmp_path):
    import sqlite3
    from services.api.focus_api.db import SqliteRepository
    path = tmp_path / "old.db"
    SqliteRepository(path).close()
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE jobs DROP COLUMN enrollment_id")
    conn.execute("ALTER TABLE jobs DROP COLUMN follow_periods")
    conn.commit(); conn.close()
    repo = SqliteRepository(path)
    assert repo.count_jobs() == 0
    cols = {r[1] for r in repo._conn.execute("PRAGMA table_info(jobs)")}
    assert {"enrollment_id", "follow_periods"} <= cols
    repo.close()


def test_audio_only_keeps_one_placeholder_when_face_detection_fails(make_api, tmp_path):
    """No lip models on the machine must not dead-end the picker.

    The audio-only engine identifies the speaker by voiceprint, so a failed face
    detection only costs the (optional) lip suggestion. Without this fallback the
    UI would show an empty candidate list and the user could never enroll.
    """
    class NoFaces(FakeAudioProvider):
        def detect(self, *, video_id, video_path):
            raise ProviderError("real face detection failed", retryable=True)

    api = make_api(provider=NoFaces(), runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "nofaces", isolation_engine="audio_only"))
    video_id, token, _ = api.upload_ok()
    api.drain()

    body = api.get_faces(video_id, token).json()
    assert body["status"] == "ready"
    assert [f["face_id"] for f in body["faces"]] == ["audio-only"]
    assert body["faces"][0]["thumbnail_url"].endswith("/audio-only/thumbnail")

    # ...and the flow still reaches an enrollment with that placeholder.
    analysis = _get(api, f"/videos/{video_id}/analysis", token).json()
    usable = next(v for v in analysis["voices"] if v["usable"])
    enroll = _post(api, f"/videos/{video_id}/enrollments", token,
                   json={"face_id": "audio-only", "source": "voice", "voice_id": usable["voice_id"]})
    assert enroll.status_code == 202 and enroll.json()["status"] == "ready"


def test_audio_only_keeps_one_placeholder_when_face_detection_fails(make_api, tmp_path):
    """No lip models on the machine must not dead-end the picker.

    The audio-only engine identifies the speaker by voiceprint, so a failed face
    detection only costs the (optional) lip suggestion. Without this fallback the
    UI would show an empty candidate list and the user could never enroll.
    """
    class NoFaces(FakeAudioProvider):
        def detect(self, *, video_id, video_path):
            raise ProviderError("real face detection failed", retryable=True)

    api = make_api(provider=NoFaces(), runner=FakeAudioOnlyRunner(),
                   settings=make_settings(tmp_path / "nofaces", isolation_engine="audio_only"))
    video_id, token, _ = api.upload_ok()
    api.drain()

    body = api.get_faces(video_id, token).json()
    assert body["status"] == "ready"
    assert [f["face_id"] for f in body["faces"]] == ["audio-only"]
    assert body["faces"][0]["thumbnail_url"].endswith("/audio-only/thumbnail")

    # ...and the flow still reaches an enrollment with that placeholder.
    analysis = _get(api, f"/videos/{video_id}/analysis", token).json()
    usable = next(v for v in analysis["voices"] if v["usable"])
    enroll = _post(api, f"/videos/{video_id}/enrollments", token,
                   json={"face_id": "audio-only", "source": "voice", "voice_id": usable["voice_id"]})
    assert enroll.status_code == 202 and enroll.json()["status"] == "ready"
