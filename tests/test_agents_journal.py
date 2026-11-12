"""日记生成 Agent 的模型边界、故障回退、超时与并发隔离。"""

import asyncio
import json

import httpx
import pytest

from app.agents.journal import JournalAgent
from app.llm import ModelService
from app.ocr.journal import generation
from app.schemas.ocr import JournalTextRequest
from tests.journal_helpers import (
    GENERATED,
    MAIN_WORK_PARTS,
    MIXED_MAIN_WORK_PARTS,
    JournalEngine,
    client_for,
    completion,
    post_journal,
)
from tests.ocr_helpers import make_ocr_settings


def test_route_generates_from_complete_source_without_titles(tmp_path):
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
    assert {
        key: value
        for key, value in response.json()["data"]["jsonData"]["fields"]["mainWork"].items()
        if key != "content"
    } == GENERATED
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]
    assert schema["name"] == "journal" and schema["strict"] is True
    assert set(schema["schema"]["required"]) == {"construction", "witness", "patrol"}
    assert json.loads(calls[0]["messages"][-1]["content"]) == {
        "content": "K3+280段路基填筑\n旁站路基碾压\n巡视挡土墙砌筑"
    }


def test_complete_titles_still_require_model(tmp_path):
    settings, client = client_for(tmp_path, lambda request: completion(json.dumps(GENERATED)))
    with client:
        response = post_journal(client, settings)
    assert response.status_code == 200
    work = response.json()["data"]["jsonData"]["fields"]["mainWork"]
    assert "主要施工情况" in work.pop("content")
    assert work == GENERATED


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
    assert len(calls) == 1 and "《视情况" in calls[0]["content"]
    assert {
        key: value
        for key, value in response.json()["data"]["jsonData"]["fields"]["mainWork"].items()
        if key != "content"
    } == GENERATED


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
    assert response.json()["data"]["jsonData"]["fields"]["mainWork"] == {
        "content": "",
        "construction": None,
        "witness": dict.fromkeys(GENERATED["witness"]),
        "patrol": dict.fromkeys(GENERATED["patrol"]),
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
    assert {
        key: value
        for key, value in response.json()["data"]["jsonData"]["fields"]["mainWork"].items()
        if key != "content"
    } == GENERATED


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
        content = json.loads(json.loads(request.content)["messages"][-1]["content"])["content"]
        await asyncio.sleep(0.01)
        active -= 1
        return completion(
            json.dumps(
                {
                    "construction": content,
                    "witness": dict.fromkeys(GENERATED["witness"]),
                    "patrol": dict.fromkeys(GENERATED["patrol"]),
                }
            )
        )

    settings = make_ocr_settings(tmp_path)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: completion("{}"))),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        agent = JournalAgent(service)
        first, second = await asyncio.gather(
            agent.generate(JournalTextRequest(content="K1+100填筑。")),
            agent.generate(JournalTextRequest(content="K2+200砌筑。")),
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

    settings = make_ocr_settings(tmp_path, journal_timeout_seconds=0.01)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda r: completion("{}"))),
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    try:
        agent = JournalAgent(service)
        from app.errors import JournalGenerationError

        with pytest.raises(JournalGenerationError):
            await generation.generate_work("K3+280段路基填筑", agent.generate)
    finally:
        await service.close()
