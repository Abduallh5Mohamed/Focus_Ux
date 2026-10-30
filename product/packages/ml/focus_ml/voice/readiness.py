"""Read-only readiness report: GPU, VRAM, CUDA, worker connection, weights.
Never installs, downloads or loads a model."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from .weights import activate_site, voice_home, weight_status

TOOLS = Path(__file__).resolve().parents[4] / "tools"


def gpu_info() -> dict:
    activate_site()
    info = {"torch": None, "cuda": None, "cuda_available": False, "gpu": None, "vram_mib": None}
    try:
        import torch
        info.update(torch=torch.__version__, cuda=torch.version.cuda,
                    cuda_available=bool(torch.cuda.is_available()))
        if info["cuda_available"]:
            p = torch.cuda.get_device_properties(0)
            info.update(gpu=p.name, vram_mib=round(p.total_memory / 2**20))
            return info
    except ImportError:
        info["note"] = "PyTorch is not installed in this environment"
    try:   # fall back to the driver so a missing/CPU torch is still explained
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            name, mem = [x.strip() for x in out.stdout.splitlines()[0].split(",")]
            info.update(gpu=name, vram_mib=int(float(mem)), driver_only=True)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return info


def worker_connection(url: str | None, local_api: bool = False) -> dict:
    """Uses the existing worker client (same key, no redirects); no work is claimed."""
    if not url:
        return {"checked": False, "detail": "no --url given"}
    try:
        spec = importlib.util.spec_from_file_location("windows_worker", TOOLS / "windows_worker.py")
        ww = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ww)
        client = ww.saved_client(url, local_api=local_api)
        client.preflight()
        return {"checked": True, "ok": True, "detail": "worker API reachable and compatible"}
    except Exception as exc:   # messages from the worker client are credential-free
        return {"checked": True, "ok": False, "detail": str(exc)}


def extractor_status() -> dict:
    """Overlap-extraction candidates: weights/code present or the blocker. Read-only,
    informational: the gated baseline works without them, so they do not gate
    ``ready_for_gpu``."""
    from ..overlap.candidates import candidate_status
    return candidate_status()


def collect(url: str | None = None, local_api: bool = False, min_vram_mib: int = 3500) -> dict:
    gpu = gpu_info()
    weights = weight_status()
    checks = {
        "gpu_found": bool(gpu["gpu"]),
        "cuda_usable": gpu["cuda_available"],
        "vram_fits_4gb_class": bool(gpu["vram_mib"] and gpu["vram_mib"] >= min_vram_mib),
        "weights_present": all(weights.values()),
    }
    conn = worker_connection(url, local_api)
    extractors = extractor_status()
    return {"python": sys.version.split()[0], "voice_home": str(voice_home()), "gpu": gpu,
            "weights": weights, "worker": conn,
            "overlap_extractors": extractors,
            "overlap_extractors_ready": sorted(n for n, v in extractors.items() if v["ready"]), "checks": checks,
            "ready_for_gpu": all(checks.values()) and (not conn["checked"] or conn.get("ok", False))}
