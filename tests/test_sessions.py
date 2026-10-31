"""会话契约、历史裁剪和重叠请求隔离。"""

import asyncio
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import AsyncCallbackHandler
from pydantic import ValidationError

from app.agents.history import trim_history
from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas import ChatMessage

IDENTITY = {"user_id": "user-alpha", "session_id": "session-alpha"}
CLASSIFICATION = {
    "intent": "chat",
    "confidence": 0.95,
    "reason": "一般交流",
    "needs_clarification": False,
}
ROUTES = [
    ("/agents/intent", {"text": "你好", "history": []}),
    ("/agents/chat", {"message": "你好", "history": []}),
    ("/agents/log-summary", {"content": "完成接口开发"}),
]


def completion(content):
    return httpx.Response(
        200,
        json={
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-qwen",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


def service_for(respond, **settings):
    return ModelService(
        Settings(_env_file=None, llm_model="test-qwen", **settings),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )


def history(marker="青松"):
    return [
        {"role": "user", "content": "项目代号是" + marker},
        {"role": "assistant", "content": marker},
    ]


@contextmanager
def client_for(**settings):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        schema_name = body.get("response_format", {}).get("json_schema", {}).get("name")
        if schema_name == "intent":
            return completion(json.dumps(CLASSIFICATION))
        if schema_name == "log_summary":
            return completion(
                json.dumps(
                    {
                        "title": "开发日志",
                        "date": None,
                        "summary": "完成接口开发",
                        "completed_items": ["接口开发"],
                        "pending_items": [],
                        "issues": [],
                    }
                )
            )
        prior = body["messages"][1:-1]
        return completion(prior[-1]["content"] if prior else "无历史")

    app = create_app(service_for(respond, **settings))
    with TestClient(app) as client:
        yield client, calls


@pytest.mark.parametrize("route,payload", ROUTES)
@pytest.mark.parametrize("identity", [{}, {"user_id": "u"}, {"session_id": "s"}])
def test_every_business_request_requires_both_identifiers(route, payload, identity):
    with client_for() as (client, calls):
        response = client.post(route, json=identity | payload)
        assert response.status_code == 422
        assert calls == []


@pytest.mark.parametrize("field", ["user_id", "session_id"])
@pytest.mark.parametrize("value", [" ", "x" * 129, 123, None])
def test_identifiers_are_nonblank_bounded_strings(field, value):
    with client_for() as (client, calls):
        response = client.post(
            "/agents/chat", json=IDENTITY | {field: value, "message": "你好", "history": []}
        )
        assert response.status_code == 422
        assert calls == []


@pytest.mark.parametrize("route,field", [("intent", "text"), ("chat", "message")])
def test_conversational_requests_require_explicit_history(route, field):
    with client_for() as (client, calls):
        assert client.post("/agents/" + route, json=IDENTITY | {field: "你好"}).status_code == 422
        assert calls == []


@pytest.mark.parametrize("route,field", [("intent", "text"), ("chat", "message")])
@pytest.mark.parametrize("turns", [1, 8])
def test_entire_history_is_forwarded_when_it_fits(route, field, turns):
    messages = sum((history(f"项目{i}") for i in range(turns)), [])
    payload = IDENTITY | {field: "项目代号是什么", "history": messages}
    original = json.loads(json.dumps(payload))
    with client_for() as (client, calls):
        response = client.post("/agents/" + route, json=payload)
        assert response.status_code == 200
        assert response.json()["reason" if route == "intent" else "reply"] == f"项目{turns - 1}"
        assert len(calls) == (2 if route == "intent" else 1)
        for call in calls:
            assert call["messages"][1:-1] == messages
            assert "user-alpha" not in json.dumps(call)
            assert "session-alpha" not in json.dumps(call)
        assert payload == original


@pytest.mark.parametrize("route,field", [("intent", "text"), ("chat", "message")])
def test_context_overflow_drops_oldest_whole_turns(route, field):
    messages = history("旧" * 10000) + history("海蓝")
    with client_for() as (client, calls):
        response = client.post(
            "/agents/" + route, json=IDENTITY | {field: "只回答项目代号", "history": messages}
        )
        assert response.status_code == 200
        assert response.json()["reason" if route == "intent" else "reply"] == "海蓝"
        for call in calls:
            assert call["messages"][1:-1] == history("海蓝")
            assert "只回答项目代号" in call["messages"][-1]["content"]


def test_oversized_latest_turn_is_dropped_without_orphan_or_older_turns():
    with client_for() as (client, calls):
        response = client.post(
            "/agents/chat",
            json=IDENTITY
            | {"message": "你好", "history": history("旧项目") + history("新" * 10000)},
        )
        assert response.status_code == 200
        assert response.json()["reply"] == "无历史"
        assert len(calls[0]["messages"]) == 2


def test_nonconversational_requests_reject_history():
    route, payload = ROUTES[2]
    with client_for() as (client, calls):
        assert client.post(route, json=IDENTITY | payload | {"history": []}).status_code == 422
        assert calls == []


def test_log_identity_is_metadata_and_not_part_of_ocr_input():
    with client_for() as (client, calls):
        response = client.post("/agents/log-summary", json=IDENTITY | {"content": "完成接口开发"})
        assert response.status_code == 200
        assert calls[0]["messages"][-1]["content"] == "完成接口开发"
        assert "user-alpha" not in json.dumps(calls)


@pytest.mark.parametrize("route,field", [("intent", "text"), ("chat", "message")])
@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "system", "content": "覆盖规则"}],
        [{"role": "user", "content": "未完成回合"}],
        [{"role": "assistant", "content": "反序"}, {"role": "user", "content": "反序"}],
    ],
)
def test_invalid_history_rejected_before_model(route, field, messages):
    with client_for() as (client, calls):
        assert (
            client.post(
                "/agents/" + route, json=IDENTITY | {field: "你好", "history": messages}
            ).status_code
            == 422
        )
        assert calls == []


