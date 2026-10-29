"""Opt-in integration with the running Replit/Vite proxy; no injected inference.

FOCUS_TEST_PROXY_URL=https://<development-host> python -m pytest \
    product/tests/api/test_proxy.py -q
"""
import os

import httpx
import pytest

from .fixtures_media import make_mp4_bytes
from .test_uploads import assert_error


def test_api_prefix_reaches_backend_routes():
    base = os.environ.get("FOCUS_TEST_PROXY_URL")
    if not base:
        pytest.skip("Set FOCUS_TEST_PROXY_URL to the running frontend origin")
    with httpx.Client(base_url=base.rstrip("/"), timeout=30) as client:
        health = client.get("/api/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["dispatcher"] is True
        # A JSON backend 404 proves unknown /api paths do not return the SPA.
        assert_error(client.get("/api/does-not-exist"), 404, "NOT_FOUND")
        payload = make_mp4_bytes()
        response = client.post("/api/videos", files={
            "file": ("proxy-smoke.mp4", payload, "video/mp4"),
        })
        assert response.status_code == 201, response.text
        body = response.json()
        video = body["video_id"]
        headers = {"Authorization": f"Bearer {body['session_token']}"}
        try:
            path = f"/api/videos/{video}/original"
            assert_error(client.get(path), 401, "UNAUTHORIZED")
            original = client.get(path, headers=headers)
            assert original.status_code == 200
            assert original.content == payload
            assert original.headers["cache-control"] == "private, no-store"
            partial = client.get(path, headers={**headers, "Range": "bytes=0-3"})
            assert partial.status_code == 206
            assert partial.content == payload[:4]
            faces = client.get(f"/api/videos/{video}/faces", headers=headers)
            assert faces.status_code == 200
            assert faces.json()["status"] in ("pending", "ready", "failed")
        finally:
            deleted = client.delete(f"/api/videos/{video}", headers=headers)
            assert deleted.status_code == 202
            assert deleted.json() == {"deletion_pending": True}
        assert_error(client.get(path, headers=headers), 404, "NOT_FOUND")
