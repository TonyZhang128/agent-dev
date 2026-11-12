"""简表照片识别、schema2 模板和约定 JSON 的公开行为。"""

import base64
import json
import math
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.llm import ModelService
from app.main import create_app
from app.ocr.jianbiao import OcrTextBox, recognize_jianbiao
from tests.ocr_helpers import make_ocr_settings, ocr_result

SOURCE_TEMPLATE_ID = "JB12-4.5.2-4"
TABLE_WIDTH = 1089
TABLE_HEIGHT = 626
ROW_LINES = (0, 55, 97, 147, 194, 241, 288, 335, 382, 429, 476, 523, 570, 626)
COLUMN_LINES = (0, 169, 291, 1089)
DATE_DIVIDER = 426
RATE_DIVIDER = 1009


def source_photo() -> np.ndarray:
    """按左图的表格拓扑生成一张带透视变形的现场照片。"""
    canonical = np.full((TABLE_HEIGHT, TABLE_WIDTH, 3), 255, np.uint8)
    for y in ROW_LINES:
        cv2.line(canonical, (0, y), (TABLE_WIDTH - 1, y), (0, 0, 0), 2)
    for x in COLUMN_LINES:
        cv2.line(canonical, (x, 0), (x, TABLE_HEIGHT - 1), (0, 0, 0), 2)
    cv2.line(canonical, (DATE_DIVIDER, 0), (DATE_DIVIDER, 55), (0, 0, 0), 2)
    cv2.line(canonical, (RATE_DIVIDER, 147), (RATE_DIVIDER, TABLE_HEIGHT - 1), (0, 0, 0), 2)

    source = np.array(
        [[0, 0], [TABLE_WIDTH - 1, 0], [TABLE_WIDTH - 1, TABLE_HEIGHT - 1], [0, TABLE_HEIGHT - 1]],
        np.float32,
    )
    destination = np.array([[120, 100], [1180, 130], [1150, 850], [90, 820]], np.float32)
    photo = np.full((950, 1300, 3), 255, np.uint8)
    matrix = cv2.getPerspectiveTransform(source, destination)
    warped = cv2.warpPerspective(canonical, matrix, (photo.shape[1], photo.shape[0]))
    mask = cv2.warpPerspective(
        np.full(canonical.shape[:2], 255, np.uint8), matrix, (photo.shape[1], photo.shape[0])
    )
    photo[mask > 0] = warped[mask > 0]
    return photo


def table_bounds(canvas: np.ndarray) -> tuple[int, int, int, int]:
    """测试只观察校正图上的真实表格，不依赖模块内部画布参数。"""
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
    points = cv2.findNonZero(255 - gray)
    assert points is not None
    return cv2.boundingRect(points)


def text_box(text: str, x0: float, y0: float, x1: float, y1: float) -> OcrTextBox:
    return OcrTextBox(
        text=text,
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
        confidence=0.98,
        polygon=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
    )


def test_recognizes_photo_and_maps_common_output() -> None:
    """旧模板编号仍可使用，识别值应进入新版公共字段输出。"""
    from app.ocr.jianbiao.output import build_recognition_response

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, "inspector", "张三")]

    result = recognize_jianbiao(source_photo(), SOURCE_TEMPLATE_ID, reader=read)
    payload = build_recognition_response(result)

    assert result.values["inspector"] == "张三"
    assert result.source_template_id == "subgrade_spot_check"
    assert payload["data"]["common"]["inspectorName"] == "张三"


def test_last_record_value_is_preserved_in_output() -> None:
    """第10行识别值不得因旧目标表只映射6行而丢失。"""

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, "measured_value_10", "80")]

    result = recognize_jianbiao(source_photo(), SOURCE_TEMPLATE_ID, reader=read)
    from app.ocr.jianbiao.output import build_recognition_response

    records = build_recognition_response(result)["data"]["fields"]["records"]

    assert result.values["measured_value_10"] == "80"
    assert records[9]["measuredValue"] == "80"


