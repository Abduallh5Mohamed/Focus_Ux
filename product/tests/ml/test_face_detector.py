"""Detection-only face backend: no Dolphin weights, honest detector labels."""
import sys
import types

import pytest

from focus_ml.config import AdapterConfig
from focus_ml.errors import ModelUnavailableError
from focus_ml.face_detector import HAAR, LEGACY, DetectionOnlyBackend, safe_reason
from focus_ml.runtime import LocalEngine

BOX = [10.0, 20.0, 110.0, 140.0, 0.99]


@pytest.fixture
def legacy_source(tmp_path, monkeypatch):
    """A model source holding only face_detection_utils (no Inference.py, no weights)."""
    (tmp_path / "face_detection_utils.py").write_text(
        "def detect_faces(frame, threshold=0.9, allow_upscaling=False):\n"
        f"    return [{BOX!r}], None\n")
    monkeypatch.delitem(sys.modules, "face_detection_utils", raising=False)
    yield tmp_path
    sys.modules.pop("face_detection_utils", None)


def fake_cv2(*, empty=False, boxes=((12, 22, 100, 118),)):
    class Cascade:
        def __init__(self, path):
            self.path = path

        def empty(self):
            return empty

        def detectMultiScale(self, gray, **kwargs):
            return list(boxes)

    return types.SimpleNamespace(
        data=types.SimpleNamespace(haarcascades="/site/cv2/data/"),
        CascadeClassifier=Cascade, COLOR_RGB2GRAY=7, cvtColor=lambda frame, code: frame)


def test_detection_works_without_dolphin_weights_or_lip_engine(legacy_source, tmp_path, monkeypatch):
    config = AdapterConfig(model_source=str(legacy_source), model_cache=str(tmp_path / "missing"))
    engine = LocalEngine(config)
    monkeypatch.setattr(engine.adapter, "load_models", lambda *a, **k: pytest.fail("Dolphin weights loaded"))
    monkeypatch.setattr(engine.isolation, "check_ready", lambda: pytest.fail("lip engine checked"))
    name, detect = engine._detector()
    assert name == LEGACY and engine.models is None
    assert detect(None)[0] == [BOX]
    assert engine.face_detector_status() == {"detector": LEGACY, "error": None}


def test_haar_fallback_is_labelled_and_keeps_the_legacy_reason(tmp_path):
    backend = DetectionOnlyBackend(AdapterConfig(model_source=str(tmp_path)), cv2_module=fake_cv2()).load()
    assert backend.name == HAAR
    boxes, _ = backend.detect_faces(object(), threshold=0.9, allow_upscaling=False)
    assert boxes == [[12.0, 22.0, 112.0, 140.0, 1.0]]
    assert "Dolphin face detector" in backend.status()["error"]
    assert str(tmp_path) not in backend.status()["error"]


def test_every_detector_failing_raises_with_a_path_free_reason(tmp_path):
    backend = DetectionOnlyBackend(AdapterConfig(model_source=str(tmp_path)), cv2_module=fake_cv2(empty=True))
    with pytest.raises(ModelUnavailableError) as caught:
        backend.load()
    assert "no face detector" in caught.value.message
    assert "Haar" in caught.value.detail and "Dolphin" in caught.value.detail
    assert backend.name is None and backend.status()["error"] == caught.value.detail


def test_visibility_uses_the_detection_only_path(monkeypatch):
    from focus_ml import adapter
    from focus_ml.voice import visibility

    engine = LocalEngine(AdapterConfig())
    monkeypatch.setattr(engine, "initialize", lambda: pytest.fail("full initialization used"))
    calls = []
    monkeypatch.setattr(engine, "_detector", lambda: ("opencv_haar", lambda f, threshold, allow_upscaling: (
        calls.append(f) or [[10.0, 10.0, 110.0, 110.0]], None)))
    monkeypatch.setattr(adapter, "_bgr_to_rgb", lambda frame: frame)
    monkeypatch.setattr(visibility, "read_samples", lambda path: iter([(0, "a"), (500, "b")]))
    spans = engine.face_visibility("clip.mp4", (10, 10, 100, 100), (640, 360))
    assert calls == ["a", "b"] and spans == [{"start_ms": 0, "end_ms": 1000}]


def test_safe_reason_removes_paths_and_bounds_length():
    text = safe_reason("ImportError: cannot open C:\\models\\x\\a.py and /home/u/b.py " + "x" * 500)
    assert "models" not in text and "/home" not in text and "<path>" in text and len(text) <= 300
