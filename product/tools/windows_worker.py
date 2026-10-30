"""Outbound-only Windows CUDA worker. Uses the user's existing environment.

No dependency installation, model downloads, listener, tunnel or training.
Run from the extracted worker kit; original A:/focus files remain read-only.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "product" / "packages" / "ml"))
sys.path.insert(0, str(ROOT / "product"))
TOKEN_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusWorker" / "worker-token"
LOCAL_TOKEN_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusLocalTrial" / "worker-token"
PREVIEW_TOKEN_FILE = TOKEN_FILE.parent / "preview-access-token"
# A 3-minute canonical clip is tens of MB. Configurable, still bounded.
MAX_MEDIA_BYTES = int(os.environ.get("FOCUS_WORKER_MAX_MEDIA_MB", "250")) * 1024 * 1024
MAX_OUTPUT_AUDIO_BYTES = 8 * 1024 * 1024  # 3 min mono PCM16 @ 16 kHz is about 5.8 MB
AUDIO_TASKS = ("transcribe", "analyze", "enroll", "isolate")  # media is audio, not video
ENGINES = ("audio_only", "dolphin", "av_mossformer2", "separate_select")


class ConnectionSetupError(RuntimeError):
    """Safe, actionable connection error. Contains no credentials or URLs."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ConnectionSetupError(
            "Connection redirected before reaching FOCUS. The preview may require "
            "Replit sign-in, or the website address may have changed. No credentials "
            "were forwarded. Use Check-Connection.cmd; do not change model files."
        )


