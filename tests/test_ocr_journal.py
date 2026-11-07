"""新版监理日志识别链：整页一次 OCR、栏目匹配、印刷字剥离和补充识别。

离线用例只模拟 OCR 模型边界，照片和表格由测试生成，不读取模板库或数据池。
"""

import base64
import io
import json
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.llm import ModelService
from app.main import create_app
from app.ocr.journal import fields, frame, image, spec
from app.ocr.journal.types import Photo
from tests.ocr_helpers import make_ocr_settings, ocr_result


def table_photo(width: int = 900, height: int = 1273) -> np.ndarray:
    """一张带表格线的合成照片；定位链应把它识别成表格而不是页面。"""
    picture = np.full((height, width, 3), 255, np.uint8)
    x0, y0, x1, y1 = 100, 250, 800, 1150
    cv2.rectangle(picture, (x0, y0), (x1, y1), (0, 0, 0), 2)
    for y in (250, 290, 340, 390, 450, 560, 700, 800, 1000, 1150):
        cv2.line(picture, (x0, y), (x1, y), (0, 0, 0), 2)
    for x in (100, 250, 600, 800):
        cv2.line(picture, (x, y0), (x, y1), (0, 0, 0), 2)
    return picture


def field_box(
    shape: tuple[int, ...],
    field: spec.FieldSpec,
    text: str = "",
    *,
    at: float = 0.5,
    height: float = 30.0,
) -> list[list[float]]:
    """在栏目内部生成一个 OCR 框；at 是框中心在栏目高度中的相对位置。"""
    canvas_height, canvas_width = shape[:2]
    x, y, width, height_ratio = field.rect
    center_x = (x + width / 2) * canvas_width
    center_y = (y + height_ratio * at) * canvas_height
    box_width = max(60.0, min(width * canvas_width * 0.7, 360.0))
    return [
        [center_x - box_width / 2, center_y - height / 2],
        [center_x + box_width / 2, center_y - height / 2],
        [center_x + box_width / 2, center_y + height / 2],
        [center_x - box_width / 2, center_y + height / 2],
    ]


MAIN_WORK_CONSTRUCTION = "主要施工情况K3+280段路基填筑"
MAIN_WORK_WITNESS = "旁站情况旁站路基碾压《视情况挡土墙错缝砌筑"


def full_page_items(shape: tuple[int, ...], *, skip: str = "") -> list[tuple]:
    """按栏目生成整页 OCR 结果；mainWork 里带三个印刷小标题和三段值。"""
    values = {
        "project": ("成乐高速公路扩容建设", 0.95),
        "number": ("JL-001", 0.96),
        "supervision_org": ("监理机构：测试监理机构", 0.97),
        "recorder": ("记录人：王璐瑶", 0.96),
        "weather": ("晴", 0.98),
        "position": ("专业监理工程师", 0.99),
        "date": ("记录时间：2026年11月11日", 0.99),
        "reviewer": ("审核人：王梦瑶", 0.98),
        "issues": ("挡土墙墙背回填局部压实不足", 0.95),
        "next_day_plan": ("见证水稳基层检测", 0.94),
    }
    parts = (
        ("主要施工情况", "K3+280段路基填筑", 0.15, 0.28, 0.95),
        ("旁站情况", "旁站路基碾压", 0.45, 0.58, 0.94),
        ("《视情况", "挡土墙错缝砌筑", 0.75, 0.88, 0.93),
    )
    items = []
    for field in spec.FIELD_SPECS:
        if field.key == skip:
            continue
        if field.key == "mainWork":
            for label, text, label_at, value_at, conf in parts:
                items.append((field_box(shape, field, at=label_at), label, 0.9))
                items.append((field_box(shape, field, at=value_at), text, conf))
            continue
        text, conf = values[field.key]
        items.append((field_box(shape, field), text, conf))
    return items


class PageEngine:
    """整页返回固定栏目；裁剪补充识别默认返回空。"""

    def __init__(self, *, skip: str = "", fallback: str = ""):
        self.calls = 0
        self.skip = skip
        self.fallback = fallback

    def __call__(self, picture):
        self.calls += 1
        height, width = picture.shape[:2]
        if width < 500:  # 栏目补充识别的裁剪图
            if self.fallback:
                return ocr_result(
                    ([[10, 10], [width - 10, 10], [width - 10, 40], [10, 40]], self.fallback, 0.95)
                )
            return ocr_result()
        return ocr_result(*full_page_items(picture.shape, skip=self.skip))


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


