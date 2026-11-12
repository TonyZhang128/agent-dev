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
from app.ocr.journal import alignment as frame
from app.ocr.journal import field_matching as fields
from app.ocr.journal import photo as image
from app.ocr.journal.models import FieldLayout, LoadedPhoto
from app.ocr.journal.template import load_template
from tests.ocr_helpers import make_ocr_settings, ocr_result


def table_photo(width: int = 900, height: int = 1273) -> np.ndarray:
    """一张带表格线的合成照片；定位链应把它识别成表格而不是页面。"""
    picture = np.full((height, width, 3), 255, np.uint8)
    x0, y0, x1, y1 = 100, 250, 800, 1150
    cv2.rectangle(picture, (x0, y0), (x1, y1), (0, 0, 0), 2)
    # 独立按标准表人工标注六行；旧夹具是九行通栏表，不能冒充本模板。
    for y in (250, 329, 400, 483, 790, 991, 1150):
        cv2.line(picture, (x0, y), (x1, y), (0, 0, 0), 2)
    cv2.line(picture, (221, y0), (221, y1), (0, 0, 0), 2)
    for x in (519, 662):
        cv2.line(picture, (x, 329), (x, 483), (0, 0, 0), 2)
    return picture


def field_box(
    shape: tuple[int, ...],
    field: FieldLayout,
    text: str = "",
    *,
    at: float = 0.5,
    height: float = 30.0,
) -> list[list[float]]:
    """在栏目内部生成一个 OCR 框；at 是框中心在栏目高度中的相对位置。"""
    canvas_height, canvas_width = shape[:2]
    x0, y0, x1, y1 = fields.field_bounds_on_canvas(
        field, (canvas_width, canvas_height), frame.table_rect_on_canvas(load_template())
    )
    center_x = (x0 + x1) / 2
    center_y = y0 + (y1 - y0) * at
    box_width = max(60.0, min((x1 - x0) * 0.7, 360.0))
    return [
        [center_x - box_width / 2, center_y - height / 2],
        [center_x + box_width / 2, center_y - height / 2],
        [center_x + box_width / 2, center_y + height / 2],
        [center_x - box_width / 2, center_y + height / 2],
    ]


MAIN_WORK_CONSTRUCTION = "K3+280段路基填筑"
MAIN_WORK_WITNESS = "旁站路基碾压"
MAIN_WORK_PATROL = "挡土墙错缝砌筑"


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
        ("巡视情况", "挡土墙错缝砌筑", 0.75, 0.88, 0.93),
    )
    items = []
    for field in load_template().field_layouts():
        if field.key == skip:
            continue
        if field.key == "main_work":
            for label, text, label_at, value_at, confidence in parts:
                items.append((field_box(shape, field, at=label_at), label, 0.9))
                items.append((field_box(shape, field, at=value_at), text, confidence))
            continue
        text, confidence = values[field.key]
        items.append((field_box(shape, field), text, confidence))
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

    response = client.post("/ocr/journal", json={"path": "journal.png", "taskId": " 42 "})

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
                    "patrol": MAIN_WORK_PATROL,
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

    response = client.post("/ocr/journal", json={"path": "journal.png"})

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


def test_empty_field_does_not_repeat_ocr(client, settings):
    write_photo(settings)
    engine = PageEngine(skip="reviewer", fallback="审核人：王梦瑶")
    client.app.state.ocr_resources.engine = engine

    response = client.post("/ocr/journal", json={"path": "journal.png"})

    data = response.json()["data"]
    assert response.status_code == 200
    assert engine.calls == 1
    assert data["common"]["reviewerName"] is None


def test_date_keeps_invalid_calendar_value():
    assert fields._normalize_date("2026年2月31日") == "2026年2月31日"


@pytest.mark.parametrize("left", [39.9, 40, 40.1])
def test_unresolved_cross_field_box_is_not_assigned(left):
    specs = (
        fields.FieldLayout("first", "左栏", (0, 0, 0.5, 1)),
        fields.FieldLayout("second", "右栏", (0.5, 0, 0.5, 1)),
    )
    box = fields.OcrTextBox("无法判定归属", left, 10, 60, 30, 0.99)
    groups, ambiguous = fields._assign_boxes_to_fields([box], specs, (100, 100), (0, 0, 1, 1))
    assert not groups["first"] and not groups["second"]
    assert ambiguous == {"first", "second"}


