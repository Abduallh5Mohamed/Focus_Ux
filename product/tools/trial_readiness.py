"""Read-only Windows trial checks. Never installs packages or downloads weights."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GPU_PROBE = """
import json, torch
available = torch.cuda.is_available()
print("FOCUS_GPU_INFO=" + json.dumps({
    "pytorch": torch.__version__, "cuda": torch.version.cuda,
    "available": available,
    "device": torch.cuda.get_device_name(0) if available else None
}))
"""


def run(command: list[str], timeout: int = 30):
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, check=False,
    )


def gpu_python(focus: Path) -> Path | None:
    """The Python that has PyTorch: FOCUS_PYTHON, else a .venv under the model folder, else the
    project's own .venv-ml. Presence only; nothing is run."""
    explicit = os.environ.get("FOCUS_PYTHON")
    candidates = ([Path(explicit)] if explicit else
                  [focus / ".venv/Scripts/python.exe", ROOT / ".venv-ml/Scripts/python.exe"])
    return next((c for c in candidates if c.is_file()), None)


def collect(focus: Path | None, *, test_uploads: bool = False,
            require_continuous: bool = False) -> dict:
    """``focus`` is the folder with Dolphin/ and cache/. ``None`` means the project folder itself."""
    own_folder = focus is None
    focus = ROOT if own_folder else focus
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})

    windows = platform.system() == "Windows"
    add("windows", windows, "Native Windows required" if not windows else "Windows")
    add("trial_python", sys.version_info[:2] == (3, 12), platform.python_version())
    local_python = ROOT / ".venv" / "Scripts" / "python.exe"
    add("isolated_api_python", local_python.is_file()
        and Path(sys.executable).resolve() == local_python.resolve(),
        "Run with this trial checkout's .venv/Scripts/python.exe")
    add("separate_checkout", own_folder or (ROOT.resolve() != focus.resolve()
        and focus.resolve() not in ROOT.resolve().parents),
        "The trial checkout must be outside a separate model installation"
        if not own_folder else "Models are read from the project folder (set FOCUS_HOME to use another)")

    revision = None
    for name, args in (
        ("git", ["--version"]), ("node", ["--version"]),
        ("uv", ["--version"]), ("ffmpeg", ["-version"]), ("ffprobe", ["-version"]),
    ):
        executable = shutil.which(name)
        if not executable:
            add(name, False, "Not found on PATH")
            continue
        try:
            result = run([executable, *args])
            ok = result.returncode == 0
            version = result.stdout.splitlines()[0] if result.stdout else "No version returned"
            if name == "node" and ok:
                major, minor, *_ = version.lstrip("v").split(".")
                ok = int(major) == 22 and int(minor) >= 12
            add(name, ok, version)
            if name == "git":
                head = run([executable, "rev-parse", "HEAD"])
                if head.returncode == 0:
                    revision = head.stdout.strip()
        except (OSError, subprocess.TimeoutExpired, ValueError):
            add(name, False, "Version check failed or timed out")
    add("revision", revision is not None, revision or "Cannot identify trial revision")
    add("frontend_dependencies", (ROOT / "product/apps/web/node_modules/vite/package.json").is_file(),
        "Install frontend dependencies in the trial checkout before starting")

    for name, relative, directory in (
        ("dolphin_source", "Dolphin/Inference.py", False),
        ("mean_face", "Dolphin/assets/20words_mean_face.npy", False),
        ("hf_cache_directory", "cache/hf", True),
        ("torch_cache_directory", "cache/torch", True),
    ):
        asset = focus / relative
        add(name, asset.is_dir() if directory else asset.is_file(),
            "Presence check only; does not establish model completeness")

    python_with_torch = gpu_python(focus)
    add("gpu_python", python_with_torch is not None,
        "Presence only: FOCUS_PYTHON, <models>/.venv or .venv-ml in the project")

    for module in ("fastapi", "uvicorn", "httpx", "numpy", "pytest"):
        try:
            result = run([sys.executable, "-B", "-c",
                          f"import importlib; importlib.import_module('{module}')"])
            add(f"api_{module}", result.returncode == 0, "Import check in trial Python")
        except (OSError, subprocess.TimeoutExpired):
            add(f"api_{module}", False, "Import failed or timed out")

    gpu = None
    if windows and python_with_torch is not None:
        try:
            result = run([str(python_with_torch), "-B", "-c", GPU_PROBE], timeout=60)
            marker = next((line.removeprefix("FOCUS_GPU_INFO=")
                           for line in result.stdout.splitlines()
                           if line.startswith("FOCUS_GPU_INFO=")), None)
            gpu = json.loads(marker) if marker else None
            add("cuda", result.returncode == 0 and bool(gpu and gpu.get("available")),
                "Read-only CUDA check; no inference benchmark")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            add("cuda", False, "CUDA probe failed or timed out; nothing was installed or changed")
    else:
        checks.append({"name": "cuda", "status": "skip",
                       "detail": "Requires native Windows and a Python with PyTorch (FOCUS_PYTHON)"})

    if require_continuous:
        for relative in ("product/packages/ml/focus_ml/live_stream_backend.py",
                         "product/tools/stream_gate.py"):
            add(relative, (ROOT / relative).is_file(),
                "Source presence only; real-device acceptance still required")

    upload_tests = "not_run"
    if test_uploads:
        if not windows:
            upload_tests = "blocked"
            add("native_upload_tests", False, "Run this check on native Windows")
        elif not all(c["status"] == "pass" for c in checks
                     if c["name"] in ("isolated_api_python", "separate_checkout")):
            upload_tests = "blocked"
            add("native_upload_tests", False, "Fix isolated trial checkout checks first")
        else:
            try:
                # Tests use the trial interpreter, never the original ML interpreter.
                result = run([
                    sys.executable, "-B", "-m", "pytest", "-q",
                    "product/tests/api/test_upload_ownership.py",
                    "product/tests/api/test_temp_storage.py",
                ], timeout=180)
                upload_tests = "pass" if result.returncode == 0 else "fail"
                add("native_upload_tests", result.returncode == 0,
                    "Focused Windows ownership/storage tests; exit " + str(result.returncode))
            except (OSError, subprocess.TimeoutExpired):
                upload_tests = "fail"
                add("native_upload_tests", False, "Tests failed to start or timed out")

    return {
        "ready_for_manual_trial": all(c["status"] == "pass" for c in checks),
        "revision": revision, "checks": checks, "gpu": gpu,
        "upload_tests": upload_tests,
        "gpu_inference_acceptance": "not_measured",
        "camera_latency_acceptance": "not_measured",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--focus", type=Path, default=None,
                        help="Folder with Dolphin/ and cache/ (default: FOCUS_HOME, else the project folder)")
    parser.add_argument("--test-uploads", action="store_true")
    parser.add_argument("--require-continuous", action="store_true",
                        help="Also check that continuous-stream source has been integrated")
    args = parser.parse_args(argv)
    focus = args.focus or (Path(os.environ["FOCUS_HOME"]) if os.environ.get("FOCUS_HOME") else None)
    report = collect(focus, test_uploads=args.test_uploads,
                     require_continuous=args.require_continuous)
    # Report only known, non-secret metadata. Never dump subprocess stderr or env.
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready_for_manual_trial"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