def offline_service(settings) -> ModelService:
    """拆分模型不可达：本文件只验证 OCR，mainWork 应按标题规则完成。"""

    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    return ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(unavailable), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(unavailable), trust_env=False
        ),
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(offline_service(settings))) as client:
        yield client


def write_photo(settings, name: str = "journal.png") -> None:
    ok, buffer = cv2.imencode(".png", table_photo())
    assert ok
    (settings.projects_root / name).write_bytes(buffer.tobytes())


def test_new_route_reads_one_page_and_maps_fields(client, settings):
    write_photo(settings)
    engine = PageEngine()
    client.app.state.ocr_resources.engine = engine

    response = client.post("/ocr/daily-logs-new", json={"path": "journal.png", "taskId": " 42 "})

    assert response.status_code == 200
    assert engine.calls == 1
    assert response.json() == {
        "status": 200,
        "message": "识别完成",
        "data": {
            "taskId": "42",
            "documentType": "supervision_diary",
            "common": {
                "projectName": "成乐高速公路扩容建设",
                "documentNo": "JL-001",
                "supervisionOrg": "测试监理机构",
                "recorderName": "王璐瑶",
                "recorderPosition": "专业监理工程师",
                "weather": "晴",
                "logDate": "2026-11-11",
                "reviewerName": "王梦瑶",
            },
            "fields": {
                "mainWork": {
                    "construction": MAIN_WORK_CONSTRUCTION,
                    "witness": MAIN_WORK_WITNESS,
                    "patrol": None,
                },
                "issues": "挡土墙墙背回填局部压实不足",
                "nextDayPlan": "见证水稳基层检测",
            },
        },
    }


