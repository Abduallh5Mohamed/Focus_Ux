"""Nothing in the local launchers may assume a drive, folder or GPU model."""
import re
from pathlib import Path

from focus_ml.local_paths import PROJECT_ROOT, focus_home, missing_model_assets, model_environment

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def test_launchers_have_no_fixed_paths_or_gpu_model():
    for path in list(TOOLS.glob("*.cmd")) + list(TOOLS.glob("*.ps1")) + list(TOOLS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"A:[\\/]+focus", text, re.I), path.name
    for path in TOOLS.glob("*.cmd"):
        text = path.read_text(encoding="ascii")
        if "%FOCUS_PY%" in text and path.name != "focus_env.cmd":
            assert 'call "%~dp0focus_env.cmd"' in text, path.name
        assert "venv\\Scripts\\python.exe" not in text or path.name == "focus_env.cmd", path.name


def test_focus_home_and_overrides(tmp_path):
    assert focus_home(None, {}) == PROJECT_ROOT
    assert focus_home(None, {"FOCUS_HOME": str(tmp_path)}) == tmp_path.resolve()
    env = model_environment(tmp_path, {})
    assert env["FOCUS_MODEL_SOURCE"] == str(tmp_path / "Dolphin") and env["HF_HOME"] == env["FOCUS_MODEL_CACHE"]
    env = model_environment(tmp_path, {"FOCUS_MODEL_CACHE": "/c", "FOCUS_MODEL_SOURCE": "/s", "FOCUS_TORCH_HOME": "/t"})
    assert (env["HF_HOME"], env["FOCUS_MODEL_SOURCE"], env["TORCH_HOME"]) == ("/c", "/s", "/t")
    assert len(missing_model_assets(model_environment(tmp_path, {}))) == 2
    (tmp_path / "Dolphin").mkdir(); (tmp_path / "Dolphin/Inference.py").touch(); (tmp_path / "cache/hf").mkdir(parents=True)
    assert missing_model_assets(model_environment(tmp_path, {})) == []


def test_gpu_report_without_gpu_is_honest(tmp_path):
    from focus_ml import gpu_report, hardware
    det = hardware.detect({"torch": None})
    rep = gpu_report.collect(detection=det, env={"FOCUS_HOME": str(tmp_path)})
    assert not rep["ready_for_audio_only_worker"] and not rep["ready_for_wesep_overlap"]
    assert "GPU inference speed" in rep["not_measured"] and rep["sizing"] is None
    assert "NOT ready" in gpu_report.render(rep)
