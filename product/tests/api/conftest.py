"""Path bootstrap and shared app factory: python -m pytest product/tests/api."""
from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
for candidate in (str(PRODUCT_ROOT),):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from .harness import Harness, make_settings  # noqa: E402
from .fakes import DEFAULT_FACES, FakeCandidateProvider, FakeExtractionRunner, make_wav_bytes  # noqa: E402
from .fixtures_media import make_mp4_bytes  # noqa: E402

from services.api.focus_api.routes import create_app  # noqa: E402


@pytest.fixture
def make_api(tmp_path):
    stack = ExitStack()
    counter = {"n": 0}

    def factory(
        *,
        provider=None,
        runner=None,
        transcriber=None,
        settings=None,
        start_dispatcher=False,
    ) -> Harness:
        counter["n"] += 1
        resolved = settings or make_settings(tmp_path / f"api{counter['n']}")
        app = create_app(
            settings=resolved,
            candidate_provider=provider if provider is not None else FakeCandidateProvider(),
            extraction_runner=runner if runner is not None else FakeExtractionRunner(),
            transcriber=transcriber,
            start_dispatcher=start_dispatcher,
        )
        client = stack.enter_context(TestClient(app))
        return Harness(client=client, app=app, settings=resolved)

    yield factory
    stack.close()


@pytest.fixture
def ready_media(make_api):
    api = make_api()
    data = api.setup_video()
    response = api.create_job(data["video_id"], data["face_id"], "ready", data["token"])
    assert response.status_code == 202
    job = response.json()["job_id"]
    assert api.get_job(job, data["token"]).json()["status"] == "queued"
    api.drain()
    assert api.get_job(job, data["token"]).json()["status"] == "completed"
    _, stranger, _ = api.upload_ok()
    video, face = data["video_id"], data["face_id"]
    return api, data, job, stranger, [
        (f"/videos/{video}/original", make_mp4_bytes(), "video/mp4"),
        (f"/videos/{video}/faces/{face}/thumbnail", DEFAULT_FACES[0].thumbnail_bytes, "image/jpeg"),
        (f"/jobs/{job}/audio", make_wav_bytes(), "audio/wav"),
    ]


@pytest.fixture
def make_settings_for(tmp_path):
    counter = {"n": 0}

    def factory(**overrides):
        counter["n"] += 1
        return make_settings(tmp_path / f"settings{counter['n']}", **overrides)

    return factory
