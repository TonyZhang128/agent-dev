"""mainWork 拆分 Agent 的模型边界、规则回退、502 映射、回退开关与并发隔离测试。"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import ModelService
from app.main import create_app
from app.ocr.journal import main_work_split as split
from app.ocr.journal.models import FieldReading
from app.ocr.journal.template import load_template
from app.schemas.ocr import MainWorkAssignment, MainWorkCategory, MainWorkSplitPlan
from tests.ocr_helpers import make_ocr_settings, ocr_result
from tests.test_ocr_journal import field_box, write_photo

MAIN_WORK_PARTS = (
    ("主要施工情况", "K3+280段路基填筑", 0.15, 0.28, 0.95),
    ("旁站情况", "旁站路基碾压", 0.45, 0.58, 0.94),
    ("巡视情况", "巡视挡土墙砌筑", 0.75, 0.88, 0.93),
)
# 没有标题或开头强标记，标题规则无法完整拆分，只能调用模型。
MIXED_MAIN_WORK_PARTS = (
    ("K3+280段路基填筑", "", 0.15, 0.28, 0.95),
    ("旁站路基碾压", "", 0.45, 0.58, 0.94),
    ("巡视挡土墙砌筑", "", 0.75, 0.88, 0.93),
)
FIELD_VALUES = {
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


def page_items(shape, parts=MAIN_WORK_PARTS):
    items = []
    for field in load_template().field_layouts():
        if field.key == "main_work":
            for label, text, label_at, value_at, confidence in parts:
                items.append((field_box(shape, field, at=label_at), label, 0.9))
                items.append((field_box(shape, field, at=value_at), text, confidence))
            continue
        text, confidence = FIELD_VALUES[field.key]
        items.append((field_box(shape, field), text, confidence))
    return items


class JournalEngine:
    """整页 OCR 固定返回栏目；mainWork 可按用例替换或省略。"""

    def __init__(self, *, parts=MAIN_WORK_PARTS):
        self.calls = 0
        self.parts = parts

    def __call__(self, picture):
        self.calls += 1
        # 只有第一次是整页图；后续都是栏目补充识别的裁剪图，返回空结果。
        if self.calls > 1:
            return ocr_result()
        return ocr_result(*page_items(picture.shape, self.parts))


def completion(content: str, *, finish: str = "stop", model: str = "test-qwen"):
    return httpx.Response(
        200,
        json={
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


def units_of(request) -> list[dict]:
    body = json.loads(request.content)
    return json.loads(body["messages"][-1]["content"])["units"]


def model_plan(units: list[dict]) -> str:
    """按标题范围和正文关键词返回合法计划；用于模拟真实模型的正确输出。"""
    assignments = []
    heading_category = None
    for unit in units:
        if unit["kind"] == "heading":
            heading_category = unit["heading_category"]
        category = heading_category or semantic_category(unit["text"])
        assignments.append({"unit_id": unit["id"], "category": category or "unknown"})
    return json.dumps({"assignments": assignments}, ensure_ascii=False)


def semantic_category(text: str) -> str | None:
    if "旁站" in text:
        return "witness"
    if "巡视" in text:
        return "patrol"
    if any(word in text for word in ("施工", "路基", "砌筑")):
        return "construction"
    return None


def client_for(tmp_path, respond, **overrides):
    settings = make_ocr_settings(tmp_path, **overrides)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    return settings, TestClient(create_app(service))


def post_journal(client, settings, **kwargs) -> httpx.Response:
    write_photo(settings)
    client.app.state.ocr_resources.engine = kwargs.pop("engine", JournalEngine())
    return client.post("/ocr/daily-logs-new", json={"path": "journal.png", **kwargs})


def test_route_uses_the_model_plan_when_rules_cannot_split(tmp_path):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return completion(model_plan(units_of(request)))

    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=MIXED_MAIN_WORK_PARTS))

    assert response.status_code == 200
    assert response.json()["data"]["fields"]["mainWork"] == {
        "construction": "K3+280段路基填筑",
        "witness": "旁站路基碾压",
        "patrol": "巡视挡土墙砌筑",
    }
    assert calls[0]["response_format"]["json_schema"]["name"] == "main_work_split"
    units = json.loads(calls[0]["messages"][-1]["content"])["units"]
    assert all(set(unit) == {"id", "text", "kind", "heading_category"} for unit in units)


def test_route_uses_headings_without_calling_the_model(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)

    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings)

    assert response.status_code == 200
    assert response.json()["data"]["fields"]["mainWork"] == {
        "construction": "主要施工情况K3+280段路基填筑",
        "witness": "旁站情况旁站路基碾压",
        "patrol": "巡视情况巡视挡土墙砌筑",
    }
    assert calls == []


def test_route_classifies_damaged_heading_without_rewriting_source(tmp_path):
    calls = []

    def respond(request):
        units = units_of(request)
        calls.append(units)
        category = None
        assignments = []
        for unit in units:
            if unit["text"] == "《视情况":
                assert unit["kind"] == "heading" and unit["heading_category"] is None
                category = "patrol"
            elif unit["kind"] == "heading":
                category = unit["heading_category"]
            assignments.append({"unit_id": unit["id"], "category": category})
        return completion(json.dumps({"assignments": assignments}, ensure_ascii=False))

    parts = (*MAIN_WORK_PARTS[:2], ("《视情况", "巡视挡土墙砌筑", 0.75, 0.88, 0.93))
    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=parts))
    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["data"]["fields"]["mainWork"]["patrol"] == "《视情况巡视挡土墙砌筑"


@pytest.mark.parametrize(
    "result,finish",
    [
        ("not JSON", "stop"),
        (json.dumps({"assignments": []}), "stop"),
        (json.dumps({"assignments": [{"unit_id": "u1", "category": "unknown"}]}), "length"),
    ],
    ids=["invalid-json", "empty-plan", "truncated"],
)
def test_route_returns_502_when_rules_fail_and_model_output_is_invalid(tmp_path, result, finish):
    def respond(request):
        return completion(result, finish=finish)

    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=MIXED_MAIN_WORK_PARTS))

    assert response.status_code == 502
    assert response.json() == {"detail": "监理日志主要工作情况无法可靠拆分，请核对照片后重试"}


def test_route_returns_a_controlled_502_when_model_and_rules_both_fail(tmp_path):
    def respond(request):
        units = units_of(request)
        return completion(
            json.dumps(
                {"assignments": [{"unit_id": unit["id"], "category": "unknown"} for unit in units]},
                ensure_ascii=False,
            )
        )

    settings, client = client_for(tmp_path, respond)
    mixed_parts = (("对路基进行了检查。", "复核旁站和巡视。", 0.3, 0.6, 0.9),)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=mixed_parts))

    assert response.status_code == 502
    assert response.json() == {"detail": "监理日志主要工作情况无法可靠拆分，请核对照片后重试"}
    assert "对路基进行了检查" not in response.text


def test_route_never_calls_the_model_for_empty_main_work(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        return completion("{}")

    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=()))

    assert response.status_code == 200
    assert response.json()["data"]["fields"]["mainWork"] == {
        "construction": None,
        "witness": None,
        "patrol": None,
    }
    assert calls == []


def test_main_work_agent_uses_the_configured_cloud_fallback(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.host == "api.deepseek.com":
            return completion(model_plan(units_of(request)), model="deepseek-flash")
        raise httpx.ConnectError("offline", request=request)

    settings, client = client_for(tmp_path, respond, llm_fallback_api_key="secret")
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=MIXED_MAIN_WORK_PARTS))

    assert response.status_code == 200
    assert len(calls) == 2
    assert response.json()["data"]["fields"]["mainWork"] == {
        "construction": "K3+280段路基填筑",
        "witness": "旁站路基碾压",
        "patrol": "巡视挡土墙砌筑",
    }


def test_other_agents_keep_the_configured_cloud_fallback(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.host == "api.deepseek.com":
            return completion("云端回答", model="deepseek-flash")
        raise httpx.ConnectError("offline", request=request)

    _settings, client = client_for(tmp_path, respond, llm_fallback_api_key="secret")
    with client:
        response = client.post(
            "/agents/chat",
            json={"user_id": "u", "session_id": "s", "message": "你好", "history": []},
        )

    assert response.status_code == 200
    assert response.json()["reply"] == "云端回答"
    assert len(calls) == 2


def readings(value: str) -> list[FieldReading]:
    return [
        FieldReading(
            layout=load_template().field_layouts()[8], boxes=(), value=value, confidence=0.9
        )
    ]


@pytest.mark.asyncio
async def test_concurrent_splits_do_not_share_units_or_plans():
    async def planner(request):
        text = request.units[0].text
        category = MainWorkCategory.patrol if "巡视" in text else MainWorkCategory.construction
        return MainWorkSplitPlan(
            assignments=[
                MainWorkAssignment(unit_id=unit.unit_id, category=category)
                for unit in request.units
            ]
        )

    patrol, construction = await asyncio.gather(
        split.split_main_work(readings("对K3+280段进行了旁站和巡视。"), planner),
        split.split_main_work(readings("对路基进行了填筑。"), planner),
    )

    assert patrol.strategy == construction.strategy == "llm"
    assert patrol.values.patrol == "对K3+280段进行了旁站和巡视。"
    assert patrol.values.construction is None
    assert construction.values.construction == "对路基进行了填筑。"
    assert construction.values.patrol is None
