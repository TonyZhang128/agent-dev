"""已批准的三入口：原文、完整框、坐标回投和独立处理能力。"""

import base64
import io
import json

import cv2
import numpy as np
import pytest
from PIL import Image

from app.ocr.journal import output
from app.ocr.journal.models import (
    CanvasAlignment,
    FieldLayout,
    FieldReading,
    JournalRecognition,
    LoadedPhoto,
    OcrTextBox,
)
from app.ocr.journal.template import FIELD_KEYS
from tests.ocr_helpers import ocr_result
from tests.test_agents_main_work import GENERATED, client_for, completion
from tests.test_ocr_journal import PageEngine, full_page_items, table_photo, write_photo


class CompleteEngine:
    """包含栏目外框和重复框，验证调试结果没有在归属时丢失。"""

    def __init__(self):
        self.calls = 0
        self.items = []

    def __call__(self, picture):
        self.calls += 1
        self.items = full_page_items(picture.shape)
        self.items.extend(
            [
                ([[0, 0], [20, 0], [20, 10], [0, 10]], "表外原始文字", 0.42),
                self.items[0],
            ]
        )
        return ocr_result(*self.items)


def test_recognize_returns_all_boxes_and_unsplit_text_without_model(tmp_path):
    calls = []

    def unavailable(request):
        calls.append(request)
        raise AssertionError("纯 OCR 不应调用语言模型")

    settings, client = client_for(tmp_path, unavailable)
    with client:
        write_photo(settings)
        engine = CompleteEngine()
        client.app.state.ocr_resources.engine = engine
        response = client.post(
            "/ocr/journal/recognize", json={"path": "journal.png", "taskId": " 42 "}
        )
        assert response.status_code == 200, response.text
        assert engine.calls == 1
        assert calls == []
        payload = response.json()
        assert set(payload) == {"status", "message", "data"}
        data = payload["data"]
        assert data["taskId"] == "42"
        assert data["image"] == {
            "width": 900,
            "height": 1273,
            "coordinateSpace": "exif_corrected_original",
        }
        boxes = data["boxes"]
        assert len(boxes) == len(engine.items)
        assert [box["text"] for box in boxes] == [item[1] for item in engine.items]
        assert [box["confidence"] for box in boxes] == pytest.approx(
            [item[2] for item in engine.items]
        )
        assert len({box["id"] for box in boxes}) == len(boxes)
        readings = {field["key"]: field for field in data["fields"]}
        assert set(readings) == set(FIELD_KEYS)
        main_work = readings["main_work"]
        assert main_work["text"] == (
            "主要施工情况\nK3+280段路基填筑\n旁站情况\n旁站路基碾压\n巡视情况\n挡土墙错缝砌筑"
        )
        assert readings["supervision_org"]["text"] == "测试监理机构"
        assert readings["date"]["text"] == "2026-11-11"
        references = {box_id for field in readings.values() for box_id in field["boxIds"]}
        assert references <= {box["id"] for box in boxes}
        assert boxes[-1]["id"] not in references  # 重复框仅保留原始记录，不重复归属
        assert boxes[-2]["id"] not in references  # 表外框仍可诊断
        split = client.post("/ocr/journal/process", json={"main_work": main_work["text"]})
        assert split.status_code == 200
        assert split.json() == {**GENERATED, "patrol": "挡土墙错缝砌筑"}
        assert engine.calls == 1
        assert calls == []


def test_journal_is_renamed_without_legacy_alias(tmp_path):
    settings, client = client_for(tmp_path, lambda request: pytest.fail("规则不应调用模型"))
    with client:
        write_photo(settings)
        client.app.state.ocr_resources.engine = PageEngine()
        assert client.post("/ocr/daily-logs-new", json={"path": "journal.png"}).status_code == 404
        response = client.post("/ocr/journal", json={"path": "journal.png"})
        assert response.status_code == 200
        assert response.json()["data"]["fields"]["mainWork"] == {
            **GENERATED,
            "patrol": "挡土墙错缝砌筑",
        }


@pytest.mark.parametrize("text", ["", " \n", "施工情况：\n旁站情况：\n巡视情况："])
def test_process_accepts_empty_content_without_ocr_or_model(tmp_path, text):
    settings, client = client_for(tmp_path, lambda request: pytest.fail("空文本不应调用模型"))
    with client:
        client.app.state.ocr_resources.engine = lambda picture: pytest.fail("不能调用 OCR")
        response = client.post("/ocr/journal/process", json={"main_work": text})
        assert response.status_code == 200
        assert response.json() == dict.fromkeys(("construction", "witness", "patrol"))