class WorkerClient:
    def __init__(self, url, token, preview_token=None, *, local_api=False):
        parts = urlsplit(url)
        if local_api:
            if url not in ("http://127.0.0.1:5000", "http://127.0.0.1:5000/api"):
                raise ValueError("local API must be http://127.0.0.1:5000")
            if preview_token:
                raise ValueError("preview credentials must never be sent to the local API")
            self.url, self.token = "http://127.0.0.1:5000/api", token
            self.preview_token = None
            # Do not send loopback credentials through an inherited HTTP proxy.
            from urllib.request import ProxyHandler
            self.opener = build_opener(ProxyHandler({}), NoRedirect())
            return
        if (
            parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/", "/api", "/api/")
        ):
            raise ValueError("enter the trusted site's HTTPS address, without query parameters")
        self.url, self.token = "https://" + parts.netloc + "/api", token
        self.preview_token = preview_token
        self.opener = build_opener(NoRedirect())

    def request(self, path, data=None, content_type="application/json", extra_headers=None):
        # Relative paths are constructed here, never supplied by task payloads.
        request = Request(
            self.url + path, data=data,
            headers={
                "Authorization": "Bearer " + (self.preview_token or self.token),
                "X-Focus-Worker-Token": self.token,
                "Content-Type": content_type,
                "Cache-Control": "no-store",
                **(extra_headers or {}),
            },
        )
        return self.opener.open(request, timeout=60)

    def preflight(self):
        """Check authenticated reachability before loading GPU models.

        Does not poll/claim work or mark the worker online.
        """
        try:
            with self.request("/worker/check") as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(4097)
                if "application/json" not in content_type or len(raw) > 4096:
                    raise ConnectionSetupError(
                        "The address returned a web/sign-in page, not the FOCUS worker API. "
                        "Check private-preview access and the website address."
                    )
                result = json.loads(raw)
                if not isinstance(result, dict) or result.get("worker_protocol") != 1:
                    raise ConnectionSetupError("The address is not a compatible FOCUS worker API.")
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ConnectionSetupError(
                    "Connection denied (HTTP %d). Check the saved worker key and, "
                    "if the preview is private, its separate development access token."
                    % exc.code
                ) from None
            if exc.code == 404:
                raise ConnectionSetupError(
                    "Worker API not found (HTTP 404). Check the site address, "
                    "remote inference mode and server version."
                ) from None
            raise ConnectionSetupError(
                "Website connection check failed (HTTP %d)." % exc.code
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ConnectionSetupError(
                "Cannot reach the website. Check internet access, the HTTPS address "
                "and that the Replit application is running. Models were not loaded."
            ) from None
        except (ValueError, UnicodeError):
            raise ConnectionSetupError("Website returned an invalid worker handshake.") from None

    def safe_message(self, exc):
        message = str(exc)
        for secret in (self.token, self.preview_token):
            if secret:
                message = message.replace(secret, "[redacted]")
        return message[:1500]

    def json(self, path, payload=None):
        with self.request(path, json.dumps(payload or {}).encode()) as response:
            raw = response.read(4 * 1024 * 1024 + 1)  # task payloads carry the diarization
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError("server response too large")
            return json.loads(raw) if raw else None

    def stream_poll(self, live_id):
        if len(live_id) != 32 or any(c not in "0123456789abcdef" for c in live_id):
            raise ValueError("invalid stream id")
        with self.request("/worker/stream/" + live_id + "/poll", b"", "application/octet-stream") as r:
            body = r.read(5 * 1024 * 1024)
            return body or None

    def stream_out(self, live_id, body):
        with self.request("/worker/stream/" + live_id + "/out", body, "application/octet-stream") as r:
            r.read(1024)

    def run_stream(self, task, engine):
        from focus_ml.live_stream_backend import AccelOptions, DolphinStreamBackend
        from tools.stream_worker import run_stream

        accel = AccelOptions(
            fp16=os.environ.get("FOCUS_LIVE_FP16", "1") != "0",
            compile=os.environ.get("FOCUS_LIVE_COMPILE", "0") == "1",
        )
        backend = DolphinStreamBackend(engine, accel)
        print("Live stream started. Isolating continuously...", flush=True)
        run_stream(self, task["task_id"], backend, task["config"], accel=backend.accel_report)
        print("Live stream ended.", flush=True)

    def process(self, task, engine):
        task_id = task["task_id"]
        if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
            raise ValueError("invalid task id")
        prefix = "/worker/tasks/" + task_id
        try:
            with tempfile.TemporaryDirectory(prefix="focus-inference-") as directory:
                video = Path(directory) / (
                    "canonical.mp4" if task["kind"] in ("detect", "extract", "visibility")
                    else "task-audio.wav"
                )
                digest, total = hashlib.sha256(), 0
                with self.request(prefix + "/media") as response, video.open("wb") as output:
                    while chunk := response.read(64 * 1024):
                        total += len(chunk)
                        if total > MAX_MEDIA_BYTES:
                            raise ValueError("canonical media exceeds the worker limit")
                        digest.update(chunk)
                        output.write(chunk)
                if digest.hexdigest() != task["sha256"]:
                    raise ValueError("canonical media checksum mismatch")
                self.handle(task, engine, video, directory, prefix)
                print("Task complete. Temporary media removed.", flush=True)
        except Exception as exc:
            # The website receives a curated code, never local paths/stderr.
            try:
                self.json(prefix + "/error", {"code": getattr(exc, "code", "PROCESSING_FAILED")})
            except Exception:
                pass
            raise

    def handle(self, task, engine, video, directory, prefix):
        kind = task["kind"]
        payload = task.get("payload") or {}
        if kind == "detect":
            self.json(prefix + "/faces", engine.detect(task["video_id"], str(video)))
        elif kind == "extract":
            result = engine.extract(task["video_id"], str(video), task["face_id"], directory)
            wav = Path(result.wav_path)
            if wav.resolve().parent != Path(directory).resolve():
                raise ValueError("engine output is outside its task directory")
            if result.source_offset_ms != 0 or wav.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("engine output is oversized or shifted")
            with self.request(
                prefix + "/audio", wav.read_bytes(), "audio/wav",
                {"X-Focus-Engine": getattr(result, "engine", "dolphin")},
            ) as response:
                response.read(1024)
        elif kind == "transcribe":
            self.json(prefix + "/transcript", {"segments": engine.transcribe_audio(str(video))})
        elif kind == "analyze":
            # Audio only: diarization, voiceprints, clean sample spans and clips.
            self.json(prefix + "/analysis", engine.analyze_audio(str(video)))
        elif kind == "enroll":
            try:
                if payload.get("mode") == "range":
                    result = engine.enroll_audio_range(
                        str(video), payload["diarization"],
                        payload["start_ms"] / 1000, payload["end_ms"] / 1000)
                else:
                    result = engine.enroll_audio_file(str(video))
            except Exception as exc:
                if getattr(exc, "code", None) != "ENROLLMENT_REFUSED":
                    raise
                result = {"refused": str(getattr(exc, "message", exc))[:400]}
            self.json(prefix + "/enrollment", result)
        elif kind == "visibility":
            spans = engine.face_visibility(str(video), payload["bbox"], payload["frame_size"])
            self.json(prefix + "/visibility", {"visible": spans})
        elif kind == "isolate":
            # The request carries the enrollment and the cached diarization. No
            # video, frame, face or lip data exists on this path.
            from focus_ml.voice.engine import regions_to_wire
            result = engine.isolate_audio(
                str(video), payload["voiceprint"], payload["diarization"], directory)
            wav = Path(result.wav_path)
            if wav.resolve().parent != Path(directory).resolve():
                raise ValueError("engine output is outside its task directory")
            if result.source_offset_ms != 0 or wav.stat().st_size > MAX_OUTPUT_AUDIO_BYTES:
                raise ValueError("engine output is oversized or shifted")
            self.json(prefix + "/regions", {"regions": regions_to_wire(result.details["regions"])})
            with self.request(
                prefix + "/audio", wav.read_bytes(), "audio/wav", {"X-Focus-Engine": "audio_only"},
            ) as response:
                response.read(1024)
        else:
            raise ValueError("unsupported task")


def setup():
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TOKEN_FILE.exists():
        with TOKEN_FILE.open("x") as output:
            output.write(secrets.token_urlsafe(48))
        TOKEN_FILE.chmod(0o600)
    # Copy through stdin, never a command argument, log, URL or chat.
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
        input=TOKEN_FILE.read_text().strip(), text=True, check=True,
    )
    print("Worker key copied to clipboard. Paste ONLY into Replit Secrets: FOCUS_WORKER_TOKEN.")
    print("Do not paste it into chat. Clear the clipboard after saving.")