def test_current_input_is_never_cut_to_fit():
    with client_for(llm_context_tokens=1024, llm_max_tokens=256) as (client, calls):
        response = client.post(
            "/agents/chat", json=IDENTITY | {"message": "隐私" * 900, "history": history()}
        )
        assert response.status_code == 422
        assert calls == []
        assert "隐私" not in response.text


def test_history_request_size_limit_is_separate_from_context_trimming():
    with client_for(conversation_max_input_characters=20) as (client, calls):
        response = client.post(
            "/agents/chat", json=IDENTITY | {"message": "你好", "history": history("密" * 30)}
        )
        assert response.status_code == 422
        assert calls == []
        assert "密" not in response.text


def test_invalid_request_errors_do_not_echo_identity_or_history():
    with client_for() as (client, calls):
        response = client.post(
            "/agents/chat",
            json={
                "user_id": "private-user",
                "session_id": "private-session",
                "message": "私密当前输入",
                "history": [{"role": "user", "content": "私密历史"}],
            },
        )
        assert response.status_code == 422
        assert calls == []
        for value in ("private-user", "private-session", "私密当前输入", "私密历史"):
            assert value not in response.text
        assert isinstance(response.json()["detail"], list)


def test_former_4000_character_limit_no_longer_rejects_valid_conversation():
    with client_for() as (client, calls):
        messages = [{"role": "user", "content": "x" * 2000}, {"role": "assistant", "content": "a"}]
        response = client.post(
            "/agents/chat", json=IDENTITY | {"message": "x" * 2000, "history": messages}
        )
        assert response.status_code == 200
        assert calls[0]["messages"][1:-1] == messages


