"""Small allowlisted source bundle. Never package caches, media or secrets."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.responses import Response

from .config import PRODUCT_ROOT


# Needed by the audio-only worker, including overlap extraction and its validation tools.
REQUIRED_PACKAGE_DIRS = ("voice", "overlap")
OVERLAP_TOOLS = ("overlap_minimal_infer.py", "overlap_e2e.py", "overlap_acceptance.py",
                 "Overlap-Validate.cmd", "Overlap-Preflight.cmd", "Setup-Overlap.cmd", "setup_overlap.py",
                 "Start-Worker-Checkout.cmd")
# Finds the Python with PyTorch and checks the GPU; every .cmd calls focus_env.cmd.
GPU_TOOLS = ("focus_env.cmd", "Focus-Check-GPU.cmd", "gpu_check.py")
REFUSAL = ("This worker ZIP is incomplete and cannot run the audio-only worker. "
           "Use the full repo checkout instead: update it with git pull --ff-only and run "
           "product\\tools\\Start-Worker-Checkout.cmd.")


def missing_parts() -> list[str]:
    root = PRODUCT_ROOT / "packages/ml/focus_ml"
    missing = [d for d in REQUIRED_PACKAGE_DIRS if not (root / d / "__init__.py").is_file()]
    missing += [t for t in OVERLAP_TOOLS + GPU_TOOLS if not (PRODUCT_ROOT / "tools" / t).is_file()]
    return missing


def worker_kit() -> Response:
    missing = missing_parts()
    if missing:   # never ship a ZIP that starts and then fails on a missing module
        return Response(REFUSAL + " Missing: " + ", ".join(missing), status_code=503,
                        media_type="text/plain")
    output = io.BytesIO()
    tools = PRODUCT_ROOT / "tools"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (
            "Setup-Key.cmd", "Start-Worker.cmd", "Check-Connection.cmd",
            "Setup-Preview-Access.cmd", "Setup-ClearerVoice.cmd",
        ):
            archive.write(tools / name, name)
        archive.write(tools / "windows_worker.py", "product/tools/windows_worker.py")
        archive.write(tools / "asr_engine.py", "product/tools/asr_engine.py")
        for name in (
            "setup_clearervoice.py", "engine_harness.py", "engine_compare.py",
            "engine_gate.py", "three_speaker_set.py",
        ):
            archive.write(tools / name, "product/tools/" + name)
        archive.write(tools / "stream_worker.py", "product/tools/stream_worker.py")
        archive.write(tools / "compare_isolation.py", "product/tools/compare_isolation.py")
        archive.writestr("product/tools/__init__.py", "")
        # Continuous live path: dependency-free wire format shared with the API.
        archive.writestr("product/services/__init__.py", "")
        archive.writestr("product/services/worker/__init__.py", "")
        archive.write(PRODUCT_ROOT / "services/worker/stream_proto.py",
                      "product/services/worker/stream_proto.py")
        for name in GPU_TOOLS:
            archive.write(tools / name, name if name.endswith(".cmd") else "product/tools/" + name)
        for name in OVERLAP_TOOLS:
            if name != "Start-Worker-Checkout.cmd":
                archive.write(tools / name, name if name.endswith(".cmd") else "product/tools/" + name)
        base = PRODUCT_ROOT / "packages/ml/focus_ml"
        for path in sorted(base.glob("*.py")) + [
                p for d in REQUIRED_PACKAGE_DIRS for p in sorted((base / d).glob("*.py"))]:
            archive.write(path, str(path.relative_to(PRODUCT_ROOT.parent)))
        archive.writestr(
            "READ-ME.txt",
            "FOCUS Windows worker\n\n"
            "Uses the Python that has CUDA PyTorch (found by focus_env.cmd, or set FOCUS_PYTHON) and\n"
            "the Dolphin/cache folders from FOCUS_HOME (default: this folder), read-only. Any NVIDIA GPU.\n"
            "Run Focus-Check-GPU.cmd first: it reports GPU, driver, free VRAM, Python and model folders.\n"
            "No package installs, weight downloads, listening ports or tunnels.\n"
            "1. Extract this ZIP into a NEW folder.\n"
            "2. Run Setup-Key.cmd. It copies a private worker key to the clipboard.\n"
            "3. Paste ONLY into Replit Secrets named FOCUS_WORKER_TOKEN, never chat.\n"
            "4. Configure FOCUS_INFERENCE_MODE=remote and restart the web application.\n"
            "5. AFTER the task is merged, run Start-Worker.cmd. Enter the MAIN\n"
            "   app HTTPS URL shown in Networking, not the isolated task preview.\n"
            "6. Keep the window open. Models must load before uploading a clip.\n\n"
            "The default engine is audio_only (voice enrollment, no lip data). The lip-based engines\n"
            "stay available through FOCUS_ISOLATION_ENGINE on the server and --engine here.\n"
            "Optional stronger lip-based isolation engines (off by default):\n"
            "Run Setup-ClearerVoice.cmd once and type yes. It uses its own folder\n"
            "(%LOCALAPPDATA%\\FocusClearerVoice). Then compare engines with\n"
            "product/tools/engine_compare.py and choose one with FOCUS_ISOLATION_ENGINE\n"
            "(dolphin, av_mossformer2 or separate_select). Details: docs/ISOLATION_ENGINES.md.\n\n"
            "If the connection fails:\n"
            "Run Check-Connection.cmd first; it does NOT load any GPU models.\n"
            "A task preview and the main Networking URL are different hosts.\n"
            "The main URL cannot serve new worker routes until the task is merged.\n"
            "A private Replit preview can redirect automated clients to sign-in.\n"
            "Use a separate Replit DEVELOPMENT external access token for that gate,\n"
            "saved locally with Setup-Preview-Access.cmd (hidden input).\n"
            "Never use the worker key as the preview access token or put either\n"
            "token in a URL/chat/screenshot. Preview access uses Authorization;\n"
            "application worker auth uses X-Focus-Worker-Token. Redirects remain blocked.\n\n"
            "Security/privacy:\n"
            "This key trusts this computer to process ALL website users' queued media.\n"
            "Keep it private. Remove/rotate the Replit secret to revoke access.\n"
            "Videos/audio are processed in temporary directories and removed after each task.\n"
            "Closing/stopping mid-task or a computer crash can leave temp files; "
            "remove abandoned focus-inference-* folders from Windows TEMP.\n"
            "Timeout/restart fails the current task; it is not silently replayed.\n"
            "The worker cannot access browser sessions or enumerate stored uploads.\n"
            "First-frame faces only. No voice-only tracking. Transcription uses faster-whisper from FOCUS_ASR_MODEL\n(local/cached model only; nothing is downloaded). Without it, text is reported unavailable.\n"
            "A successful connection is NOT proof of isolation quality; verify on real clips.\n"
            "Do not send private worker keys or original personal videos in chat.\n",
        )
    return Response(
        output.getvalue(), media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="focus-windows-worker.zip"',
            "Cache-Control": "no-store",
        },
    )
