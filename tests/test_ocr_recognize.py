"""`POST /ocr/recognize` 的响应契约、字段提取与真实照片回归。

离线用例模拟 RapidOCR 边界，覆盖无表号、表号对不上、坐标对齐和错误映射。
真实照片位于 `data/ocr/imgs`，OCR 模型位于 `.cache/models/ocr`；任一素材缺失时
集成用例跳过，干净克隆和 CI 不要求模型文件。
"""

import base64
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.ocr_helpers import CODE, make_ocr_settings, ocr_result

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "data/ocr/imgs"
MODELS = ROOT / ".cache/models/ocr"
REAL_IMAGES = ("CJ5.jpg", "test.jpg")
MODEL_FILES = (
    "PP-OCRv6_det_medium.onnx",
    "PP-OCRv6_rec_medium.onnx",
    "ch_PP-LCNet_x1_0_textline_ori_cls_server.onnx",
)


def polygon(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    """OCR 输出的四点多边形；接口会取其外接矩形。"""
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def write_image(path: Path, width: int, height: int) -> None:
    cv2.imencode(".png", np.full((height, width, 3), 255, np.uint8))[1].tofile(str(path))


def encode_image(width: int, height: int) -> str:
    """返回可直接放进 img 字段的 base64 PNG。"""
    ok, buffer = cv2.imencode(".png", np.full((height, width, 3), 255, np.uint8))
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings=settings)) as client:
        yield client


@pytest.fixture
def aligned_settings(tmp_path):
    """重写表样 PDF，写入 4 处中文字栏目文字作为对齐锚点。"""
    settings = make_ocr_settings(tmp_path)
    runs = [
        ("监理单位", 40, 40),
        ("施工单位", 220, 40),
        ("工程名称", 40, 90),
        ("检测日期", 220, 90),
    ]
    with pymupdf.open() as document:
        page = document.new_page(width=400, height=300)
        for text, x, y in runs:
            page.insert_text((x, y), text, fontname="china-s", fontsize=10)
        document.save(settings.asset_root / "pdf/test.pdf")
    return settings