def test_mismatched_table_is_rejected_before_ocr() -> None:
    """表格拓扑不符合模板时不得退回整图，也不得调用 OCR。"""
    import pytest

    from app.errors import JianbiaoFrameNotFound

    called = False

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        nonlocal called
        called = True
        return []

    with pytest.raises(JianbiaoFrameNotFound):
        recognize_jianbiao(np.full((800, 1000, 3), 255, np.uint8), SOURCE_TEMPLATE_ID, reader=read)

    assert called is False


def test_cross_field_text_is_marked_ambiguous_instead_of_duplicated() -> None:
    """文字框跨两个字段且归属接近时，两边都不得生成确定值。"""

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        x, y, width, height = table_bounds(canvas)
        return [
            text_box(
                "疑似跨栏",
                x + 69 / TABLE_WIDTH * width,
                y + 160 / TABLE_HEIGHT * height,
                x + 269 / TABLE_WIDTH * width,
                y + 185 / TABLE_HEIGHT * height,
            )
        ]

    result = recognize_jianbiao(source_photo(), SOURCE_TEMPLATE_ID, reader=read)

    assert "check_item_1" not in result.values
    assert "standard_value_1" not in result.values
    ambiguous = {reading.key for reading in result.readings if reading.ambiguous}
    assert {"check_item_1", "standard_value_1"} <= ambiguous


def test_base64_photo_uses_same_recognition_pipeline() -> None:
    """调用方可以直接传 base64 照片，获得与内存图像一致的字段值。"""
    import base64

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, "inspector", "张三")]

    encoded = cv2.imencode(".png", source_photo())[1].tobytes()
    result = recognize_jianbiao(
        None,
        SOURCE_TEMPLATE_ID,
        img=base64.b64encode(encoded).decode("ascii"),
        reader=read,
    )

    assert result.values["inspector"] == "张三"


SCHEMA2_TEMPLATE_ID = "subgrade_spot_check"


def template_text_box(canvas: np.ndarray, key: str, text: str) -> OcrTextBox:
    """在模板字段中央构造 OCR 框；预期业务值仍由测试字面量独立给出。"""
    from app.ocr.jianbiao.template import load_template

    template = load_template(SCHEMA2_TEMPLATE_ID)
    field = next(item for item in template.fields if item.key == key)
    x, y, width, height = table_bounds(canvas)
    u, v, field_width, field_height = field.rect_in_table
    center_x = x + (u + field_width / 2) * width
    center_y = y + (v + field_height / 2) * height
    box_width = field_width * width * 0.6
    box_height = field_height * height * 0.5
    return text_box(
        text,
        center_x - box_width / 2,
        center_y - box_height / 2,
        center_x + box_width / 2,
        center_y + box_height / 2,
    )


def test_schema2_template_expands_record_rows() -> None:
    """新版行组模板应展开为45个值区，并把宽/高比转换为校正所需的高/宽比。"""
    from app.ocr.jianbiao.template import load_template

    template = load_template(SCHEMA2_TEMPLATE_ID)

    assert template.template_name == "土方路基抽检记录表"
    assert len(template.common_fields) == 5
    assert len(template.row_groups) == 10
    assert len(template.fields) == 45
    assert template.fields[-1].key == "pass_rate_10"
    assert math.isclose(template.height_aspect, 467.25 / 816.75, rel_tol=1e-6)
    assert load_template(SOURCE_TEMPLATE_ID).template_id == SCHEMA2_TEMPLATE_ID


