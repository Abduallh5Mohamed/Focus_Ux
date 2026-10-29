"""Import-safe adapter configuration.

``import focus_ml`` performs no os.chdir, no sys.path mutation and no other
side effects. ``model_source``/``model_cache`` are stored here but their paths
are RESOLVED AND ACTIVATED lazily at execution time inside adapter methods —
this keeps the legacy import-time ``os.chdir(DOLPHIN)`` gap (docs/01 #2)
explicit instead of silently hiding it; cwd side effects are limited to the
execution body (restored per request), a documented honest compromise.

Deferred/unused config fields THIS MILESTONE:
- ``merge``: window merge strategy; stored only, separation parity is
  GPU-pending so no merge mode is honored yet.
- ``downscale``: legacy experiment only, unsupported; detect/track paths
  reject it at runtime (downscaled detection was never geometrically
  validated and must not silently produce wrong boxes).
- ``session_paths``: deferred activation hook, not consumed this milestone.

Wired fields: ``detect_every`` (legacy default, mirrors focus_ml.tracking.
DETECT_EVERY = 8) and ``landmark_every`` are actually used by the tracking
stage; ``sample_rate`` feeds duration computation and window sizing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _optional_str(env, name: str) -> str | None:
    value = env.get(name)
    return value if value else None


def _forced_int(env, name: str, default: int) -> int:
    try:
        return int(env[name])
    except (KeyError, TypeError, ValueError):
        return default


@dataclass
class AdapterConfig:
    model_source: str | None = None
    model_cache: str | None = None
    max_video_seconds: int = 15
    max_upload_mb: int = 50
    window_s: float = 2.0
    detect_every: int = 8
    landmark_every: int = 1
    downscale: float | None = None
    device: str = "cuda"
    sample_rate: int = 16000
    fps: int = 25
    merge: str = "direct"

    @classmethod
    def from_env(cls, env: "dict | None" = None) -> "AdapterConfig":
        sources = os.environ if env is None else env
        return cls(
            model_source=_optional_str(sources, "FOCUS_MODEL_SOURCE"),
            model_cache=_optional_str(sources, "FOCUS_MODEL_CACHE"),
            max_video_seconds=_forced_int(sources, "FOCUS_MAX_VIDEO_SECONDS", 15),
            max_upload_mb=_forced_int(sources, "FOCUS_MAX_UPLOAD_MB", 50),
        )

    @classmethod
    def session_paths(cls, config: "AdapterConfig") -> tuple[str | None, str | None]:
        """DEFERRED, unused this milestone: returns (sys.path insertion point,
        working dir) that adapter execution MAY activate when the real legacy
        backend runs. Importing this package never consumes these values; they
        mirror legacy lines 23-25 which did ``sys.path.insert(0, DOLPHIN)`` and
        ``os.chdir(DOLPHIN)`` AT IMPORT TIME (docs/01 #2). Current adapter
        behavior: sys.path/cwd are temporarily activated inside ``_load_backend``
        and restored on exit (per-request restoration, honest compromise)."""
        return (config.model_source, config.model_source)