def test_recognize_returns_draft_contract_and_extracts_header_fields(client, settings):
    write_image(settings.projects_root / "照片.png", 600, 400)
    client.app.state.ocr_resources.engine = lambda image: ocr_result(
        (polygon(10, 10, 300, 40), "监理单位：测试公司", 0.99),
        (polygon(20, 60, 240, 90), "检测日期：2026.7.2", 0.95),
    )

    response = client.post("/ocr/recognize", json={"path": "照片.png"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "data"}
    assert body["status"] == 200
    data = body["data"]
    assert set(data) == {
        "form",
        "formName",
        "layout",
        "fields",
        "keys",
        "detail",
        "warning",
        "align",
        "image",
        "lines",
        "ms",
    }
    assert data["form"] == ""
    assert data["formName"] == ""
    assert data["layout"] is False
    assert data["keys"] == {}
    assert data["warning"] == "未指定表号,只按栏目文字取值"
    assert data["align"] == {"anchors": 0, "how": "none"}
    assert data["image"] == {"width": 600, "height": 400}
    assert data["fields"] == {
        "fld_supervisor": "测试公司",
        "fld_check_date": "2026-07-02",
    }
    assert [line["s"] for line in data["lines"]] == [
        "监理单位：测试公司",
        "检测日期：2026.7.2",
    ]
    assert data["lines"][0] == {
        "s": "监理单位：测试公司",
        "box": [10, 10, 300, 40],
        "conf": pytest.approx(0.99),
    }
    assert data["lines"][1]["box"] == [20, 60, 240, 90]
    details = {item["field"]: item for item in data["detail"]}
    assert details["fld_supervisor"] == {
        "field": "fld_supervisor",
        "value": "测试公司",
        "how": "inline",
        "conf": pytest.approx(0.99),
        "boxes": [[10, 10, 300, 40]],
    }
    assert details["fld_check_date"]["value"] == "2026-07-02"
    assert details["fld_check_date"]["how"] == "inline"
    assert isinstance(data["ms"], int) and data["ms"] >= 0


def test_recognize_reports_template_name_and_mismatch_warning(client, settings):
    write_image(settings.projects_root / "照片.png", 600, 400)
    client.app.state.ocr_resources.engine = lambda image: ocr_result(
        (polygon(10, 10, 300, 40), "监理单位：测试公司", 0.99)
    )

    response = client.post("/ocr/recognize", json={"path": "照片.png", "form": f"  {CODE}  "})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["form"] == CODE
    assert data["formName"] == "测试表"
    assert data["layout"] is True
    assert data["align"] == {"anchors": 0, "how": "mismatch"}
    assert data["warning"] == (
        f"照片与 {CODE} 表样对不上(只认出 0 处栏目),只按栏目文字取值,请核对表号"
    )
    assert data["fields"]["fld_supervisor"] == "测试公司"


def test_recognize_unknown_form_keeps_label_extraction(client, settings):
    write_image(settings.projects_root / "照片.png", 600, 400)
    client.app.state.ocr_resources.engine = lambda image: ocr_result(
        (polygon(10, 10, 300, 40), "监理单位：测试公司", 0.99)
    )

    response = client.post("/ocr/recognize", json={"path": "照片.png", "form": "NOPE"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["form"] == "NOPE"
    assert data["formName"] == ""
    assert data["layout"] is False
    assert data["align"] == {"anchors": 0, "how": "none"}
    assert data["warning"] == "模板库没有 NOPE 的表样坐标,只按栏目文字取值"
    assert data["fields"]["fld_supervisor"] == "测试公司"


def test_recognize_aligned_photo_reads_value_from_template_rectangle(aligned_settings):
    write_image(aligned_settings.projects_root / "photo.png", 800, 600)
    app = create_app(settings=aligned_settings)
    with TestClient(app) as client:
        app.state.ocr_resources.engine = lambda image: ocr_result(
            (polygon(80, 70, 160, 82.5), "监理单位", 0.99),
            (polygon(440, 70, 520, 82.5), "施工单位", 0.99),
            (polygon(80, 170, 160, 182.5), "工程名称", 0.99),
            (polygon(440, 170, 520, 182.5), "检测日期", 0.99),
            (polygon(300, 100, 400, 120), "测试公司", 0.95),
        )
        response = client.post("/ocr/recognize", json={"path": "photo.png", "form": CODE})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["formName"] == "测试表"
    assert data["layout"] is True
    assert data["warning"] == ""
    assert data["align"]["how"] == "anchors"
    assert data["align"]["anchors"] == 4
    assert data["align"]["ax"] == pytest.approx(800, abs=0.5)
    assert data["align"]["ay"] == pytest.approx(600, abs=0.5)
    assert data["fields"]["fld_supervisor"] == "测试公司"
    assert data["detail"] == [
        {
            "field": "fld_supervisor",
            "value": "测试公司",
            "how": "rect",
            "conf": pytest.approx(0.95),
            "boxes": [[300, 100, 400, 120]],
        }
    ]


def test_recognize_validates_request_and_path(client, settings):
    (settings.projects_root / "folder").mkdir()

    assert client.post("/ocr/recognize", json={"path": "照片.png", "extra": 1}).status_code == 422
    assert client.post("/ocr/recognize", json={"path": ""}).status_code == 422
    assert client.post("/ocr/recognize", json={"img": ""}).status_code == 422
    assert client.post("/ocr/recognize", json={"path": " ", "img": " "}).status_code == 422
    assert client.post("/ocr/recognize", json={}).status_code == 422
    assert client.post("/ocr/recognize", json={"path": "missing.png"}).status_code == 400
    assert client.post("/ocr/recognize", json={"path": "folder"}).status_code == 400
    assert client.post("/ocr/recognize", json={"img": "not-base64"}).status_code == 400


@pytest.mark.parametrize("prefix", ["", "data:image/png;base64,"])
def test_recognize_accepts_base64_image_without_path(client, prefix):
    client.app.state.ocr_resources.engine = lambda image: ocr_result(
        (polygon(10, 10, 300, 40), "监理单位：测试公司", 0.99),
    )

    response = client.post("/ocr/recognize", json={"img": prefix + encode_image(600, 400)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["image"] == {"width": 600, "height": 400}
    assert data["fields"]["fld_supervisor"] == "测试公司"


def test_recognize_without_templates_returns_503(tmp_path):
    projects = tmp_path / "projects"
    projects.mkdir()
    write_image(projects / "照片.png", 200, 100)
    settings = Settings(
        _env_file=None,
        templates_root=tmp_path / "missing",
        projects_root=projects,
        ocr_model_root=tmp_path / "models",
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        app.state.ocr_resources.engine = lambda image: ocr_result()
        response = client.post("/ocr/recognize", json={"path": "照片.png"})

    assert response.status_code == 503
    assert set(response.json()) == {"detail"}
    assert "TEMPLATES_ROOT" in response.json()["detail"]


def missing_real_assets() -> list[Path]:
    paths = [IMAGES / name for name in REAL_IMAGES] + [MODELS / name for name in MODEL_FILES]
    return [path for path in paths if not path.is_file()]


@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    missing = missing_real_assets()
    if missing:
        pytest.skip("真实 OCR 素材缺失: " + ", ".join(str(path) for path in missing))
    generated = make_ocr_settings(tmp_path_factory.mktemp("recognize"))
    settings = Settings(
        _env_file=None,
        templates_root=generated.templates_root,
        admin_root=generated.admin_root,
        asset_root=generated.asset_root,
        projects_root=IMAGES,
        ocr_model_root=MODELS,
    )
    with TestClient(create_app(settings=settings)) as client:
        yield client


def assert_line_geometry(lines: list[dict], image: dict) -> None:
    for line in lines:
        assert set(line) == {"s", "box", "conf"}
        assert line["s"].strip()
        x0, y0, x1, y1 = line["box"]
        assert 0 <= x0 < x1 <= image["width"]
        assert 0 <= y0 < y1 <= image["height"]
        assert 0 <= line["conf"] <= 1


def test_real_photo_cj5_extracts_printed_table(real_client):
    before = sorted(path.name for path in IMAGES.iterdir())

    response = real_client.post("/ocr/recognize", json={"path": "CJ5.jpg"})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["image"] == {"width": 3072, "height": 4096}
    assert data["form"] == ""
    assert data["formName"] == ""
    assert data["layout"] is False
    assert data["warning"] == "未指定表号,只按栏目文字取值"
    assert data["fields"]["fld_check_date"] == "2024-07-02"
    item = data["fields"]["fld_item_name"]
    assert "K86+300~K87+720安顺互通路基工程" in item
    assert "工程部位：K86+300~K86+660土石方路基" in item
    texts = {line["s"] for line in data["lines"]}
    assert {"公路工程项目", "水准测量记录表", "测点及位置", "后视", "中间点", "前视"} <= texts
    assert {"3.324", "890.100", "886.776", "-8", "9"} <= texts
    assert len(data["lines"]) >= 40
    assert data["detail"]
    assert isinstance(data["ms"], int) and data["ms"] >= 0
    assert_line_geometry(data["lines"], data["image"])
    assert sorted(path.name for path in IMAGES.iterdir()) == before


def test_real_handwritten_log_page_recognizes_printed_header(real_client):
    response = real_client.post("/ocr/recognize", json={"path": "test.jpg"})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["image"] == {"width": 3072, "height": 4096}
    assert data["form"] == ""
    texts = [line["s"] for line in data["lines"]]
    assert "四川公路工程咨询监理公司" in texts
    assert any("Sichuan Highway" in text for text in texts)
    assert len(texts) >= 15
    header = next(line for line in data["lines"] if line["s"] == "四川公路工程咨询监理公司")
    assert header["conf"] >= 0.9
    assert isinstance(data["ms"], int) and data["ms"] >= 0
    assert_line_geometry(data["lines"], data["image"])
