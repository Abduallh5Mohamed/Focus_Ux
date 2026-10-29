"""Import safety is itself a test target: importing focus_ml must not import
torch/cv2/face_alignment, must not change cwd and must not mutate sys.path.
torch/cv2 are absent from the test interpreter on purpose."""
import os
import subprocess
import sys

import pytest

PACKAGE_PARENT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "ml")
)
FOCUS_ML_ON_PATH = os.path.join(PACKAGE_PARENT, "focus_ml")


def _run_import_probe() -> subprocess.CompletedProcess:
    code = (
        "import json, os, sys\n"
        f"sys.path.insert(0, r'{PACKAGE_PARENT}')\n"
        "before_cwd = os.getcwd()\n"
        "before_path = list(sys.path)\n"
        "import focus_ml\n"
        "print(json.dumps({"
        "'cwd_ok': os.getcwd() == before_cwd, "
        "'path_ok': sys.path == before_path, "
        "'no_version': not hasattr(focus_ml, '__version__'), "
        "'torch_loaded': 'torch' in sys.modules, "
        "'cv2_loaded': 'cv2' in sys.modules, "
        "'fa_loaded': 'face_alignment' in sys.modules, "
        "'sf_loaded': 'soundfile' in sys.modules, "
        "'numpy_loaded': 'numpy' in sys.modules,"
        "}))\n"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        timeout=120,
    )


def test_import_focus_ml_is_side_effect_free():
    completed = _run_import_probe()
    assert completed.returncode == 0, completed.stderr
    report = __import__("json").loads(completed.stdout.strip().splitlines()[-1])
    assert report["cwd_ok"] is True
    assert report["path_ok"] is True
    assert report["no_version"] is True


def test_import_focus_ml_does_not_load_heavy_modules():
    completed = _run_import_probe()
    assert completed.returncode == 0, completed.stderr
    report = __import__("json").loads(completed.stdout.strip().splitlines()[-1])
    for heavy in ("torch_loaded", "cv2_loaded", "fa_loaded", "sf_loaded", "numpy_loaded"):
        assert report[heavy] is False, f"{heavy} unexpectedly loaded at import time"


def test_package_root_does_not_mutate_sys_path_in_process():
    sys.path.insert(0, PACKAGE_PARENT)
    before = list(sys.path)
    __import__("focus_ml")
    assert sys.path == before, "focus_ml import mutated sys.path"
    assert str(FOCUS_ML_ON_PATH) not in sys.path
    for entry in sys.path:
        assert "Dolphin" not in entry