def test_process_uses_real_agent_and_checks_facts(tmp_path):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return completion(json.dumps(GENERATED, ensure_ascii=False))

    _, client = client_for(tmp_path, respond)
    source = "K3+280段路基填筑\n旁站路基碾压\n巡视挡土墙砌筑"
    with client:
        client.app.state.ocr_resources.engine = lambda picture: pytest.fail("不能调用 OCR")
        response = client.post("/ocr/journal/process", json={"main_work": source})
        assert response.status_code == 200
        assert response.json() == GENERATED
    assert len(requests) == 1
    assert json.loads(requests[0]["messages"][-1]["content"]) == {"main_work": source}


@pytest.mark.parametrize(
    "payload", [{}, {"main_work": None}, {"main_work": 12}, {"main_work": "", "extra": 1}]
)
def test_process_rejects_invalid_requests(tmp_path, payload):
    _, client = client_for(tmp_path, lambda request: pytest.fail("不能调用模型"))
    with client:
        response = client.post("/ocr/journal/process", json=payload)
        assert response.status_code == 422
        assert all(set(error) <= {"type", "loc", "msg"} for error in response.json()["detail"])


def test_process_rejects_changed_facts_and_preserves_length_policy(tmp_path):
    _, client = client_for(tmp_path, lambda request: completion(json.dumps(GENERATED)))
    with client:
        bad = client.post("/ocr/journal/process", json={"main_work": "K3+281段路基填筑"})
        assert bad.status_code == 502
        assert bad.json() == {"detail": "监理日志主要工作情况无法可靠拆分，请核对照片后重试"}
        long = client.post("/ocr/journal/process", json={"main_work": "正文" * 2001})
        assert long.status_code == 502
        source = "施工情况：" + "填筑。" * 1400 + "\n旁站情况：旁站。\n巡视情况：巡视。"
        ruled = client.post("/ocr/journal/process", json={"main_work": source})
        assert ruled.status_code == 200
        assert ruled.json()["construction"] == "填筑。" * 1400


