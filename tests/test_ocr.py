"""保留 OCR 核心能力的行为回归：引擎适配、资源隔离与模板查找。"""

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.ocr.core import engine as ocr_engine
from app.ocr.core.resources import (
    OCRResources,
    get_resources,
    use_resources,
)
from tests.ocr_helpers import make_ocr_settings, ocr_result

CODE = "TEST"


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


@pytest.fixture
def resources(settings):
    resource = OCRResources(settings)
    with use_resources(resource):
        yield resource


def test_ocr_converts_rapidocr_output_to_boxes(resources):
    resources.engine = lambda image: ocr_result(
        ([[10, 10], [300, 10], [300, 40], [10, 40]], "监理单位：测试公司", 0.99),
        ([[20, 50], [80, 50], [80, 70], [20, 70]], "2026-10-31", 0.5),
    )
    boxes = ocr_engine.ocr(np.zeros((100, 100, 3), np.uint8))
    assert [b["s"] for b in boxes] == ["监理单位：测试公司", "2026-10-31"]
    assert [b["box"] for b in boxes] == [[10.0, 10.0, 300.0, 40.0], [20.0, 50.0, 80.0, 70.0]]
    assert boxes[0]["conf"] == pytest.approx(0.99)
    assert boxes[1]["conf"] == pytest.approx(0.5)


def test_ocr_empty_detection_returns_no_boxes(resources):
    resources.engine = lambda image: ocr_result()
    assert ocr_engine.ocr(np.zeros((10, 10, 3), np.uint8)) == []


def test_polygon_ocr_preserves_rotated_vertices(resources):
    polygon = ((10, 20), (100, 10), (105, 40), (15, 50))
    resources.engine = lambda image: ocr_result((polygon, "倾斜文字", 0.9))
    detections = ocr_engine.detect_text(np.zeros((100, 120, 3), np.uint8))
    assert detections[0].polygon == polygon
    assert detections[0].text == "倾斜文字"


@pytest.mark.parametrize("coordinate,confidence", [(float("nan"), 0.9), (10, float("inf"))])
def test_ocr_rejects_nonfinite_geometry_and_score(resources, coordinate, confidence):
    from app.ocr.core.resources import OCRModelError

    resources.engine = lambda image: ocr_result(
        ([[coordinate, 10], [100, 10], [100, 40], [10, 40]], "异常框", confidence)
    )
    with pytest.raises(OCRModelError):
        ocr_engine.ocr(np.zeros((100, 120, 3), np.uint8))


def test_engine_uses_ppocrv6_medium_and_ppocrv5_server_direction_model(settings, monkeypatch):
    import rapidocr

    captured = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs["params"])

    monkeypatch.setattr(rapidocr, "RapidOCR", FakeRapidOCR)
    with use_resources(OCRResources(settings)):
        ocr_engine.engine()

    assert captured["Global.model_root_dir"] == str(settings.ocr_model_root)
    assert captured["Det.model_type"] is rapidocr.ModelType.MEDIUM
    assert captured["Det.ocr_version"] is rapidocr.OCRVersion.PPOCRV6
    assert captured["Rec.model_type"] is rapidocr.ModelType.MEDIUM
    assert captured["Rec.ocr_version"] is rapidocr.OCRVersion.PPOCRV6
    assert captured["Cls.model_type"] is rapidocr.ModelType.SERVER
    assert captured["Cls.ocr_version"] is rapidocr.OCRVersion.PPOCRV5


def test_ocr_model_failure_returns_503(settings):
    from tests.test_ocr_journal import table_photo

    image = table_photo()
    cv2.imencode(".png", image)[1].tofile(str(settings.projects_root / "照片.png"))
    app = create_app(settings=settings)

    def broken_engine(image):
        # RapidOCR 3.x 在首次推理时才加载模型，下载失败发生在这里。
        raise RuntimeError("model download failed")

    with TestClient(app) as client:
        app.state.ocr_resources.engine = broken_engine
        response = client.post("/ocr/journal", json={"path": "projects/照片.png"})
    assert response.status_code == 503
    assert "model download failed" not in response.json()["detail"]


def test_settings_paths_are_project_relative_and_explicit_environment_wins(monkeypatch):
    from app.config import ROOT

    monkeypatch.setenv("PROJECTS_ROOT", "relative/pool")
    assert Settings(_env_file=None).projects_root == ROOT / "relative/pool"


def test_catalog_context_restored_after_exception(resources):
    other = OCRResources(Settings(_env_file=None))
    with pytest.raises(RuntimeError), use_resources(other):
        raise RuntimeError("test")
    assert get_resources() is resources


def test_application_shutdown_releases_ocr_model_and_template_caches(settings):
    app = create_app(settings=settings)
    with TestClient(app):
        app.state.ocr_resources.engine = object()
        app.state.ocr_resources.caches[lambda: None] = lambda: None
    assert app.state.ocr_resources.engine is None
    assert app.state.ocr_resources.caches == {}
