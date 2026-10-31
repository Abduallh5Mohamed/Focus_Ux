"""Read-only NVIDIA GPU detection and a VRAM-based sizing plan.

Nothing here loads a model, downloads anything, or assumes a GPU model. ``detect`` reports what the
driver (``nvidia-smi``) and PyTorch each see, and the blockers when CUDA cannot be used. ``plan_for``
turns the free VRAM into an extractor window length and batch size from the candidate's own VRAM model
(``CandidateInfo.vram_base_mib`` / ``vram_per_window_s_mib``).

Those per-model numbers and ``RESERVE_MIB`` are conservative estimates used only to choose a starting
point. They are not measurements: an out-of-memory error still halves the batch at run time, and peak
VRAM is measured and logged by the extraction itself. No speed figure is produced here.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field

# Kept free for the CUDA context, the voice embedder and allocator fragmentation (estimate).
RESERVE_MIB = 1024
# Window lengths tried from longest to shortest. 4 s is the length the pipeline was built around.
WINDOW_CHOICES_S = (4.0, 3.0, 2.0)
MAX_BATCH = 16


def real_probes() -> dict:
    """What this Python environment and the driver report. Importing torch can be slow; no model loads."""
    out: dict = {"torch": None}
    try:
        import torch
        out["torch"] = {"version": torch.__version__, "cuda_build": torch.version.cuda,
                        "cuda_available": bool(torch.cuda.is_available())}
        if out["torch"]["cuda_available"]:
            free, total = torch.cuda.mem_get_info(0)
            props = torch.cuda.get_device_properties(0)
            out["gpu"] = {"name": props.name, "capability": list(torch.cuda.get_device_capability(0)),
                          "total_mib": round(total / 2**20), "free_mib": round(free / 2**20)}
    except ImportError:
        pass
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            name, driver, total, free = [v.strip() for v in r.stdout.splitlines()[0].split(",")]
            out["driver"] = {"name": name, "driver": driver, "total_mib": int(float(total)),
                             "free_mib": int(float(free))}
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return out


def detect(probes: dict | None = None) -> dict:
    """``{"usable", "device", "vram_free_mib", "vram_total_mib", "driver", "blockers", "probes"}``.

    ``usable`` is true only when PyTorch can run on the GPU. Otherwise ``blockers`` says why (no driver,
    CPU-only PyTorch build, no PyTorch, ...). The first GPU is used, as everywhere else in the project;
    set ``CUDA_VISIBLE_DEVICES`` to choose another one.
    """
    pr = real_probes() if probes is None else probes
    t, gpu, drv = pr.get("torch"), pr.get("gpu"), pr.get("driver")
    blockers: list[str] = []
    if t is None:
        blockers.append("PyTorch is not importable in this Python environment")
    elif not t.get("cuda_build"):
        blockers.append("this PyTorch is a CPU-only build; install the CUDA build of PyTorch")
    elif not t.get("cuda_available"):
        blockers.append("PyTorch has a CUDA build but cannot use a GPU (driver too old, or no NVIDIA GPU)")
    if drv is None:
        blockers.append("nvidia-smi found no NVIDIA driver or GPU")
    if gpu is not None and t and t.get("cuda_build") and gpu["capability"][0] < 5:
        blockers.append("GPU compute capability is older than PyTorch CUDA builds support")
    usable = gpu is not None and not blockers
    source = gpu or drv or {}
    return {"usable": usable,
            "device": source.get("name"),
            "vram_total_mib": source.get("total_mib"),
            "vram_free_mib": source.get("free_mib"),
            "driver": (drv or {}).get("driver"),
            "compute_capability": gpu["capability"] if gpu else None,
            "pytorch": t, "blockers": blockers, "probes": pr}


@dataclass
class GpuPlan:
    """A starting point for extraction on this GPU (estimate, not a measurement)."""
    device: str                      # "cuda" or "cpu"
    vram_budget_mib: float | None
    window_s: float
    batch_size: int
    fits: bool                       # one window of the shortest length fits the budget
    gpu_name: str | None = None
    vram_free_mib: int | None = None
    vram_total_mib: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def required_free_mib(info, window_s: float = WINDOW_CHOICES_S[-1]) -> float:
    """Free VRAM below which this candidate is not expected to run even one short window."""
    return info.vram_base_mib + info.vram_per_window_s_mib * window_s + RESERVE_MIB


def plan_for(info, free_mib: float | None, total_mib: float | None = None, *, gpu_name: str | None = None) -> GpuPlan:
    """Window length and batch size for ``info`` (a ``CandidateInfo``) given the free VRAM."""
    if not free_mib:
        return GpuPlan("cpu", None, WINDOW_CHOICES_S[0], 1, False, gpu_name, None, total_mib,
                       ["no usable GPU memory reading; sizing is not applied"])
    budget = max(0.0, float(free_mib) - RESERVE_MIB)
    notes: list[str] = []
    window_s = None
    for w in WINDOW_CHOICES_S:
        if budget >= info.vram_base_mib + info.vram_per_window_s_mib * w:
            window_s = w
            break
    fits = window_s is not None
    if not fits:
        window_s = WINDOW_CHOICES_S[-1]
        notes.append(f"{free_mib:.0f} MiB free is below the estimated {required_free_mib(info):.0f} MiB "
                     "needed for one short window; extraction is expected to run out of memory")
    elif window_s != WINDOW_CHOICES_S[0]:
        notes.append(f"window shortened to {window_s:g} s to fit the free VRAM")
    per = max(1.0, info.vram_per_window_s_mib * window_s)
    batch = max(1, min(MAX_BATCH, int((budget - info.vram_base_mib) // per)))
    return GpuPlan("cuda", budget, window_s, batch, fits, gpu_name, int(free_mib),
                   int(total_mib) if total_mib else None, notes)


def _env_number(env, name: str, cast):
    raw = (env.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, not {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def hybrid_overrides(info, *, env=None, detection: dict | None = None) -> dict:
    """Keyword arguments for ``HybridConfig`` chosen from the GPU, then from explicit settings.

    ``FOCUS_OVERLAP_VRAM_BUDGET_MIB``, ``FOCUS_OVERLAP_WINDOW_S`` and ``FOCUS_OVERLAP_BATCH_SIZE`` win
    over detection. With no usable GPU and no settings the result is empty (the defaults apply).
    """
    env = os.environ if env is None else env
    det = detection if detection is not None else detect()
    kw: dict = {}
    plan = None
    if det["usable"]:
        plan = plan_for(info, det["vram_free_mib"], det["vram_total_mib"], gpu_name=det["device"])
        kw = {"vram_budget_mib": plan.vram_budget_mib, "window_s": plan.window_s}
    budget = _env_number(env, "FOCUS_OVERLAP_VRAM_BUDGET_MIB", float)
    window = _env_number(env, "FOCUS_OVERLAP_WINDOW_S", float)
    batch = _env_number(env, "FOCUS_OVERLAP_BATCH_SIZE", int)
    if budget is not None:
        kw["vram_budget_mib"] = budget
    if window is not None:
        kw["window_s"] = window
    if batch is not None:
        kw["batch_size"] = batch
    if kw:
        kw["plan"] = {"source": "settings" if (budget or window or batch) else "detected",
                      "gpu": plan.as_dict() if plan else None,
                      "overrides": {k: v for k, v in (("vram_budget_mib", budget), ("window_s", window),
                                                      ("batch_size", batch)) if v is not None}}
    return kw