def test_inline_reviewer_label_and_value_in_one_box():
    canvas = np.full((1400, 1000, 3), 255, np.uint8)
    # 独立标注：标签和值跨越模板值区左边界，但属于同一个表外字段。
    readings = fields.extract_fields(
        canvas,
        load_template().field_layouts(),
        (0.1, 0.2, 0.9, 0.9),
        lambda picture: [fields.OcrTextBox("审核人：王梦瑶", 680, 1253, 840, 1295, 0.95)],
    )
    assert (
        next(reading.value for reading in readings if reading.layout.key == "reviewer") == "王梦瑶"
    )


def test_geometry_reads_name_without_its_printed_label():
    readings = fields.extract_fields(
        np.full((1000, 1000, 3), 255, np.uint8),
        load_template().field_layouts(),
        (0.1, 0.2, 0.9, 0.9),
        lambda picture: [fields.OcrTextBox("王璐瑶", 300, 275, 400, 305, 0.95)],
    )
    assert (
        next(reading.value for reading in readings if reading.layout.key == "recorder") == "王璐瑶"
    )


def test_unphotographed_reviewer_is_not_mistaken_for_empty_paper():
    canvas = np.full((842, 595, 3), 255, np.uint8)
    mask = np.full((842, 595), 255, np.uint8)
    mask[674:] = 0
    readings = fields.extract_fields(
        canvas,
        load_template().field_layouts(),
        (0.1, 0.1, 0.9, 0.8),
        lambda picture: [],
        valid_mask=mask,
    )
    reviewer = next(reading for reading in readings if reading.layout.key == "reviewer")
    assert reviewer.value == ""
    assert reviewer.visible_fraction == 0
    assert reviewer.ambiguous


@pytest.mark.parametrize("angle,padding", [(3, 0), (0, 700)])
def test_complete_table_alignment_handles_rotation_and_background(angle, padding):
    picture = table_photo()
    source_corners = np.float32([[100, 250], [800, 250], [800, 1150], [100, 1150]])
    rotation = cv2.getRotationMatrix2D((450, 636), angle, 1)
    rotated = cv2.warpAffine(picture, rotation, (900, 1273), borderValue=(255, 255, 255))
    expected = cv2.transform(source_corners[None], rotation)[0] + padding
    padded = cv2.copyMakeBorder(
        rotated, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    location = frame.align_canvas(
        LoadedPhoto(
            padded, cv2.cvtColor(padded, cv2.COLOR_BGR2GRAY), padded.shape[1], padded.shape[0]
        )
    )
    assert min(location.line_support) >= 0.55
    assert location.table_quad_in_photo == pytest.approx(expected, abs=8)


def test_alignment_keeps_outside_geometry_and_source_coverage():

    picture = table_photo()
    photo = LoadedPhoto(picture, cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY), 900, 1273)
    location = frame.align_canvas(photo)
    table = location.table_rect_on_canvas
    expected = np.array(
        [[[table[0], table[1]], [table[2], table[1]], [table[2], table[3]], [table[0], table[3]]]],
        dtype=np.float32,
    )
    expected *= np.array([location.canvas_width, location.canvas_height])
    actual = cv2.perspectiveTransform(
        location.table_quad_in_photo[None], location.work_image_to_canvas
    )
    assert actual == pytest.approx(expected, abs=0.1)
    assert location.source_coverage_mask.shape == location.canvas.shape[:2]
    assert np.count_nonzero(location.source_coverage_mask) > 0


