"""`POST /ocr/daily-logs` 的识别链路、业务映射、来源校验和错误映射。

离线用例模拟 RapidOCR 边界，照片由测试生成，不读取模板库或数据池。
监理日志的固定栏目按现场《监理日记》表样裁剪，`process()` 负责映射业务结构。
"""

import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ocr import daily_logs
from tests.ocr_helpers import make_ocr_settings, ocr_result

# 与 daily_logs.LAYOUT 的顺序一致，逐格返回 OCR 结果。
TEXTS = (
    "测试高速公路项目",
    "JL-001",
    "测试监理机构",
    "张三",
    "晴",
    "专业监理工程师",
    "2026年10月3日",
    "李四",
    "路基填筑 100m",
    "旁站检查 2 次",
    "巡视检查",
    "无",
    "继续填筑",
)


class SequentialEngine:
    """按调用顺序返回监理日志各栏目的识别结果。"""

    def __init__(self, texts=TEXTS):
        self.texts = iter(texts)

    def __call__(self, image):
        text = next(self.texts)
        return ocr_result(([[10, 10], [200, 10], [200, 40], [10, 40]], text, 0.98))


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings=settings)) as client:
        yield client


def write_photo(settings, name: str = "log.png", width: int = 600, height: int = 849):
    image = np.full((height, width, 3), 255, np.uint8)
    cv2.rectangle(image, (20, 20), (width - 20, height - 20), (0, 0, 0), 3)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    (settings.projects_root / name).write_bytes(buffer.tobytes())
    return image


def test_daily_logs_recognizes_regions_and_returns_draft_contract(client, settings):
    write_photo(settings)
    client.app.state.ocr_resources.engine = SequentialEngine()

    response = client.post("/ocr/daily-logs", json={"path": "log.png"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "data"}
    assert body["status"] == 200
    data = body["data"]
    assert set(data) == {
        "form",
        "formName",
        "frame",
        "recognized",
        "detail",
        "processed",
        "warning",
        "image",
        "ms",
    }
    assert data["form"] == "JLB13"
    assert data["formName"] == "监理日志"
    assert data["recognized"] == {
        "project": "测试高速公路项目",
        "number": "JL-001",
        "supervision_org": "测试监理机构",
        "recorder": "张三",
        "weather": "晴",
        "position": "专业监理工程师",
        "date": "2026-10-03",
        "reviewer": "李四",
        "construction": "路基填筑100m",
        "witness": "旁站检查2次",
        "patrol": "巡视检查",
        "issues": "无",
        "next_day_plan": "继续填筑",
    }
    assert data["processed"] == {
        "taskId": None,
        "documentType": "supervision_diary",
        "common": {
            "projectName": "测试高速公路项目",
            "documentNo": "JL-001",
            "supervisionOrg": "测试监理机构",
            "recorderName": "张三",
            "recorderPosition": "专业监理工程师",
            "weather": "晴",
            "logDate": "2026-10-03",
            "reviewerName": "李四",
        },
        "fields": {
            "mainWork": {
                "construction": "路基填筑100m",
                "witness": "旁站检查2次",
                "patrol": "巡视检查",
            },
            "issues": "无",
            "nextDayPlan": "继续填筑",
        },
    }
    assert data["warning"] == ""
    assert data["image"] == {"width": 600, "height": 849}
    assert data["frame"]["how"] == "contour"
    assert [item["field"] for item in data["detail"]] == [
        item["field"] for item in daily_logs.LAYOUT
    ]
    detail = {item["field"]: item for item in data["detail"]}
    assert detail["date"]["value"] == "2026-10-03"
    assert detail["date"]["conf"] == pytest.approx(0.98)
    assert detail["construction"]["rect"][0] >= 0
    assert isinstance(data["ms"], int) and data["ms"] >= 0


def test_daily_logs_accepts_base64_image_and_prefers_it(client, settings):
    image = write_photo(settings)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    client.app.state.ocr_resources.engine = SequentialEngine()

    response = client.post(
        "/ocr/daily-logs",
        json={
            "path": "missing.png",
            "img": "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii"),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["recognized"]["supervision_org"] == "测试监理机构"
    assert response.json()["data"]["image"] == {"width": 600, "height": 849}


@pytest.mark.parametrize("payload", [{}, {"path": "  "}, {"img": "\n"}])
def test_daily_logs_requires_a_photo_source(client, payload):
    assert client.post("/ocr/daily-logs", json=payload).status_code == 422


def test_daily_logs_rejects_missing_or_invalid_photo(client, settings):
    (settings.projects_root / "invalid.png").write_bytes(b"not an image")

    missing = client.post("/ocr/daily-logs", json={"path": "missing.png"})
    assert missing.status_code == 400
    assert set(missing.json()) == {"detail"}

    invalid = client.post("/ocr/daily-logs", json={"path": "invalid.png"})
    assert invalid.status_code == 400
    assert set(invalid.json()) == {"detail"}


def test_daily_logs_maps_model_failure_to_503(client, settings):
    write_photo(settings)

    def broken(image):
        raise RuntimeError("model download failed")

    client.app.state.ocr_resources.engine = broken

    response = client.post("/ocr/daily-logs", json={"path": "log.png"})

    assert response.status_code == 503
    assert "model download failed" not in response.json()["detail"]


def test_daily_log_warp_anchors_table_frame_to_known_page_rectangle():
    page = np.array([[0, 0], [100, 0], [100, 141.42], [0, 141.42]], np.float32)
    table = np.array([[0, 0], [100, 0], [100, 111.4], [0, 111.4]], np.float32)
    height = round(daily_logs.W * daily_logs.PAGE_ASPECT)

    page_destination, _size = daily_logs._destination(page, "contour")
    assert page_destination[0].tolist() == [0.0, 0.0]
    assert page_destination[2].tolist() == [daily_logs.W, height]

    x0, y0, x1, y1 = daily_logs.TABLE
    table_destination, _ = daily_logs._destination(table, "contour")
    assert table_destination[0].tolist() == pytest.approx([x0 * daily_logs.W, y0 * height])
    assert table_destination[2].tolist() == pytest.approx([x1 * daily_logs.W, y1 * height])


def test_daily_logs_echoes_task_id(client, settings):
    write_photo(settings)
    client.app.state.ocr_resources.engine = SequentialEngine()

    response = client.post("/ocr/daily-logs", json={"path": "log.png", "taskId": " 42 "})

    assert response.status_code == 200
    assert response.json()["data"]["processed"]["taskId"] == "42"


def test_process_maps_recognized_and_leaves_missing_fields_null():
    processed = daily_logs.process(
        {"project": " 项目 ", "date": "2026-10-03", "witness": "旁站"},
        [],
        "42",
    )

    assert processed["taskId"] == "42"
    assert processed["documentType"] == "supervision_diary"
    assert processed["common"]["projectName"] == "项目"
    assert processed["common"]["documentNo"] is None
    assert processed["fields"]["mainWork"] == {
        "construction": None,
        "witness": "旁站",
        "patrol": None,
    }
    assert processed["fields"]["nextDayPlan"] is None


def test_process_returns_null_fields_for_empty_recognition():
    processed = daily_logs.process({}, [])

    assert processed["taskId"] is None
    assert all(value is None for value in processed["common"].values())
    assert processed["fields"] == {
        "mainWork": {"construction": None, "witness": None, "patrol": None},
        "issues": None,
        "nextDayPlan": None,
    }