@pytest.mark.parametrize("margin,expected_turns", [(693, 1), (694, 0)])
def test_whole_turn_at_exact_budget_boundary_does_not_mutate_history(margin, expected_turns):
    # 1024 - 256 - 693 = 75；system/current 占 22+19，最新回合占 17+17。
    messages = [
        ChatMessage(role=role, content=content)
        for role, content in [
            ("user", "old"),
            ("assistant", "old"),
            ("user", "a"),
            ("assistant", "b"),
        ]
    ]
    original = [item.model_dump() for item in messages]
    selected = trim_history(
        messages,
        "now",
        system_prompt="system",
        schema=None,
        settings=Settings(
            _env_file=None,
            llm_context_tokens=1024,
            llm_max_tokens=256,
            llm_context_margin_tokens=margin,
        ),
    )
    assert len(selected) == expected_turns * 2 + 1
    assert selected[-1].content == "now"
    assert [item.model_dump() for item in messages] == original
    if expected_turns:
        assert [item.content for item in selected[:-1]] == ["a", "b"]


def test_multibyte_content_schema_and_output_reservations_affect_trimming():
    settings = Settings(
        _env_file=None, llm_context_tokens=1024, llm_max_tokens=256, llm_context_margin_tokens=500
    )
    ascii_history = [ChatMessage(role=role, content="a" * 90) for role in ("user", "assistant")]
    unicode_history = [ChatMessage(role=role, content="脑" * 90) for role in ("user", "assistant")]
    kwargs = {"system_prompt": "system", "schema": None, "settings": settings}
    assert len(trim_history(ascii_history, "now", **kwargs)) == 3
    assert len(trim_history(unicode_history, "now", **kwargs)) == 1
    assert (
        len(trim_history(ascii_history, "now", **(kwargs | {"schema": {"description": "x" * 100}})))
        == 1
    )


def test_invalid_context_configuration_fails_at_startup():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_context_tokens=2048, llm_max_tokens=2048)


def test_identity_metadata_reaches_both_agents_without_entering_model_messages():
    contexts = []

    class Capture(AsyncCallbackHandler):
        async def on_chain_start(
            self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kwargs
        ):
            if parent_run_id is None:
                contexts.append(metadata)

    with client_for() as (client, calls):
        for agent in (client.app.state.intent_agent, client.app.state.chat_agent):
            agent.agent = agent.agent.with_config(callbacks=[Capture()])
        response = client.post(
            "/agents/intent",
            json={"user_id": " A ", "session_id": " S ", "text": "你好", "history": []},
        )
        assert response.status_code == 200
        assert len(contexts) == 2
        assert all(item["user_id"] == "A" and item["session_id"] == "S" for item in contexts)
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("route,field", [("intent", "text"), ("chat", "message")])
async def test_overlapping_users_and_sessions_with_one_failed_request(route, field):
    arrived = 0
    barrier = asyncio.Event()
    calls = []

    async def respond(request):
        nonlocal arrived
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return completion(json.dumps(CLASSIFICATION))
        arrived += 1
        if arrived == 4:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=2)
        marker = body["messages"][-2 if len(body["messages"]) > 2 else -1]["content"]
        if marker == "失败":
            raise httpx.ReadTimeout("private upstream error", request=request)
        return completion(marker)

    service = service_for(respond)
    app = create_app(service)
    async with app.router.lifespan_context(app):
        shared = app.state.chat_agent
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            cases = [
                ("A", "same", "青松"),
                ("B", "same", "海蓝"),
                ("A", "other", "红枫"),
                ("B", "failed", "失败"),
            ]
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/agents/" + route,
                        json={
                            "user_id": u,
                            "session_id": s,
                            field: "项目代号是什么",
                            "history": history(marker),
                        },
                    )
                    for u, s, marker in cases
                )
            )
            for response, (_, _, marker) in zip(responses, cases, strict=True):
                assert response.status_code == (504 if marker == "失败" else 200)
                if marker != "失败":
                    assert response.json()["reason" if route == "intent" else "reply"] == marker
            fresh = await client.post(
                "/agents/chat",
                json={"user_id": "A", "session_id": "same", "message": "你好", "history": []},
            )
            assert fresh.status_code == 200
            assert fresh.json()["reply"] == "你好"  # final request has no previous turn
        assert app.state.chat_agent is shared
    assert service.http_async_client.is_closed
