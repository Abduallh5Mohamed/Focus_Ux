"""CPU tests for the readiness reporter, not Windows/GPU acceptance evidence."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def checker(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "tools/trial_readiness.py"
    spec = importlib.util.spec_from_file_location("trial_readiness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    return module


def test_linux_never_runs_original_python_or_native_tests(checker, tmp_path, monkeypatch):
    monkeypatch.setattr(checker.platform, "system", lambda: "Linux")
    called = []

    def run(command, timeout=30):
        called.append(command)
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(checker, "run", run)
    report = checker.collect(tmp_path, test_uploads=True)
    assert not report["ready_for_manual_trial"]
    assert report["upload_tests"] == "blocked"
    assert report["gpu_inference_acceptance"] == "not_measured"
    assert report["camera_latency_acceptance"] == "not_measured"
    assert all("pytest" not in command and checker.GPU_PROBE not in command for command in called)


def test_continuous_mode_reports_missing_integration(checker, tmp_path, monkeypatch):
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    report = checker.collect(tmp_path / "original", require_continuous=True)
    assert any(c["name"].endswith("stream_gate.py") and c["status"] == "fail"
               for c in report["checks"])
    assert not report["ready_for_manual_trial"]


def test_original_checkout_cannot_be_used_for_trial(checker, tmp_path, monkeypatch):
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=""))
    report = checker.collect(tmp_path)
    separate = next(c for c in report["checks"] if c["name"] == "separate_checkout")
    assert separate["status"] == "fail"


def test_cli_failure_is_explicit_and_reports_no_raw_errors(checker, monkeypatch, capsys):
    monkeypatch.setattr(checker, "collect", lambda *a, **k: {
        "ready_for_manual_trial": False, "checks": [],
        "gpu_inference_acceptance": "not_measured",
    })
    assert checker.main([]) == 2
    assert json.loads(capsys.readouterr().out)["ready_for_manual_trial"] is False


@pytest.mark.parametrize("pytest_exit", [0, 1])
def test_mock_windows_gpu_and_upload_checks(checker, tmp_path, monkeypatch, pytest_exit):
    root = tmp_path / "trial"
    focus = tmp_path / "original"
    local_python = root / ".venv/Scripts/python.exe"
    for path in (
        local_python, focus / ".venv/Scripts/python.exe",
        focus / "Dolphin/Inference.py", focus / "Dolphin/assets/20words_mean_face.npy",
        root / "product/apps/web/node_modules/vite/package.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for name in ("hf", "torch"):
        (focus / "cache" / name).mkdir(parents=True)
    monkeypatch.setattr(checker, "ROOT", root)
    monkeypatch.setattr(checker, "sys",
                        SimpleNamespace(executable=str(local_python), version_info=(3, 12)))
    monkeypatch.setattr(checker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(checker.shutil, "which", lambda name: name)
    calls = []

    def run(command, timeout=30):
        calls.append(command)
        if checker.GPU_PROBE in command:
            return SimpleNamespace(returncode=0, stdout='FOCUS_GPU_INFO={"available":true}')
        if "pytest" in command:
            assert command[0] == str(local_python)
            return SimpleNamespace(returncode=pytest_exit, stdout="")
        return SimpleNamespace(returncode=0, stdout="v22.12.0\n")

    monkeypatch.setattr(checker, "run", run)
    report = checker.collect(focus, test_uploads=True)
    assert report["ready_for_manual_trial"] is (pytest_exit == 0)
    assert report["upload_tests"] == ("pass" if pytest_exit == 0 else "fail")
    assert report["gpu_inference_acceptance"] == "not_measured"
    assert all("pip" not in command and "install" not in command for command in calls)