def test_response_contract_matches_provided_example() -> None:
    """公开 JSON 应与用户示例逐值一致，包括固定10行、空值null和数值合格率。"""
    from app.ocr.jianbiao.output import build_recognition_response

    sample_values = {
        "project": "成乐高速公路扩容建设项目",
        "number": "JB12-4.5.2-4",
        "inspector": "王璐瑶",
        "inspect_date": "2026年11月11日",
        "position": "防裂工程土工合成材料处治层（土工格栅）",
        "check_item_1": "压实度",
        "standard_value_1": "≥96%",
        "measured_value_1": "96.2、96.5、96.8",
        "pass_rate_1": "100",
        "check_item_2": "弯沉",
        "standard_value_2": "满足设计要求",
        "measured_value_2": "212、218、226（0.01 mm）",
        "pass_rate_2": "100.0%",
        "check_item_3": "平整度",
        "standard_value_3": "≤15 mm",
        "measured_value_3": "8、10、9",
        "pass_rate_3": "100",
    }

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, key, text) for key, text in sample_values.items()]

    result = recognize_jianbiao(
        source_photo(),
        SCHEMA2_TEMPLATE_ID,
        task_id="123456789012345678",
        reader=read,
    )
    expected = json.loads(
        (Path(__file__).parent / "fixtures/jianbiao-response.example.json").read_text(
            encoding="utf-8"
        )
    )

    assert build_recognition_response(result) == expected


def test_annotation_labels_are_not_returned_as_business_values() -> None:
    """标注图的英文键、字段标签和行占位符必须剥离，只保留真实填写内容。"""
    from app.ocr.jianbiao.output import build_recognition_response

    annotated_values = {
        "inspector": "inspector·抽检人",
        "position": "position·工程部位防裂工程土工合成材料处治层（土工格栅）",
        "check_item_1": "抽检项目1",
        "standard_value_1": "规定值1·满足设计要求",
        "measured_value_1": "实测值1",
        "pass_rate_1": "合格率1",
    }

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, key, text) for key, text in annotated_values.items()]

    result = recognize_jianbiao(source_photo(), SCHEMA2_TEMPLATE_ID, reader=read)
    payload = build_recognition_response(result)

    assert payload["data"]["common"]["inspectorName"] is None
    assert payload["data"]["common"]["position"] == "防裂工程土工合成材料处治层（土工格栅）"
    assert payload["data"]["fields"]["records"][0] == {
        "rowIndex": 1,
        "checkItem": None,
        "standardValue": "满足设计要求",
        "measuredValue": None,
        "passRate": None,
    }


def test_sideways_photo_is_rotated_and_corners_use_original_coordinates() -> None:
    """横置照片应自动转正，且诊断四角必须映射回原始照片坐标。"""
    upright = source_photo()
    sideways = cv2.rotate(upright, cv2.ROTATE_90_CLOCKWISE)

    def read(canvas: np.ndarray) -> list[OcrTextBox]:
        return [template_text_box(canvas, "inspector", "张三")]

    automatic = recognize_jianbiao(sideways, SCHEMA2_TEMPLATE_ID, reader=read)
    manual = recognize_jianbiao(upright, SCHEMA2_TEMPLATE_ID, reader=read)

    assert automatic.values["inspector"] == "张三"
    assert automatic.alignment.canvas.shape == manual.alignment.canvas.shape
    expected = np.column_stack(
        (
            upright.shape[0] - 1 - manual.alignment.table_quad_in_photo[:, 1],
            manual.alignment.table_quad_in_photo[:, 0],
        )
    )
    np.testing.assert_allclose(
        automatic.alignment.table_quad_in_photo,
        expected,
        atol=1.5,
    )


# ---- HTTP 接口：只模拟 OCR 模型边界，照片与数据池由测试生成 ----


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


def offline_service(settings) -> ModelService:
    """简表识别不调用语言模型；模型边界置为不可达。"""

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


class TemplateEngine:
    """整页返回模板字段中央的文字框，只模拟 OCR 模型边界。"""

    def __init__(self, values: dict[str, str]):
        self.values = values

    def __call__(self, picture):
        return ocr_result(
            *[
                (
                    [list(point) for point in template_text_box(picture, key, text).polygon],
                    text,
                    0.98,
                )
                for key, text in self.values.items()
            ]
        )


def write_pool_photo(settings, array: np.ndarray, name: str) -> None:
    ok, buffer = cv2.imencode(".png", array)
    assert ok
    (settings.projects_root / name).write_bytes(buffer.tobytes())


