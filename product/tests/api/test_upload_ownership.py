"""Real processes must not mistake a paused upload for abandoned data."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from services.api.focus_api.storage import Storage

from .harness import make_settings


OWNER = r"""
import io
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from api.fixtures_media import make_mp4_bytes
from services.api.focus_api import service
from services.api.focus_api.config import Settings
from services.api.focus_api.routes import create_app
from services.api.focus_api.storage import Storage

root, phase = Path(sys.argv[1]), sys.argv[2]
settings = Settings(storage_root=root, cleanup_temp_max_age_s=0.02)

def pause():
    (root / "paused").write_text("ready")
    assert sys.stdin.readline().strip() == "resume"

if phase == "before-file":
    storage = Storage(settings)
    storage.ensure()
    with storage.own_temp_upload() as path:
        pause()
    sys.exit(0)

class PausedStream(io.BytesIO):
    def read(self, size=-1):
        if phase == "read" and self.tell():
            pause()
        return super().read(size)

original_probe = service.probe_video
def probe(path):
    if phase == "probe":
        pause()
    return original_probe(path)
service.probe_video = probe

original_replace = service.os.replace
def replace(source, target):
    if phase == "move":
        pause()
    return original_replace(source, target)
service.os.replace = replace

app = create_app(settings=settings, start_dispatcher=False)
with TestClient(app):
    body, _ = app.state.service.upload(
        stream=PausedStream(make_mp4_bytes()), content_type="video/mp4", token=None
    )
    assert app.state.storage.find_media_path(body["video_id"]).is_file()
"""


@pytest.mark.parametrize("phase", ["read", "probe", "move", "before-file"])
@pytest.mark.parametrize("crash", [False, True], ids=["resume", "owner-killed"])
def test_startup_preserves_paused_owner_and_recovers_after_exit(
    tmp_path, make_api, phase, crash
):
    settings = make_settings(tmp_path, cleanup_temp_max_age_s=0.02)
    product = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(product), str(product / "tests"), env.get("PYTHONPATH", "")]
    )
    owner = subprocess.Popen(
        [sys.executable, "-c", OWNER, str(tmp_path), phase],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path / "paused").exists():
            if owner.poll() is not None:
                stdout, stderr = owner.communicate()
                pytest.fail(f"Owner exited before pause:\n{stdout}\n{stderr}")
            assert time.monotonic() < deadline, "owner did not reach upload pause"
            time.sleep(0.01)

        files = list(settings.tmp_dir.glob("*.upload"))
        assert len(files) == (0 if phase == "before-file" else 1)
        leases = list(settings.tmp_dir.glob("*.upload.lock"))
        assert len(leases) == 1
        # The owner remains blocked longer than the configured age. Backdate
        # as well to make the cutoff deterministic on coarse timestamp filesystems.
        for path in files:
            os.utime(path, (1, 1))
        time.sleep(settings.cleanup_temp_max_age_s * 2)
        if files:
            assert time.time() - files[0].stat().st_mtime > settings.cleanup_temp_max_age_s
        abandoned = settings.tmp_dir / "abandoned.upload"
        abandoned.write_bytes(b"unowned")
        os.utime(abandoned, (1, 1))

        # A genuinely separate API instance performs its normal startup pass.
        cleaner = make_api(settings=settings)
        assert not abandoned.exists()
        assert all(path.exists() for path in files + leases)
        assert cleaner.app.state.storage.cleanup_stale_temp() == []
        assert all(path.exists() for path in files + leases)

        if crash:
            # No context-manager/finally cleanup is run by the owner.
            owner.kill()
            owner.communicate(timeout=10)
            removed = cleaner.app.state.storage.cleanup_stale_temp()
            assert removed == [str(path) for path in files]
            assert not list(settings.media_dir.iterdir())
        else:
            stdout, stderr = owner.communicate("resume\n", timeout=15)
            assert owner.returncode == 0, f"{stdout}\n{stderr}"
            assert len(list(settings.media_dir.iterdir())) == (0 if phase == "before-file" else 1)

        assert not list(settings.tmp_dir.iterdir())
        assert cleaner.app.state.storage.cleanup_stale_temp() == []
        # Another startup is safe after the recovery and does not remove media.
        Storage(settings).ensure()
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


def test_lease_protects_against_another_storage_in_same_process(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings)
    storage.ensure()
    with storage.own_temp_upload() as path:
        path.write_bytes(b"paused")
        os.utime(path, (1, 1))
        Storage(settings).ensure()
        assert path.read_bytes() == b"paused"
    # A failed upload whose file could not be deleted is no longer protected.
    assert Storage(settings).cleanup_stale_temp() == [str(path)]
    assert not list(settings.tmp_dir.iterdir())
