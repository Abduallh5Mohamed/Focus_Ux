"""GPU memory discipline: one model at a time, fp16 where supported, unload
between stages, per-stage time and peak VRAM."""
from __future__ import annotations

import contextlib
import gc
import time


def resolve_device(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def release_gpu() -> None:
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


@contextlib.contextmanager
def fp16_if_supported(device: str):
    """fp16 autocast on CUDA only; CPU runs in fp32."""
    if device.startswith("cuda"):
        import torch
        with torch.autocast("cuda", dtype=torch.float16):
            yield
    else:
        yield


class StageLog:
    """Records seconds and peak VRAM (MiB, None on CPU) per stage."""

    def __init__(self, device: str = "cpu"):
        self.device = device
        self.stages: dict[str, dict] = {}

    @contextlib.contextmanager
    def stage(self, name: str):
        cuda = self.device.startswith("cuda")
        if cuda:
            import torch
            torch.cuda.reset_peak_memory_stats()
        t0 = time.perf_counter()
        try:
            yield
        finally:
            entry = {"seconds": round(time.perf_counter() - t0, 3), "peak_vram_mib": None}
            if cuda:
                import torch
                entry["peak_vram_mib"] = round(torch.cuda.max_memory_allocated() / 2**20, 1)
            self.stages[name] = entry

    def as_dict(self) -> dict:
        peaks = [s["peak_vram_mib"] for s in self.stages.values() if s["peak_vram_mib"] is not None]
        return {"device": self.device, "stages": self.stages,
                "peak_vram_mib": max(peaks) if peaks else None,
                "total_seconds": round(sum(s["seconds"] for s in self.stages.values()), 3)}
