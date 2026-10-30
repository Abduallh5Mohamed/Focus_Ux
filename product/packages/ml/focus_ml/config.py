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


TRACKING_MODES = ("reference", "adaptive")
ISOLATION_ENGINES = ("dolphin", "av_mossformer2", "separate_select")


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
    # "reference" = legacy cadence (the validated default). "adaptive" is opt-in
    # until it passes the A/B quality gate on the GPU machine.
    tracking_mode: str = "reference"
    # Which isolation engine runs behind the worker. Dolphin stays the default
    # until the user picks another after the listening comparison.
    isolation_engine: str = "dolphin"
    # Separate environment/cache for the optional ClearerVoice engines.
    clearervoice_dir: str | None = None
    adaptive_min_confidence: float = 0.6
    adaptive_max_interval: int = 32
    adaptive_edge_interval: int = 8
    adaptive_identity_iou: float = 0.3
    adaptive_max_hold_frames: int = 12

    def __post_init__(self) -> None:
        if self.isolation_engine not in ISOLATION_ENGINES:
            raise ValueError(
                f"isolation_engine must be one of {ISOLATION_ENGINES}, "
                f"got {self.isolation_engine!r}"
            )
        if self.tracking_mode not in TRACKING_MODES:
            raise ValueError(
                f"tracking_mode must be one of {TRACKING_MODES}, got {self.tracking_mode!r}"
            )

    @classmethod
    def from_env(cls, env: "dict | None" = None) -> "AdapterConfig":
        sources = os.environ if env is None else env
        return cls(
            model_source=_optional_str(sources, "FOCUS_MODEL_SOURCE"),
            model_cache=_optional_str(sources, "FOCUS_MODEL_CACHE"),
            max_video_seconds=_forced_int(sources, "FOCUS_MAX_VIDEO_SECONDS", 15),
            max_upload_mb=_forced_int(sources, "FOCUS_MAX_UPLOAD_MB", 50),
            tracking_mode=_optional_str(sources, "FOCUS_TRACKING_MODE") or "reference",
            isolation_engine=_optional_str(sources, "FOCUS_ISOLATION_ENGINE") or "dolphin",
            clearervoice_dir=_optional_str(sources, "FOCUS_CLEARERVOICE_DIR"),
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
