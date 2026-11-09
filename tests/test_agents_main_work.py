"""mainWork 拆分 Agent 的模型边界、规则回退、502 映射、回退开关与并发隔离测试。"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.main_work import MainWorkAgent
from app.llm import ModelService
from app.main import create_app
from app.ocr.journal import main_work_split as split
from app.ocr.journal.template import load_template
from app.schemas.ocr import MainWorkRequest
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
        # 真实生产链应只调用一次OCR；重复调用会返回空，调用次数另作断言。
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


GENERATED = {
    "construction": "K3+280段路基填筑",
    "witness": "旁站路基碾压",
    "patrol": "巡视挡土墙砌筑",
}


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


def post_journal(client, settings, **kwargs):
    write_photo(settings)
    client.app.state.ocr_resources.engine = kwargs.pop("engine", JournalEngine())
    return client.post("/ocr/daily-logs-new", json={"path": "journal.png", **kwargs})


def test_route_uses_full_text_generation_when_keywords_are_incomplete(tmp_path):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        return completion(json.dumps(GENERATED, ensure_ascii=False))

    settings, client = client_for(tmp_path, respond)
    with client:
        engine = JournalEngine(parts=MIXED_MAIN_WORK_PARTS)
        response = post_journal(client, settings, engine=engine)
        assert engine.calls == 1
    assert response.status_code == 200
    assert response.json()["data"]["fields"]["mainWork"] == GENERATED
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]
    assert schema["name"] == "main_work" and schema["strict"] is True
    assert set(schema["schema"]["required"]) == {"construction", "witness", "patrol"}
    assert json.loads(calls[0]["messages"][-1]["content"]) == {
        "main_work": "K3+280段路基填筑\n旁站路基碾压\n巡视挡土墙砌筑"
    }


def test_complete_keywords_bypass_model_and_remove_titles(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ConnectError("offline", request=request)

    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings)
    assert response.status_code == 200
    assert response.json()["data"]["fields"]["mainWork"] == GENERATED
    assert not calls


def test_damaged_title_uses_generation_instead_of_unknown_ids(tmp_path):
    calls = []

    def respond(request):
        payload = json.loads(json.loads(request.content)["messages"][-1]["content"])
        calls.append(payload)
        return completion(json.dumps(GENERATED, ensure_ascii=False))

    parts = (*MAIN_WORK_PARTS[:2], ("《视情况", "巡视挡土墙砌筑", 0.75, 0.88, 0.93))
    settings, client = client_for(tmp_path, respond)
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=parts))
    assert response.status_code == 200
    assert len(calls) == 1 and "《视情况" in calls[0]["main_work"]
    assert response.json()["data"]["fields"]["mainWork"] == GENERATED


@pytest.mark.parametrize(
    "content,finish",
    [
        ("not JSON", "stop"),
        ("{}", "stop"),
        (json.dumps(GENERATED), "length"),
        (json.dumps({**GENERATED, "construction": "K9+999段路基填筑"}), "stop"),
        (json.dumps({"construction": None, "witness": None, "patrol": None}), "stop"),
    ],
)
def test_invalid_generation_returns_controlled_502_without_input_leak(tmp_path, content, finish):
    settings, client = client_for(tmp_path, lambda request: completion(content, finish=finish))
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=MIXED_MAIN_WORK_PARTS))
    assert response.status_code == 502
    assert response.json() == {"detail": "监理日志主要工作情况无法可靠拆分，请核对照片后重试"}
    assert "K3+280" not in response.text


def test_empty_main_work_does_not_call_model(tmp_path):
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
    assert not calls


def test_generation_keeps_configured_cloud_fallback(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.host == "api.deepseek.com":
            return completion(json.dumps(GENERATED), model="deepseek-flash")
        raise httpx.ConnectError("offline", request=request)

    settings, client = client_for(
        tmp_path, respond, llm_fallback_enabled=True, llm_fallback_api_key="secret"
    )
    with client:
        response = post_journal(client, settings, engine=JournalEngine(parts=MIXED_MAIN_WORK_PARTS))
    assert response.status_code == 200 and len(calls) == 2
    assert response.json()["data"]["fields"]["mainWork"] == GENERATED


def test_other_agents_keep_configured_cloud_fallback(tmp_path):
    calls = []

    def respond(request):
        calls.append(request)
        if request.url.host == "api.deepseek.com":
            return completion("云端回答", model="deepseek-flash")
        raise httpx.ConnectError("offline", request=request)

    _settings, client = client_for(
        tmp_path, respond, llm_fallback_enabled=True, llm_fallback_api_key="secret"
    )
    with client:
        response = client.post(
            "/agents/chat",
            json={"user_id": "u", "session_id": "s", "message": "你好", "history": []},
        )
    assert response.status_code == 200 and len(calls) == 2
    assert response.json()["reply"] == "云端回答"


@pytest.mark.asyncio
async def test_generation_serializes_model_calls_without_sharing_content(tmp_path):
    active = 0
    peak = 0

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        content = json.loads(json.loads(request.content)["messages"][-1]["content"])["main_work"]
        await asyncio.sleep(0.01)
        active -= 1
        return completion(json.dumps({"construction": content, "witness": None, "patrol": None}))

    settings = make_ocr_settings(tmp_path)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: completion("{}"))),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        agent = MainWorkAgent(service)
        first, second = await asyncio.gather(
            agent.generate(MainWorkRequest(main_work="K1+100填筑。")),
            agent.generate(MainWorkRequest(main_work="K2+200砌筑。")),
        )
        assert first.construction == "K1+100填筑。" and second.construction == "K2+200砌筑。"
        assert peak == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_generation_timeout_is_bounded_and_controlled(tmp_path):
    async def respond(request):
        await asyncio.sleep(0.2)
        return completion(json.dumps(GENERATED))

    settings = make_ocr_settings(tmp_path, main_work_split_timeout_seconds=0.01)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: completion("{}"))),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        agent = MainWorkAgent(service)
        from app.errors import MainWorkSplitError
        from tests.test_ocr_main_work_generation import readings

        with pytest.raises(MainWorkSplitError):
            await split.split_main_work(readings("K3+280段路基填筑"), agent.generate)
    finally:
        await service.close()