def test_route_recognizes_pool_photo_and_maps_fields(client, settings):
    write_pool_photo(settings, source_photo(), "jianbiao.png")
    client.app.state.ocr_resources.engine = TemplateEngine(
        {"inspector": "张三", "pass_rate_1": "100"}
    )

    response = client.post(
        "/ocr/jianbiao",
        json={"path": "jianbiao.png", "form": "JB12-4.5.2-4", "taskId": " 42 "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == 200
    assert payload["message"] == "识别完成"
    assert payload["data"]["taskId"] == "42"
    assert payload["data"]["documentType"] == "subgrade_spot_check"
    assert payload["data"]["common"]["inspectorName"] == "张三"
    records = payload["data"]["fields"]["records"]
    assert len(records) == 10
    assert records[0]["passRate"] == 100.0
    assert records[9] == {
        "rowIndex": 10,
        "checkItem": None,
        "standardValue": None,
        "measuredValue": None,
        "passRate": None,
    }


def test_route_accepts_base64_and_reserved_docsvc_fields(client):
    encoded = base64.b64encode(cv2.imencode(".png", source_photo())[1].tobytes()).decode("ascii")
    client.app.state.ocr_resources.engine = TemplateEngine({"inspector": "张三"})

    response = client.post(
        "/ocr/jianbiao",
        json={
            "img": f"data:image/png;base64,{encoded}",
            "form": "subgrade_spot_check",
            "cfg": {},
            "bound": {},
            "out": "",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["common"]["inspectorName"] == "张三"


def test_route_rejects_mismatched_table_before_ocr(client, settings):
    write_pool_photo(settings, np.full((800, 1000, 3), 255, np.uint8), "blank.png")
    client.app.state.ocr_resources.engine = TemplateEngine({})

    response = client.post(
        "/ocr/jianbiao", json={"path": "blank.png", "form": "subgrade_spot_check"}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "未检测到简表表格，请重新拍摄"}


def test_route_rejects_unknown_template_before_ocr(client, settings):
    write_pool_photo(settings, source_photo(), "jianbiao.png")

    response = client.post("/ocr/jianbiao", json={"path": "jianbiao.png", "form": "JB-UNKNOWN"})

    assert response.status_code == 400
    assert "未配置简表模板" in response.json()["detail"]


def test_route_writes_outputs_inside_pool_when_out_set(client, settings):
    write_pool_photo(settings, source_photo(), "jianbiao.png")
    client.app.state.ocr_resources.engine = TemplateEngine({"inspector": "张三"})

    response = client.post(
        "/ocr/jianbiao",
        json={"path": "jianbiao.png", "form": "subgrade_spot_check", "out": "jianbiao-out"},
    )

    assert response.status_code == 200
    output = settings.projects_root / "jianbiao-out"
    exported = json.loads((output / "response.json").read_text(encoding="utf-8"))
    assert exported == response.json()
    diagnostics = json.loads((output / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["source_template_id"] == "subgrade_spot_check"
    assert len(diagnostics["readings"]) == 45
    assert (output / "aligned.png").is_file()


@pytest.mark.parametrize(
    "field,value",
    [("path", "../escape.png"), ("out", "../escape-out")],
)
def test_route_rejects_paths_outside_pool(client, settings, field, value):
    write_pool_photo(settings, source_photo(), "jianbiao.png")
    client.app.state.ocr_resources.engine = TemplateEngine({})
    payload = {"path": "jianbiao.png", "form": "subgrade_spot_check", field: value}

    response = client.post("/ocr/jianbiao", json=payload)

    assert response.status_code == 400
    assert "数据池" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"form": "subgrade_spot_check"},  # 缺少 path 与 img
        {"img": "invalid"},  # 缺少 form
        {"path": "jianbiao.png", "form": "subgrade_spot_check", "unknown": 1},  # 额外字段
    ],
)
def test_route_rejects_invalid_requests_before_recognition(client, payload):
    assert client.post("/ocr/jianbiao", json=payload).status_code == 422