def test_recognize_preserves_empty_columns(tmp_path):
    settings, client = client_for(tmp_path, lambda request: pytest.fail("不能调用模型"))
    with client:
        write_photo(settings)
        client.app.state.ocr_resources.engine = lambda picture: ocr_result()
        response = client.post("/ocr/journal/recognize", json={"path": "journal.png"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["boxes"] == []
        assert len(data["fields"]) == 11
        assert all(
            field["text"] is None and field["confidence"] == 0.0 and field["boxIds"] == []
            for field in data["fields"]
        )


def test_geometry_maps_perspective_and_downscale_to_original_pixels():
    # 人工标注原图位置，通过已知正向矩阵构造 OCR 输入，独立验证回投结果。
    matrix = np.array([[1.2, 0.1, 10], [0.05, 0.9, 20], [0.0002, 0.0001, 1.0]])
    original = np.array([[[100, 200], [300, 210], [290, 260], [95, 250]]], dtype=np.float64)
    ratio = 0.5
    on_canvas = cv2.perspectiveTransform(original * ratio, matrix)[0]
    box = OcrTextBox(
        "原始文字",
        float(on_canvas[:, 0].min()),
        float(on_canvas[:, 1].min()),
        float(on_canvas[:, 0].max()),
        float(on_canvas[:, 1].max()),
        0.87,
        tuple(map(tuple, on_canvas)),
    )
    canvas = np.zeros((200, 300, 3), np.uint8)
    layout = FieldLayout("main_work", "主要工作", (0, 0, 1, 1))
    reading = FieldReading(layout, (box,), "原始文字", 0.87, True, visible_fraction=0.75)
    table = np.array([[50, 60], [550, 70], [540, 360], [40, 350]], dtype=np.float64)
    recognition = JournalRecognition(
        LoadedPhoto(
            np.zeros((400, 600, 3), np.uint8), np.zeros((400, 600), np.uint8), 1200, 800, ratio
        ),
        CanvasAlignment(canvas, table, (0, 0, 1, 1), matrix, np.ones((200, 300), np.uint8), (1.0,)),
        (reading,),
        "test",
        boxes=(box,),
    )
    response = output.build_recognition_response(recognition).model_dump(mode="json")
    data = response["data"]
    assert np.asarray(data["boxes"][0]["polygon"]) == pytest.approx(original[0])
    assert np.asarray(data["tablePolygon"]) == pytest.approx(table)
    assert data["image"]["width"] == 1200
    assert data["fields"][0]["ambiguous"] is True
    assert data["fields"][0]["visibleFraction"] == 0.75
    assert data["fields"][0]["boxIds"] == [data["boxes"][0]["id"]]
    # 原图外的模板范围不裁剪；正向变回画布应等于完整模板矩形。
    projected = cv2.perspectiveTransform(np.asarray([data["fields"][0]["polygon"]]) * ratio, matrix)
    assert projected == pytest.approx(
        np.array([[[0, 0], [300, 0], [300, 200], [0, 200]]]), abs=1e-7
    )


@pytest.mark.parametrize("exif,scale", [(False, 1), (True, 1), (False, 5)])
def test_recognize_geometry_on_rotated_exif_and_large_photos(tmp_path, exif, scale):
    picture = table_photo()
    rotation = cv2.getRotationMatrix2D((450, 636), 3, scale)
    expected = cv2.transform(
        np.float32([[[100, 250], [800, 250], [800, 1150], [100, 1150]]]), rotation
    )[0]
    # 大图使用原图等比例放大，旋转则使用独立仿射位置作为预期。
    if scale > 1:
        picture = cv2.resize(picture, None, fx=scale, fy=scale)
        expected = np.float32([[100, 250], [800, 250], [800, 1150], [100, 1150]]) * scale
    else:
        picture = cv2.warpAffine(picture, rotation, (900, 1273), borderValue=(255, 255, 255))
    image = Image.fromarray(cv2.cvtColor(picture, cv2.COLOR_BGR2RGB))
    metadata = Image.Exif()
    if exif:
        image = image.transpose(Image.Transpose.ROTATE_90)
        metadata[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95, exif=metadata)
    _, client = client_for(tmp_path, lambda request: pytest.fail("不能调用模型"))
    with client:
        client.app.state.ocr_resources.engine = PageEngine()
        response = client.post(
            "/ocr/journal/recognize", json={"img": base64.b64encode(buffer.getvalue()).decode()}
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["image"]["width"] == 900 * scale
        assert data["image"]["height"] == 1273 * scale
        assert np.asarray(data["tablePolygon"]) == pytest.approx(expected, abs=8 * scale)


def test_recognize_retains_ambiguous_and_uncovered_boxes(tmp_path):
    from app.ocr.journal import field_matching

    canvas = np.full((100, 100, 3), 255, np.uint8)
    cross = OcrTextBox("跨栏", 40, 10, 60, 30, 0.92)
    hidden = OcrTextBox("未拍全的栏目", 60, 60, 90, 80, 0.94)
    layouts = (
        FieldLayout("project", "项目", (0, 0, 0.5, 0.5)),
        FieldLayout("number", "编号", (0.5, 0, 0.5, 0.5)),
        FieldLayout("main_work", "主要工作", (0, 0.5, 1, 0.5)),
    )
    mask = np.full((100, 100), 255, np.uint8)
    mask[50:] = 0
    readings = field_matching.match_fields(
        canvas, layouts, (0, 0, 1, 1), [cross, hidden], valid_mask=mask
    )
    identity = np.eye(3)
    table = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], dtype=np.float64)
    recognition = JournalRecognition(
        LoadedPhoto(canvas, canvas[:, :, 0], 100, 100),
        CanvasAlignment(canvas, table, (0, 0, 1, 1), identity, mask, (1.0,)),
        tuple(readings),
        boxes=(cross, hidden),
    )
    data = output.build_recognition_response(recognition).data
    assert [box.text for box in data.boxes] == ["跨栏", "未拍全的栏目"]
    assert all(
        field.ambiguous and field.text is None and field.boxIds == [] for field in data.fields
    )
    assert data.fields[2].visibleFraction == 0
    assert data.boxes[0].polygon == ((40, 10), (60, 10), (60, 30), (40, 30))


@pytest.mark.parametrize("scenario", ["unavailable", "timeout", "invalid"])
def test_process_returns_controlled_model_failures(tmp_path, scenario):
    import httpx

    def respond(request):
        if scenario == "unavailable":
            raise httpx.ConnectError("private upstream details", request=request)
        if scenario == "timeout":
            raise httpx.ReadTimeout("private upstream details", request=request)
        return completion("not structured JSON")

    _, client = client_for(tmp_path, respond)
    with client:
        response = client.post("/ocr/journal/process", json={"main_work": "K1+100填筑。"})
        assert response.status_code == 502
        assert response.json() == {"detail": "监理日志主要工作情况无法可靠拆分，请核对照片后重试"}


def test_recognize_keeps_blank_detections_without_assigning_them(tmp_path):
    settings, client = client_for(tmp_path, lambda request: pytest.fail("不能调用模型"))
    with client:
        write_photo(settings)

        def detect(picture):
            items = full_page_items(picture.shape)
            # 用同一正文框的坐标模拟检测成功但文字为空的结果，不能影响字段归属。
            items.extend([(items[0][0], "", 0.1), (items[0][0], " \n", 0.2)])
            return ocr_result(*items)

        client.app.state.ocr_resources.engine = detect
        response = client.post("/ocr/journal/recognize", json={"path": "journal.png"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert [box["text"] for box in data["boxes"]][-2:] == ["", " \n"]
        empty_ids = {box["id"] for box in data["boxes"][-2:]}
        assert not any(empty_ids & set(field["boxIds"]) for field in data["fields"])
        assert (
            next(field["text"] for field in data["fields"] if field["key"] == "project")
            == "成乐高速公路扩容建设"
        )
