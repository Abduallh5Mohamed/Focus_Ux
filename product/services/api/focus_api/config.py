"""Runtime configuration for the local FOCUS API.

Defaults target a localhost developer machine:
  API      http://127.0.0.1:8000
  UI       http://localhost:5173
  storage  A:/Focus_Ux/runtime/round2/api

Everything can be overridden with environment variables; nothing here writes
outside the configured storage root.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SERVICES_API_DIR = PACKAGE_DIR.parent
PRODUCT_ROOT = SERVICES_API_DIR.parent.parent
REPO_ROOT = PRODUCT_ROOT.parent

DEFAULT_STORAGE_ROOT = REPO_ROOT / "runtime" / "round2" / "api"
DEFAULT_UI_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_VIDEO_MS = 15_000


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    storage_root: Path = field(default_factory=lambda: DEFAULT_STORAGE_ROOT)
    db_path: Path | None = None
    lock_path: Path | None = None
    ui_origins: tuple[str, ...] = DEFAULT_UI_ORIGINS
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    max_video_ms: int = DEFAULT_MAX_VIDEO_MS
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # When set, thumbnail_url is absolute (trusted API origin). Otherwise it is
    # a relative path and the browser resolves it against the API base URL.
    public_base_url: str | None = None
    cleanup_temp_max_age_s: float = 3600.0
    inference_mode: str = "unavailable"
    worker_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.storage_root = Path(self.storage_root).expanduser().resolve()
        if self.db_path is not None:
            self.db_path = Path(self.db_path).expanduser().resolve()
        if self.lock_path is not None:
            self.lock_path = Path(self.lock_path).expanduser().resolve()
        self.ui_origins = tuple(str(origin) for origin in self.ui_origins)

    # -- derived directories -------------------------------------------------
    @property
    def media_dir(self) -> Path:
        return self.storage_root / "media"

    @property
    def jobs_dir(self) -> Path:
        return self.storage_root / "jobs"

    @property
    def thumbs_dir(self) -> Path:
        return self.storage_root / "thumbs"

    @property
    def tmp_dir(self) -> Path:
        return self.storage_root / "tmp"

    @property
    def db_file(self) -> Path:
        return self.db_path if self.db_path is not None else self.storage_root / "focus.sqlite3"

    @property
    def lock_file(self) -> Path:
        return self.lock_path if self.lock_path is not None else self.storage_root / "dispatcher.lock"

    @property
    def max_upload_mb(self) -> int:
        return max(1, int(self.max_upload_bytes // (1024 * 1024)) or 1)

    @property
    def thumbnail_url_prefix(self) -> str:
        base = (self.public_base_url or "").rstrip("/")
        return base

    @classmethod
    def from_env(cls) -> "Settings":
        origins_raw = os.environ.get("FOCUS_API_UI_ORIGINS", "")
        origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())
        storage = _env_path("FOCUS_API_STORAGE_ROOT") or DEFAULT_STORAGE_ROOT
        max_upload_mb = _env_int(
            "FOCUS_API_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_BYTES // (1024 * 1024)
        )
        return cls(
            storage_root=storage,
            db_path=_env_path("FOCUS_API_DB_PATH"),
            lock_path=_env_path("FOCUS_API_LOCK_PATH"),
            ui_origins=origins or DEFAULT_UI_ORIGINS,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            max_video_ms=_env_int("FOCUS_API_MAX_VIDEO_MS", DEFAULT_MAX_VIDEO_MS),
            api_host=os.environ.get("FOCUS_API_HOST", "127.0.0.1"),
            api_port=_env_int("FOCUS_API_PORT", 8000),
            public_base_url=os.environ.get("FOCUS_API_PUBLIC_BASE_URL") or None,
            cleanup_temp_max_age_s=_env_float("FOCUS_API_TEMP_MAX_AGE_S", 3600.0),
            inference_mode=os.environ.get("FOCUS_INFERENCE_MODE", "unavailable"),
            worker_token=os.environ.get("FOCUS_WORKER_TOKEN") or None,
        )
