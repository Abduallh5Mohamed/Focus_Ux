"""Shared local harness for the engine compare and gate tools.

Loads the original Dolphin models once and builds each isolation engine on top
of them. Same offline rules as the worker: no downloads, original environment
and caches read-only. Run with the Python that has PyTorch (see focus_env.cmd).
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "product" / "packages" / "ml"))
sys.path.insert(0, str(ROOT / "product"))

CLEARERVOICE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusClearerVoice"


class Harness:
    def __init__(self, focus: str | None = None):
        from focus_ml.local_paths import focus_home, model_environment
        settings = model_environment(focus_home(focus))
        clearervoice = Path(os.environ.get("FOCUS_CLEARERVOICE_DIR") or CLEARERVOICE_DIR)
        os.environ.update({
            **settings, "FOCUS_CLEARERVOICE_DIR": str(clearervoice),
        })
        sys.path.append(str(clearervoice / "site"))
        from focus_ml.config import AdapterConfig
        from focus_ml.runtime import LocalEngine

        cfg = AdapterConfig.from_env()
        self.config = dataclasses.replace(cfg, isolation_engine="dolphin")
        self.local = LocalEngine(self.config)
        print("Loading original local models (downloads disabled)...", flush=True)
        self.local.initialize()
        self._engines: dict = {}

    def engine(self, name: str):
        if name not in self._engines:
            from focus_ml.isolation_engines import build_engine
            cfg = dataclasses.replace(self.config, isolation_engine=name)
            self._engines[name] = build_engine(
                cfg, self.local.adapter, lambda: self.local.models)
        return self._engines[name]

    def faces_left_to_right(self, video_id: str, video: str) -> list[str]:
        """Face ids ordered by horizontal position (first frame)."""
        from focus_ml.identity import make_face_id
        found = self.local.detect(video_id, video)
        found.sort(key=lambda f: f["bbox"][0])
        return [make_face_id(video_id, f["timestamp_ms"], tuple(f["bbox"]), tuple(f["frame_size"]))
                for f in found]

    def run(self, name: str, video_id: str, video: str, face_id: str, job_dir: str):
        """Returns (ExtractionResult, wall seconds)."""
        from focus_ml.runtime import offline_inference
        engine = self.engine(name)
        started = time.perf_counter()
        with offline_inference():
            result = engine.run(video_id, video, face_id, job_dir)
        return result, round(time.perf_counter() - started, 2)
