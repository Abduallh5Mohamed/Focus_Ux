"""Test harness around the FastAPI TestClient.

The dispatcher is NOT auto-started in tests: ``drain()`` runs queued work
synchronously so tests can prove requests only enqueue. Recovery/lock tests
start the real dispatcher explicitly.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from .fixtures_media import make_mp4_bytes
from services.api.focus_api.config import Settings


def make_settings(base: Path, **overrides) -> Settings:
    # The existing suites exercise the lip-based flow (job carries a face).
    overrides.setdefault("isolation_engine", "dolphin")
    settings = Settings(storage_root=Path(base), **overrides)
    return settings


class Harness:
    def __init__(self, *, client: TestClient, app, settings: Settings):
        self.client = client
        self.app = app
        self.settings = settings

    # -- auth ---------------------------------------------------------------
    @staticmethod
    def auth(token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    # -- lifecycle ----------------------------------------------------------
    def drain(self, timeout: float = 30.0) -> int:
        return self.app.state.dispatcher.drain(timeout)

    @property
    def repo(self):
        return self.app.state.repo

    @property
    def dispatcher(self):
        return self.app.state.dispatcher

    # -- uploads ------------------------------------------------------------
    def upload(
        self,
        data: bytes | None = None,
        *,
        token: str | None = None,
        filename: str = "clip.mp4",
        content_type: str = "video/mp4",
    ):
        payload = make_mp4_bytes() if data is None else data
        return self.client.post(
            "/videos",
            files={"file": (filename, payload, content_type)},
            headers=self.auth(token),
        )

    def upload_ok(self, **kwargs) -> tuple[str, str, dict]:
        response = self.upload(**kwargs)
        assert response.status_code == 201, response.text
        body = response.json()
        return body["video_id"], body["session_token"], body

    def setup_video(self, *, transcriber=None, runner=None) -> dict:
        """Upload, drain face detection, return ids and first face."""
        video_id, token, _body = self.upload_ok()
        self.drain()
        faces = self.client.get(
            f"/videos/{video_id}/faces", headers=self.auth(token)
        ).json()
        assert faces["status"] == "ready", faces
        assert faces["faces"], faces
        return {
            "video_id": video_id,
            "token": token,
            "faces": faces["faces"],
            "face_id": faces["faces"][0]["face_id"],
        }

    # -- convenience --------------------------------------------------------
    def create_job(self, video_id: str, face_id: str, request_id: str, token: str, **kwargs):
        return self.client.post(
            "/jobs",
            json={
                "video_id": video_id,
                "face_id": face_id,
                "client_request_id": request_id,
            },
            headers=self.auth(token),
            **kwargs,
        )

    def get_job(self, job_id: str, token: str):
        return self.client.get(f"/jobs/{job_id}", headers=self.auth(token))

    def get_audio(self, job_id: str, token: str, headers: dict | None = None):
        merged = self.auth(token)
        merged.update(headers or {})
        return self.client.get(f"/jobs/{job_id}/audio", headers=merged)

    def get_transcript(self, job_id: str, token: str):
        return self.client.get(f"/jobs/{job_id}/transcript", headers=self.auth(token))

    def get_faces(self, video_id: str, token: str):
        return self.client.get(f"/videos/{video_id}/faces", headers=self.auth(token))

    def get_original(self, video_id: str, token: str, headers: dict | None = None):
        merged = self.auth(token)
        merged.update(headers or {})
        return self.client.get(f"/videos/{video_id}/original", headers=merged)

    def get_thumbnail(self, video_id: str, face_id: str, token: str):
        return self.client.get(
            f"/videos/{video_id}/faces/{face_id}/thumbnail", headers=self.auth(token)
        )

    def delete_video(self, video_id: str, token: str):
        return self.client.delete(f"/videos/{video_id}", headers=self.auth(token))
