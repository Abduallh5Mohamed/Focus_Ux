"""Import-safe and no-download contracts; no models or network required."""
import socket
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from focus_ml.config import AdapterConfig
from focus_ml.errors import ModelUnavailableError
from focus_ml.runtime import LocalEngine, offline_inference
from tools.windows_worker import ConnectionSetupError, NoRedirect, WorkerClient


def test_offline_scope_blocks_and_restores_network():
    original = socket.socket.connect
    with pytest.raises(ModelUnavailableError, match="downloads are disabled"):
        with offline_inference():
            socket.socket().connect(("127.0.0.1", 1234))
    assert socket.socket.connect is original


def test_missing_original_assets_fail_before_loading_models(tmp_path):
    engine = LocalEngine(AdapterConfig(model_source=str(tmp_path), model_cache=str(tmp_path)))
    with pytest.raises(ModelUnavailableError, match="mean-face asset"):
        engine.initialize()
    assert engine.models is None


@pytest.mark.parametrize("url", [
    "http://example.com", "https://user:password@example.com",
    "https://example.com/?token=secret", "https://example.com/#secret",
    "https://example.com/untrusted-path",
])
def test_worker_refuses_insecure_or_credential_urls(url):
    with pytest.raises(ValueError):
        WorkerClient(url, "test-key")


def test_worker_normalizes_site_url_without_leaking_key():
    for url in ("https://example.com", "https://example.com/", "https://example.com/api/"):
        client = WorkerClient(url, "test-key")
        assert client.url == "https://example.com/api"
    with pytest.raises(ConnectionSetupError, match="Connection redirected"):
        NoRedirect().redirect_request(None, None, None, None, None, None)


class ResponseBody(io.BytesIO):
    def __init__(self, payload, content_type="application/json"):
        super().__init__(payload)
        self.headers = {"Content-Type": content_type}


def test_preflight_checks_protocol_without_polling_or_loading_models(monkeypatch):
    calls = []
    client = WorkerClient("https://example.com", "worker-secret", "preview-secret")
    def open_request(request, timeout):
        calls.append(request)
        assert timeout == 60
        return ResponseBody(b'{"worker_protocol":1}')
    monkeypatch.setattr(client.opener, "open", open_request)
    client.preflight()
    request = calls[0]
    assert request.full_url == "https://example.com/api/worker/check"
    assert request.get_header("Authorization") == "Bearer preview-secret"
    assert request.get_header("X-focus-worker-token") == "worker-secret"
    assert len(calls) == 1
    assert "worker-secret" not in client.safe_message(RuntimeError("worker-secret preview-secret"))
    assert "preview-secret" not in client.safe_message(RuntimeError("worker-secret preview-secret"))


@pytest.mark.parametrize("body,content_type", [
    (b"<html>Sign in</html>", "text/html"),
    (b'{"worker_protocol":2}', "application/json"),
    (b"not-json", "application/json"),
])
def test_preflight_rejects_login_page_or_wrong_api(monkeypatch, body, content_type):
    client = WorkerClient("https://example.com", "test-secret")
    monkeypatch.setattr(
        client, "request", lambda *_: ResponseBody(body, content_type)
    )
    with pytest.raises(ConnectionSetupError):
        client.preflight()


def test_models_not_loaded_when_connection_check_fails(monkeypatch, tmp_path):
    from tools import windows_worker
    from focus_ml import runtime
    def failed():
        raise ConnectionSetupError("connection redirected")
    monkeypatch.setattr(windows_worker, "saved_client", lambda *_: SimpleNamespace(preflight=failed))
    def must_not_load(*_):
        pytest.fail("model initialization must happen AFTER authenticated reachability")
    monkeypatch.setattr(runtime, "LocalEngine", must_not_load)
    with pytest.raises(ConnectionSetupError, match="redirected"):
        windows_worker.run("https://example.com", str(tmp_path))
