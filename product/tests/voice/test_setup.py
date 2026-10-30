import importlib.util
import pathlib

import pytest

TOOLS = pathlib.Path(__file__).resolve().parents[2] / "tools" / "setup_voice.py"
spec = importlib.util.spec_from_file_location("setup_voice", TOOLS)
setup_voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_voice)

from focus_ml.voice.weights import REQUIRED, weight_dir, weight_status  # noqa: E402


def test_plan_install_protects_torch_and_numpy():
    report = {"install": [{"metadata": {"name": "torch", "version": "9"}},
                          {"metadata": {"name": "speechbrain", "version": "1"}}]}
    wanted, blocked = setup_voice.plan_install(report)
    assert wanted == ["speechbrain==1"] and blocked == ["torch==9"]


def test_cancel_downloads_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    assert setup_voice.main(tmp_path) == 1
    assert not (tmp_path / "weights").exists() and not (tmp_path / "site").exists()
    assert "Hugging Face" in capsys.readouterr().out      # the terms step is explained first


def test_download_marks_complete_only_when_files_present(tmp_path):
    def fake(repo_id, local_dir, token=None):
        d = pathlib.Path(local_dir)
        d.mkdir(parents=True, exist_ok=True)
        for f in REQUIRED[repo_id]:
            (d / f).write_text("x")
    setup_voice.download(tmp_path, "t", snapshot_download=fake)
    assert all(weight_status(tmp_path).values())

    def partial(repo_id, local_dir, token=None):
        pathlib.Path(local_dir).mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError, match="incomplete"):
        setup_voice.download(tmp_path / "b", None, snapshot_download=partial)
    assert not any(weight_status(tmp_path / "b").values())
