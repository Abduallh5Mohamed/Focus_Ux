"""One read-only report for "can this computer run the local GPU worker, and with what settings".

Combines GPU detection (``hardware``), the WeSep sizing plan, the model folders, the checkpoints and,
optionally, the connection to a website. It loads no model, downloads nothing and measures no speed.
``ready`` means the prerequisites are in place; it is not an inference or quality result.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from . import hardware
from .local_paths import focus_home, missing_model_assets, model_environment

OVERLAP_CANDIDATE = "wesep_bsrnn"


def _candidate(name: str):
    from .overlap.candidates import build_candidate
    return build_candidate(name, embedder=SimpleNamespace(name="probe"))


def collect(url: str | None = None, local_api: bool = False, *, detection: dict | None = None,
            env=None, candidate: str = OVERLAP_CANDIDATE) -> dict:
    import os
    env = os.environ if env is None else env
    det = detection if detection is not None else hardware.detect()
    checks: list[dict] = []

    def add(name: str, ok: bool | None, detail: str):
        checks.append({"name": name, "status": "pass" if ok else ("unknown" if ok is None else "fail"),
                       "detail": detail})

    add("python", True, f"{sys.executable} (Python {sys.version.split()[0]})")
    pt = det["pytorch"]
    add("pytorch", bool(pt), f"torch {pt['version']}, CUDA build {pt['cuda_build']}" if pt
        else "PyTorch is not importable in this Python environment")
    add("nvidia_gpu", bool(det["device"]), f"{det['device']} (driver {det['driver']})" if det["device"]
        else "no NVIDIA GPU or driver found")
    add("cuda_usable", det["usable"], "PyTorch can use the GPU" if det["usable"] else "; ".join(det["blockers"]))

    plan = None
    info = None
    try:
        info = _candidate(candidate).info
    except Exception as exc:   # report, do not hide
        add("extractor_info", False, f"{type(exc).__name__}: {exc}")
    if det["usable"] and info is not None:
        plan = hardware.plan_for(info, det["vram_free_mib"], det["vram_total_mib"], gpu_name=det["device"])
        need = hardware.required_free_mib(info)
        add("free_vram", plan.fits, f"{det['vram_free_mib']} of {det['vram_total_mib']} MiB free; "
            f"estimated need for {candidate}: {need:.0f} MiB (an estimate from the model's size, not a measurement)")
    elif info is not None:
        add("free_vram", None, "not measurable without a usable GPU")

    settings = model_environment(focus_home(None, env), env)
    problems = missing_model_assets(settings)
    add("lip_model_assets", not problems, "; ".join(problems) if problems else
        f"Dolphin source {settings['FOCUS_MODEL_SOURCE']}, cache {settings['FOCUS_MODEL_CACHE']} "
        "(presence only; does not prove the models are complete)")

    from .overlap.candidates import candidate_status
    from .voice.weights import voice_home, weight_status
    weights = weight_status()
    add("voice_weights", all(weights.values()), f"{voice_home()}: " + ", ".join(
        f"{repo} {'present' if ok else 'MISSING'}" for repo, ok in weights.items()))
    status = candidate_status().get(candidate, {"ready": False, "blocker": {"message": "unknown candidate"}})
    blocker = status["blocker"] or {}
    add("wesep_checkpoint", status["ready"], "WeSep weights and pinned code present" if status["ready"]
        else f"{blocker.get('kind', '')}: {blocker.get('message', '')}".strip(": "))

    connection = {"checked": False, "mode": "local website (this computer hosts it)"}
    if url:
        from .voice.readiness import worker_connection
        connection = worker_connection(url, local_api) | {"mode": "remote website, local GPU worker"}
        add("worker_connection", connection.get("ok", False), connection["detail"])

    required = {"cuda_usable", "free_vram", "lip_model_assets", "voice_weights", "worker_connection"}
    overlap_required = {"wesep_checkpoint"}
    base_ok = all(c["status"] == "pass" for c in checks if c["name"] in required)
    return {
        "ready_for_audio_only_worker": base_ok,
        "ready_for_wesep_overlap": base_ok and all(c["status"] == "pass" for c in checks
                                                     if c["name"] in overlap_required),
        "checks": checks, "detection": {k: v for k, v in det.items() if k != "probes"},
        "sizing": plan.as_dict() if plan else None, "sizing_basis": "estimate from model size; not measured",
        "connection": connection,
        "not_measured": ["GPU inference speed", "GPU inference quality", "peak VRAM of a real run",
                         "camera latency"],
    }


def render(report: dict) -> str:
    lines = []
    for c in report["checks"]:
        mark = {"pass": "PASS", "fail": "FAIL", "unknown": "----"}[c["status"]]
        lines.append(f"[{mark}] {c['name']}: {c['detail']}")
    plan = report["sizing"]
    if plan:
        lines.append(f"Sizing for WeSep (estimate): window {plan['window_s']:g} s, batch {plan['batch_size']}, "
                     f"VRAM budget {plan['vram_budget_mib']:.0f} MiB." + "".join(" " + n for n in plan["notes"]))
    lines.append("Audio-only worker prerequisites: " + ("ready" if report["ready_for_audio_only_worker"] else "NOT ready"))
    lines.append("WeSep overlap prerequisites: " + ("ready" if report["ready_for_wesep_overlap"] else "NOT ready"))
    lines.append("Not measured by this check: " + ", ".join(report["not_measured"]) + ".")
    return "\n".join(lines)