def test_cleaning_strips_printed_labels_and_normalizes_dates():
    field = load_template().field_layouts()[6]  # date
    boxes = [
        fields.OcrTextBox("记录时间：2026年11月11日", 0, 0, 200, 30, 0.9),
    ]
    cleaned = fields._extract_field_value(field, boxes)
    assert cleaned.text == "2026-11-11"
    assert cleaned.confidence == 0.9

    main_work = load_template().field_layouts()[8]
    boxes = [
        fields.OcrTextBox("主要施土情况", 0, 0, 200, 30, 0.8),
        fields.OcrTextBox("K3+280段路基填筑", 0, 40, 400, 70, 0.95),
        fields.OcrTextBox("旁站情况", 0, 80, 200, 110, 0.8),
        fields.OcrTextBox("旁站路基碾压", 0, 120, 400, 150, 0.94),
        fields.OcrTextBox("《视情况", 0, 160, 200, 190, 0.8),
        fields.OcrTextBox("挡土墙错缝砌筑", 0, 200, 400, 230, 0.93),
    ]
    # mainWork 保留印刷小标题；拆分发生在识别之后的独立阶段，_clean 不改文本内容。
    assert fields._extract_field_value(main_work, boxes).text == (
        "主要施土情况K3+280段路基填筑旁站情况旁站路基碾压《视情况挡土墙错缝砌筑"
    )

    reviewer = load_template().field_layouts()[7]
    assert (
        fields._extract_field_value(
            reviewer, [fields.OcrTextBox("审核人：王梦瑶", 0, 0, 200, 30, 0.9)]
        ).text
        == "王梦瑶"
    )


def test_boundary_box_is_assigned_to_the_best_field():
    main_work = load_template().field_layouts()[8]
    issues = load_template().field_layouts()[9]
    width, height = 1000, 1414
    border = main_work.rect_in_table[1] + main_work.rect_in_table[3]
    box = fields.OcrTextBox(
        "跨格文字",
        300,
        (border - 0.012) * height,
        700,
        (border + 0.008) * height,
        0.9,
    )
    groups, _ = fields._assign_boxes_to_fields(
        [box], load_template().field_layouts(), (width, height), (0, 0, 1, 1)
    )
    assert box in groups[main_work.key]
    assert box not in groups[issues.key]


def test_duplicate_boxes_are_removed():
    boxes = [
        fields.OcrTextBox("97.1", 0, 0, 100, 30, 0.9),
        fields.OcrTextBox("1", 20, 5, 40, 30, 0.8),
    ]
    assert len(fields._deduplicate_boxes(boxes)) == 1


def test_short_heading_is_not_sorted_after_overlapping_next_line():
    boxes = [
        fields.OcrTextBox("下一行正文", 207, 846, 1044, 912, 0.9),
        fields.OcrTextBox("短标题", 211, 823, 368, 867, 0.9),
    ]
    assert [box.text for box in fields._sort_reading_order(boxes)] == ["短标题", "下一行正文"]


def test_alignment_finds_table_and_rejects_blank_photo():
    picture = table_photo()
    photo = LoadedPhoto(
        bgr=picture,
        gray=cv2.cvtColor(picture, cv2.COLOR_BGR2GRAY),
        width=picture.shape[1],
        height=picture.shape[0],
    )
    located = frame.align_canvas(photo)
    assert min(located.line_support) >= 0.55
    assert located.canvas.shape == (located.canvas_height, located.canvas_width, 3)

    blank = np.full((400, 300, 3), 255, np.uint8)
    empty = LoadedPhoto(
        bgr=blank,
        gray=cv2.cvtColor(blank, cv2.COLOR_BGR2GRAY),
        width=300,
        height=400,
    )
    from app.errors import JournalFrameNotFound

    with pytest.raises(JournalFrameNotFound):
        frame.align_canvas(empty)


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
        "/ocr/journal",
        json={"path": "missing.png", "img": encoded},
    )

    assert response.status_code == 200
    assert response.json()["data"]["common"]["projectName"] == "成乐高速公路扩容建设"


@pytest.mark.parametrize("route", ["/ocr/journal", "/ocr/journal/recognize"])
def test_new_route_maps_invalid_image_and_model_failure(client, settings, route):
    (settings.projects_root / "invalid.png").write_bytes(b"not an image")
    invalid = client.post(route, json={"path": "invalid.png"})
    assert invalid.status_code == 400
    assert set(invalid.json()) == {"detail"}

    write_photo(settings)

    def broken(image):
        raise RuntimeError("model download failed")

    client.app.state.ocr_resources.engine = broken
    failed = client.post(route, json={"path": "journal.png"})
    assert failed.status_code == 503
    assert "model download failed" not in failed.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"path": "  "}, {"img": "\n"}])
@pytest.mark.parametrize("route", ["/ocr/journal", "/ocr/journal/recognize"])
def test_new_route_requires_a_photo_source(client, payload, route):
    assert client.post(route, json=payload).status_code == 422