def test_new_route_keeps_null_fields_and_matches_backend_contract(client, settings):
    """空识别也必须保留约定字段；递归比较正式响应子契约，拒绝任何额外信息。"""
    write_photo(settings)
    client.app.state.ocr_resources.engine = lambda picture: ocr_result()

    response = client.post("/ocr/daily-logs-new", json={"path": "journal.png"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": 200,
        "message": "识别完成",
        "data": {
            "taskId": None,
            "documentType": "supervision_diary",
            "common": {
                "projectName": None,
                "documentNo": None,
                "supervisionOrg": None,
                "recorderName": None,
                "recorderPosition": None,
                "weather": None,
                "logDate": None,
                "reviewerName": None,
            },
            "fields": {
                "mainWork": {"construction": None, "witness": None, "patrol": None},
                "issues": None,
                "nextDayPlan": None,
            },
        },
    }
    contract_path = Path(__file__).resolve().parents[1] / "interfaces/journal/response.schema.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    def assert_keys(actual, schema):
        if schema.get("type") == "object":
            assert isinstance(actual, dict)
            assert actual.keys() == schema["properties"].keys()
            for key, field_schema in schema["properties"].items():
                assert_keys(actual[key], field_schema)

    assert_keys(payload, contract)


def test_missing_field_uses_one_targeted_crop(client, settings):
    write_photo(settings)
    engine = PageEngine(skip="reviewer", fallback="审核人：王梦瑶")
    client.app.state.ocr_resources.engine = engine

    response = client.post("/ocr/daily-logs-new", json={"path": "journal.png"})

    data = response.json()["data"]
    assert response.status_code == 200
    assert engine.calls == 2
    assert data["common"]["reviewerName"] == "王梦瑶"


def test_cleaning_strips_printed_labels_and_normalizes_dates():
    field = spec.FIELD_SPECS[6]  # date
    boxes = [
        fields.TextBox("记录时间：2026年11月11日", 0, 0, 200, 30, 0.9),
    ]
    assert fields._clean(field, boxes) == ("2026-11-11", 0.9)

    main_work = spec.FIELD_SPECS[8]
    boxes = [
        fields.TextBox("主要施土情况", 0, 0, 200, 30, 0.8),
        fields.TextBox("K3+280段路基填筑", 0, 40, 400, 70, 0.95),
        fields.TextBox("旁站情况", 0, 80, 200, 110, 0.8),
        fields.TextBox("旁站路基碾压", 0, 120, 400, 150, 0.94),
        fields.TextBox("《视情况", 0, 160, 200, 190, 0.8),
        fields.TextBox("挡土墙错缝砌筑", 0, 200, 400, 230, 0.93),
    ]
    # mainWork 保留印刷小标题；拆分发生在识别之后的独立阶段，_clean 不改文本内容。
    assert fields._clean(main_work, boxes)[0] == (
        "主要施土情况K3+280段路基填筑旁站情况旁站路基碾压《视情况挡土墙错缝砌筑"
    )

    reviewer = spec.FIELD_SPECS[7]
    assert (
        fields._clean(reviewer, [fields.TextBox("审核人：王梦瑶", 0, 0, 200, 30, 0.9)])[0]
        == "王梦瑶"
    )


def test_boundary_box_is_assigned_to_the_best_field():
    main_work = spec.FIELD_SPECS[8]
    issues = spec.FIELD_SPECS[9]
    width, height = 1000, 1414
    border = main_work.rect[1] + main_work.rect[3]
    box = fields.TextBox(
        "跨格文字",
        300,
        (border - 0.012) * height,
        700,
        (border + 0.008) * height,
        0.9,
    )
    groups, _ = fields._assign([box], spec.FIELD_SPECS, width, height)
    assert box in groups[main_work.key]
    assert box not in groups[issues.key]


def test_duplicate_boxes_are_removed():
    boxes = [
        fields.TextBox("97.1", 0, 0, 100, 30, 0.9),
        fields.TextBox("1", 20, 5, 40, 30, 0.8),
    ]
    assert len(fields._dedup(boxes)) == 1


def test_locate_finds_table_and_falls_back_to_whole_page():
    picture = table_photo()
    photo = Photo(
        bgr=picture,
        gray=cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY),
        width=picture.shape[1],
        height=picture.shape[0],
    )
    located = frame.locate(photo)
    assert located.kind == "table"
    assert located.how == "contour+table"
    assert located.sheet.shape == (located.height, located.width, 3)

    blank = np.full((400, 300, 3), 255, np.uint8)
    empty = Photo(
        bgr=blank,
        gray=cv2.cvtColor(blank, cv2.COLOR_BGR2GRAY),
        width=300,
        height=400,
    )
    fallback = frame.locate(empty)
    assert fallback.kind == "whole"
    assert fallback.how == "whole"


def test_exif_orientation_is_applied():
    picture = Image.new("RGB", (100, 60), (255, 0, 0))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", exif=exif)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    photo = image.load_photo(None, "data:image/jpeg;base64," + encoded)

    assert photo.width == 60
    assert photo.height == 100


def test_new_route_accepts_base64_and_prefers_it(client, settings):
    write_photo(settings)
    ok, buffer = cv2.imencode(".png", table_photo())
    assert ok
    encoded = "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")
    client.app.state.ocr_resources.engine = PageEngine()

    response = client.post(
        "/ocr/daily-logs-new",
        json={"path": "missing.png", "img": encoded},
    )

    assert response.status_code == 200
    assert response.json()["data"]["common"]["projectName"] == "成乐高速公路扩容建设"


def test_new_route_maps_invalid_image_and_model_failure(client, settings):
    (settings.projects_root / "invalid.png").write_bytes(b"not an image")
    invalid = client.post("/ocr/daily-logs-new", json={"path": "invalid.png"})
    assert invalid.status_code == 400
    assert set(invalid.json()) == {"detail"}

    write_photo(settings)

    def broken(image):
        raise RuntimeError("model download failed")

    client.app.state.ocr_resources.engine = broken
    failed = client.post("/ocr/daily-logs-new", json={"path": "journal.png"})
    assert failed.status_code == 503
    assert "model download failed" not in failed.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"path": "  "}, {"img": "\n"}])
def test_new_route_requires_a_photo_source(client, payload):
    assert client.post("/ocr/daily-logs-new", json=payload).status_code == 422