def setup_preview_access():
    """Optional PRIVATE development-preview gate; separate from worker auth."""
    token = getpass.getpass(
        "Paste the separate Replit DEVELOPMENT external access token (hidden), then Enter: "
    ).strip()
    if len(token) < 16 or any(c.isspace() for c in token):
        raise RuntimeError("No valid preview access token supplied.")
    PREVIEW_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_TOKEN_FILE.write_text(token)
    PREVIEW_TOKEN_FILE.chmod(0o600)
    print("Private preview access saved locally. No token was printed or sent to chat.")


def saved_client(url, *, local_api=False):
    if local_api:
        if not LOCAL_TOKEN_FILE.is_file():
            raise RuntimeError("Start scripts/start-local-api.ps1 first.")
        return WorkerClient(url, LOCAL_TOKEN_FILE.read_text().strip(), local_api=True)
    if not TOKEN_FILE.is_file():
        raise RuntimeError("Run Setup-Key.cmd first.")
    preview_token = (
        PREVIEW_TOKEN_FILE.read_text().strip() if PREVIEW_TOKEN_FILE.is_file() else None
    )
    return WorkerClient(url, TOKEN_FILE.read_text().strip(), preview_token)


@contextmanager
def single_worker():
    """Avoid two local processes loading the GPU or processing different tasks."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with (TOKEN_FILE.parent / "worker.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError("another FOCUS worker is already running") from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("another FOCUS worker is already running") from None
            yield


CLEARERVOICE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusClearerVoice"


def run(url, focus, *, local_api=False, engine=None):
    client = saved_client(url, local_api=True) if local_api else saved_client(url)
    print("Checking website connection before loading models...", flush=True)
    client.preflight()
    print("FOCUS connection verified.", flush=True)
    focus = Path(focus).resolve()
    os.environ.update({
        "HF_HOME": str(focus / "cache" / "hf"),
        "TORCH_HOME": str(focus / "cache" / "torch"),
        "FOCUS_MODEL_SOURCE": str(focus / "Dolphin"),
        "FOCUS_MODEL_CACHE": str(focus / "cache" / "hf"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    })
    engine_name = engine or os.environ.get("FOCUS_ISOLATION_ENGINE") or "audio_only"
    # audio_only handles the voice tasks; the lip engine setting below still
    # serves face detection and any lip-based job the website is set to.
    os.environ["FOCUS_ISOLATION_ENGINE"] = "dolphin" if engine_name == "audio_only" else engine_name
    if engine_name not in ("dolphin", "audio_only"):
        # Extra engines live in a separate folder. It is appended LAST on
        # sys.path so the original environment's packages always win.
        clearervoice = Path(os.environ.get("FOCUS_CLEARERVOICE_DIR") or CLEARERVOICE_DIR)
        os.environ["FOCUS_CLEARERVOICE_DIR"] = str(clearervoice)
        sys.path.append(str(clearervoice / "site"))
    print("Isolation engine: " + engine_name, flush=True)
    from focus_ml.config import AdapterConfig
    from focus_ml.runtime import LocalEngine

    engine = LocalEngine(AdapterConfig.from_env())
    print("Loading original local models (downloads disabled)...", flush=True)
    engine.initialize()
    from tools.asr_engine import AsrEngine

    asr = AsrEngine()
    engine.transcribe_audio = asr.transcribe  # model loads once, on first use
    print("Models loaded. Connecting to the website...", flush=True)
    while True:
        try:
            task = client.json("/worker/poll")
            if task:
                print("Processing " + task["kind"] + "...", flush=True)
                try:
                    if task["kind"] == "stream":
                        client.run_stream(task, engine)
                    else:
                        client.process(task, engine)
                except ConnectionSetupError:
                    raise
                except Exception as exc:
                    print(
                        "Task failed: " + type(exc).__name__ + ": " + client.safe_message(exc),
                        flush=True,
                    )
            else:
                time.sleep(2)
        except ConnectionSetupError:
            # A setup/auth redirect is not a model failure and must not loop.
            raise
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError("Worker key rejected. Check FOCUS_WORKER_TOKEN in Replit Secrets.") from None
            if exc.code == 404:
                raise RuntimeError("Worker routes unavailable. Enable remote inference on the website.") from None
            print("Website rejected a task/connection (HTTP %d)." % exc.code, flush=True)
            time.sleep(5)
        except (URLError, TimeoutError, OSError):
            print("Website connection unavailable. Retrying in 5 seconds.", flush=True)
            time.sleep(5)
        except Exception as exc:
            raise ConnectionSetupError(
                "Worker polling failed: " + type(exc).__name__ + ": " + client.safe_message(exc)
            ) from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preview-access", action="store_true")
    parser.add_argument("--engine", choices=ENGINES,
                        help="Isolation engine (default: FOCUS_ISOLATION_ENGINE or audio_only)")
    parser.add_argument("--url")
    parser.add_argument("--focus", default="A:/focus")
    parser.add_argument("--local-api", action="store_true",
                        help="Use only the loopback trial API and its separate local credential")
    args = parser.parse_args()
    if args.local_api and (args.setup or args.preview_access):
        parser.error("--local-api cannot change existing worker or preview credentials")
    if args.local_api:
        args.url = args.url or "http://127.0.0.1:5000"
    if args.setup:
        setup()
    elif args.preview_access:
        setup_preview_access()
    elif args.check:
        url = args.url or input("Website HTTPS address: ").strip()
        client = saved_client(url, local_api=True) if args.local_api else saved_client(url)
        client.preflight()
        print("FOCUS connection verified. " + (
            "Now start the worker with --local-api." if args.local_api
            else "Now use Start-Worker.cmd."
        ))
    else:
        url = args.url or input("Website HTTPS address: ").strip()
        with single_worker():
            run(url, args.focus, local_api=args.local_api, engine=args.engine)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nWorker stopped. No new tasks will be accepted.")
    except Exception as exc:
        # Startup diagnostics stay on the operator's computer.
        print("Startup failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
