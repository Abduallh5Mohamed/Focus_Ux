"""GPU preflight for one overlap-extraction candidate. Read-only: loads no model,
downloads nothing. Every check is "pass", "fail" or "unknown" with the observed evidence;
nothing is assumed. ``probes`` lets tests inject observations."""
from __future__ import annotations

import importlib.util

from ..hardware import plan_for, real_probes, required_free_mib
from .base import BlockedError

# import name per candidate (what the adapter needs besides torch)
DEPENDENCIES = {
    "wesep_bsrnn": ("yaml", "soundfile", "scipy"),
    "usef_tse": ("yaml", "soundfile", "scipy"),
    "spexplus": ("yaml", "soundfile", "scipy"),
    "mossformer2_ss_voiceprint": ("soundfile", "scipy"),
    "sepformer_libri3mix": ("speechbrain", "hyperpyyaml", "soundfile"),
    "pyannote_ami_pixit": ("pyannote.audio", "soundfile"),
}


def _check(name: str, status: str, detail: str, **extra) -> dict:
    return {"name": name, "status": status, "detail": detail, **extra}


def _candidate_info(candidate: str):
    try:
        from types import SimpleNamespace

        from .candidates import build_candidate
        return build_candidate(candidate, embedder=SimpleNamespace(name="probe")).info
    except Exception:   # unknown candidate or missing optional code: the dependency checks report it
        return None


def run_preflight(candidate: str, *, probes: dict | None = None, ready=None,
                  has_module=None, min_free_mib: float | None = None) -> dict:
    """``ready`` is a callable raising BlockedError when weights/code are missing
    (default: the candidate's own ``check_ready``)."""
    pr = real_probes() if probes is None else probes
    has_module = has_module or (lambda m: importlib.util.find_spec(m.split(".")[0]) is not None)
    checks = []
    t = pr.get("torch")
    if not t:
        checks.append(_check("pytorch", "fail", "PyTorch is not importable in this Python environment"))
    else:
        checks.append(_check("pytorch", "pass", f"torch {t['version']} (CUDA build {t['cuda_build']})"))
        if not t["cuda_build"]:
            checks.append(_check("pytorch_cuda_build", "fail", "this PyTorch is a CPU-only build"))
        else:
            checks.append(_check("pytorch_cuda_build", "pass", f"CUDA {t['cuda_build']}"))
        checks.append(_check("cuda_available", "pass" if t["cuda_available"] else "fail",
                             "torch.cuda.is_available() = " + str(t["cuda_available"])))
    gpu = pr.get("gpu")
    drv = pr.get("driver")
    if gpu:
        checks.append(_check("gpu_model", "pass", f"{gpu['name']} (compute capability "
                             f"{gpu['capability'][0]}.{gpu['capability'][1]})"))
        free = gpu["free_mib"]
        info = _candidate_info(candidate)
        need = min_free_mib if min_free_mib is not None else (required_free_mib(info) if info else 0)
        extra = {}
        if info:
            plan = plan_for(info, free, gpu["total_mib"], gpu_name=gpu["name"])
            extra["sizing"] = plan.as_dict()
        checks.append(_check("free_vram", "pass" if free >= need else "fail",
                             f"{free} MiB free of {gpu['total_mib']} MiB (estimated need >= {need:.0f} MiB; "
                             "an estimate from the model's size, not a measurement)", free_mib=free, **extra))
        if t and t["cuda_build"] and gpu["capability"][0] < 5:
            checks.append(_check("pytorch_gpu_compat", "fail", "GPU capability is older than PyTorch CUDA builds support"))
        else:
            checks.append(_check("pytorch_gpu_compat", "pass", "PyTorch sees the GPU through its CUDA build"))
    else:
        detail = (f"driver reports {drv['name']} ({drv['free_mib']} MiB free) but torch cannot use it"
                  if drv else "no NVIDIA GPU or driver was found (nvidia-smi absent)")
        checks.append(_check("gpu_model", "fail", detail))
        checks.append(_check("free_vram", "unknown", "not measurable without a CUDA-capable torch"))
        checks.append(_check("pytorch_gpu_compat", "unknown", "needs torch + GPU"))
    missing = [m for m in DEPENDENCIES.get(candidate, ()) if not has_module(m)]
    checks.append(_check("dependencies", "fail" if missing else "pass",
                         ("missing: " + ", ".join(missing)) if missing else "all adapter packages importable"))
    try:
        if ready is None:
            from .candidates import build_candidate
            from types import SimpleNamespace
            ready = build_candidate(candidate, embedder=SimpleNamespace(name="probe")).check_ready
        ready()
        checks.append(_check("checkpoint", "pass", "weights and pinned code are present"))
    except BlockedError as exc:
        checks.append(_check("checkpoint", "fail", f"{exc.kind}: {exc.message}"))
    ok = all(c["status"] == "pass" for c in checks)
    return {"candidate": candidate, "ok": ok, "checks": checks, "probes": pr,
            "verdict": "ready for real inference" if ok else "NOT ready: " + ", ".join(
                c["name"] for c in checks if c["status"] != "pass")}
