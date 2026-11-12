"""完整识别结果到业务日记：真实 Agent、模型 HTTP 边界与两阶段串联。"""

import copy
import json

import pytest

from tests.journal_helpers import client_for, completion
from tests.test_ocr_journal import PageEngine, write_photo

PATROL_KEYS = (
    "inspectionScope",
    "mainConstruction",
    "qualitySafetyEnvironment",
    "problemsAndActions",
)
WITNESS_KEYS = (
    "supervisionProject",
    "constructionProcess",
    "supervisionWork",
    "mainDataRecords",
    "problemsAndResults",
)
GENERATED_WORK = {
    "construction": "K3+280段路基填筑",
    "patrol": {**dict.fromkeys(PATROL_KEYS), "mainConstruction": "挡土墙错缝砌筑"},
    "witness": {**dict.fromkeys(WITNESS_KEYS), "supervisionWork": "旁站路基碾压"},
}


def recognition_input(text):
    keys = (
        "project",
        "number",
        "supervision_org",
        "recorder",
        "weather",
        "position",
        "date",
        "reviewer",
        "main_work",
        "issues",
        "next_day_plan",
    )
    return {
        "taskId": None,
        "documentType": "supervision_diary",
        "image": {"width": 100, "height": 100, "coordinateSpace": "exif_corrected_original"},
        "tablePolygon": [[0, 0], [100, 0], [100, 100], [0, 100]],
        "boxes": [],
        "fields": [
            {
                "key": key,
                "label": key,
                "text": text if key == "main_work" else None,
                "confidence": 0.0,
                "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                "boxIds": [],
                "ambiguous": False,
                "visibleFraction": 1.0,
            }
            for key in keys
        ],
    }


def test_combined_and_two_stage_requests_return_same_business_result(tmp_path):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return completion(json.dumps(GENERATED_WORK, ensure_ascii=False))

    settings, client = client_for(tmp_path, respond)
    with client:
        write_photo(settings)
        engine = PageEngine()
        client.app.state.ocr_resources.engine = engine
        recognized = client.post("/ocr/journal/recognize", json={"path": "journal.png"})
        assert recognized.status_code == 200
        assert calls == []
        processed = client.post("/ocr/journal/process", json=recognized.json()["data"])
        assert processed.status_code == 200, processed.text
        assert engine.calls == 1
        combined = client.post("/ocr/journal", json={"path": "journal.png"})
        assert combined.status_code == 200, combined.text
        assert engine.calls == 2
        assert combined.json() == processed.json()
    assert len(calls) == 2  # 完整小标题也必须调用 Agent。
    body = processed.json()
    assert set(body) == {"code", "message", "data"}
    assert body["code"] == 200 and body["message"] == "success"
    diary = body["data"]["jsonData"]
    assert diary["common"]["projectName"] == "成乐高速公路扩容建设"
    assert diary["common"]["logDate"] == "2026-11-11"
    assert diary["fields"]["issues"] == "挡土墙墙背回填局部压实不足"
    assert diary["fields"]["nextDayPlan"] == "见证水稳基层检测"
    work = diary["fields"]["mainWork"]
    assert work == {
        "content": "主要施工情况\nK3+280段路基填筑\n旁站情况\n旁站路基碾压\n巡视情况\n挡土墙错缝砌筑",
        **GENERATED_WORK,
    }


def test_corrected_text_is_source_and_other_columns_are_preserved(tmp_path):
    calls = []
    generated = {
        "construction": "K1+100段填筑。",
        "patrol": dict.fromkeys(PATROL_KEYS),
        "witness": dict.fromkeys(WITNESS_KEYS),
    }

    def respond(request):
        calls.append(json.loads(request.content))
        return completion(json.dumps(generated))

    _, client = client_for(tmp_path, respond)
    source = recognition_input("  K1+100段填筑。\n")
    source["fields"][0]["text"] = " 工程名 "
    source["fields"][-1]["text"] = "明日K9+999检测，不是当日工作"
    before = copy.deepcopy(source)
    with client:
        client.app.state.ocr_resources.engine = lambda picture: pytest.fail("process 不能执行 OCR")
        response = client.post("/ocr/journal/process", json=source)
    assert response.status_code == 200, response.text
    diary = response.json()["data"]["jsonData"]
    assert diary["common"]["projectName"] == " 工程名 "
    assert diary["fields"]["mainWork"] == {"content": "  K1+100段填筑。\n", **generated}
    assert diary["fields"]["nextDayPlan"] == "明日K9+999检测，不是当日工作"
    assert json.loads(calls[0]["messages"][-1]["content"]) == {"content": "  K1+100段填筑。\n"}
    assert source == before


@pytest.mark.parametrize("text", [None, "", " \n"])
def test_empty_work_keeps_nested_fields_without_model(tmp_path, text):
    _, client = client_for(tmp_path, lambda request: pytest.fail("空记录不调用模型"))
    with client:
        response = client.post("/ocr/journal/process", json=recognition_input(text))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["jsonData"]["fields"]["mainWork"] == {
        "content": text or "",
        "construction": None,
        "patrol": dict.fromkeys(PATROL_KEYS),
        "witness": dict.fromkeys(WITNESS_KEYS),
    }


@pytest.mark.parametrize("defect", ["missing", "duplicate", "old", "extra"])
def test_process_rejects_incomplete_or_ambiguous_input(tmp_path, defect):
    source = recognition_input("填筑。")
    if defect == "missing":
        source["fields"].pop()
    elif defect == "duplicate":
        source["fields"].append(source["fields"][0])
    elif defect == "old":
        source = {"main_work": "填筑。"}
    else:
        source["extra"] = 1
    _, client = client_for(tmp_path, lambda request: pytest.fail("非法输入不能调用模型"))
    with client:
        response = client.post("/ocr/journal/process", json=source)
    assert response.status_code == 422
