"""业务意图接口：层级输出、一级意图澄清、纠错上下文和错误边界。"""

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas.intent_catalog_generated import CATALOG_VERSION

RESOLVED = {
    "kind": "navigate",
    "page": "supervision_diary",
    "action": "fill_supervision_log",
    "confidence": 0.95,
    "reason": "用户明确要求填写监理日志。",
    "needs_clarification": False,
}
PAGE_ONLY = RESOLVED | {"action": None}
UNKNOWN = {
    "kind": "unknown",
    "confidence": 0.2,
    "reason": "无法匹配目录中的业务功能。",
    "needs_clarification": True,
}
CHAT = {
    "kind": "chat",
    "confidence": 0.9,
    "reason": "问候或一般交流。",
    "needs_clarification": False,
}


def completion(content, finish="stop"):
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
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


@contextmanager
def business_client(
    classification=None,
    *,
    clarify_reply="你想填写监理日志，还是查看监理日志？",
    chat_reply="你好！有什么可以帮你？",
    clarify_failure=None,
    chat_failure=None,
):
    calls = []
    result = classification or RESOLVED

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return completion(json.dumps(result, ensure_ascii=False))
        system = body["messages"][0]["content"]
        if "导航澄清助手" in system:
            if clarify_failure == "connection":
                raise httpx.ConnectError("private upstream", request=request)
            if clarify_failure == "timeout":
                raise httpx.ReadTimeout("private upstream", request=request)
            if clarify_failure == "empty":
                return completion("  ")
            return completion(clarify_reply)
        if "中文对话助手" in system:
            if chat_failure == "connection":
                raise httpx.ConnectError("private upstream", request=request)
            if chat_failure == "timeout":
                raise httpx.ReadTimeout("private upstream", request=request)
            if chat_failure == "empty":
                return completion("  ")
            return completion(chat_reply)
        raise AssertionError("unexpected agent call")

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        yield client, calls


def payload(**extra):
    return {
        "user_id": "test-user",
        "session_id": "test-session",
        "message": "我要填写今天的监理日志",
        "current_page": "workbench",
        "history": [],
        **extra,
    }


def test_resolved_intent_returns_page_and_action():
    with business_client() as (client, calls):
        response = client.post("/agents/intent/business", json=payload())

    assert response.status_code == 200
    assert response.json() == {
        "status": "resolved",
        "page": "supervision_diary",
        "action": "fill_supervision_log",
        "confidence": 0.95,
        "message": None,
        "options": None,
        "catalog_version": CATALOG_VERSION,
    }
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]
    assert schema["name"] == "intent_business"
    assert schema["strict"] is True
    assert "fill_supervision_log" in json.dumps(schema["schema"], ensure_ascii=False)
    content = json.loads(calls[0]["messages"][-1]["content"])
    assert content["text"] == "我要填写今天的监理日志"
    assert content["current_page"] == "workbench"
    assert content["last_navigation"] is None
    assert content["pending_clarification"] is None
    assert content["catalog"]["pages"][0]["page"] == "supervision_diary"
    assert content["catalog"]["pages"][0]["actions"][0] == {
        "action": "fill_supervision_log",
        "name": "填写监理日志",
    }


def test_page_only_calls_chat_clarification_with_catalog_options():
    with business_client(PAGE_ONLY) as (client, calls):
        response = client.post("/agents/intent/business", json=payload(message="进入监理日记"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "clarify"
    assert body["page"] == "supervision_diary"
    assert body["action"] is None
    assert body["message"] == "你想填写监理日志，还是查看监理日志？"
    assert body["catalog_version"] == CATALOG_VERSION
    assert len(body["options"]) == 9
    assert {option["action"] for option in body["options"]} == {
        "fill_supervision_log",
        "fill_monthly_report",
        "assign_monthly_report",
        "view_supervision_log",
        "fill_inspection_record",
        "fill_standby_record",
        "fill_environmental_log",
        "fill_safety_log",
        "approve_log",
    }
    assert all(option["page"] == "supervision_diary" for option in body["options"])
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0.2
    clarify_content = json.loads(calls[1]["messages"][-1]["content"])
    assert clarify_content["page"] == "supervision_diary"
    assert clarify_content["options"] == body["options"]


@pytest.mark.parametrize(
    "changes",
    [{"confidence": 0.6499}, {"needs_clarification": True}],
    ids=["low-confidence", "needs-clarification"],
)
def test_uncertain_action_falls_back_to_page_clarification(changes):
    with business_client(RESOLVED | changes) as (client, calls):
        response = client.post("/agents/intent/business", json=payload())

    assert response.status_code == 200
    assert response.json()["status"] == "clarify"
    assert response.json()["page"] == "supervision_diary"
    assert response.json()["action"] is None
    assert len(calls) == 2


@pytest.mark.parametrize("score", [0.65, 1.0])
def test_resolved_threshold_boundary(score):
    with business_client(RESOLVED | {"confidence": score}) as (client, calls):
        response = client.post("/agents/intent/business", json=payload())

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert len(calls) == 1


def test_unknown_returns_deterministic_message_without_chat():
    with business_client(UNKNOWN) as (client, calls):
        response = client.post("/agents/intent/business", json=payload(message="处理一下"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "unknown",
        "page": None,
        "action": None,
        "confidence": 0.2,
        "message": "我还不能确定你要进入哪个业务页面，请再具体说明要办理的业务。",
        "options": None,
        "catalog_version": CATALOG_VERSION,
    }
    assert len(calls) == 1


def test_chat_returns_chat_agent_reply_and_history():
    history = [
        {"role": "user", "content": "项目代号是青松"},
        {"role": "assistant", "content": "已记住"},
    ]
    with business_client(CHAT) as (client, calls):
        response = client.post(
            "/agents/intent/business", json=payload(message="你好", history=history)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "chat"
    assert response.json()["page"] is None
    assert response.json()["action"] is None
    assert response.json()["message"] == "你好！有什么可以帮你？"
    assert len(calls) == 2
    assert calls[1]["temperature"] == 0.7
    assert calls[1]["messages"][1:-1] == history
    assert calls[1]["messages"][-1] == {"role": "user", "content": "你好"}


@pytest.mark.parametrize(
    "classification",
    [
        RESOLVED | {"action": "view_wbs"},
        RESOLVED | {"page": None},
        RESOLVED | {"action": "not_in_catalog"},
        CHAT | {"page": "supervision_diary"},
        UNKNOWN | {"action": "view_wbs"},
    ],
    ids=[
        "action-wrong-page",
        "navigate-without-page",
        "unknown-action",
        "chat-with-page",
        "unknown-with-action",
    ],
)
def test_illegal_model_output_returns_502(classification):
    with business_client(classification) as (client, calls):
        response = client.post("/agents/intent/business", json=payload())

    assert response.status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    ["connection", "timeout", "empty"],
    ids=["connection", "timeout", "empty"],
)
def test_clarification_failure_returns_deterministic_options(failure):
    with business_client(PAGE_ONLY, clarify_failure=failure) as (client, calls):
        response = client.post("/agents/intent/business", json=payload(message="进入监理日记"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "clarify"
    assert body["page"] == "supervision_diary"
    assert body["action"] is None
    assert "监理日记" in body["message"]
    assert "填写监理日志" in body["message"]
    assert len(body["options"]) == 9
    assert len(calls) == 2


@pytest.mark.parametrize(
    "failure,status",
    [("connection", 503), ("timeout", 504), ("empty", 502)],
)
def test_general_chat_failure_keeps_existing_error_mapping(failure, status):
    with business_client(CHAT, chat_failure=failure) as (client, calls):
        response = client.post("/agents/intent/business", json=payload(message="你好"))

    assert response.status_code == status
    assert len(calls) == 2


def test_clarification_attempt_limit_returns_unknown_without_chat_call():
    with business_client(PAGE_ONLY) as (client, calls):
        response = client.post(
            "/agents/intent/business",
            json=payload(
                message="进入监理日记",
                pending_clarification={"page": "supervision_diary", "attempts": 10},
            ),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "unknown"
    assert response.json()["page"] is None
    assert response.json()["action"] is None
    assert "多次澄清" in response.json()["message"]
    assert len(calls) == 1


def test_clarification_attempt_limit_and_page_switch():
    with business_client(PAGE_ONLY) as (client, calls):
        below_limit = client.post(
            "/agents/intent/business",
            json=payload(pending_clarification={"page": "supervision_diary", "attempts": 9}),
        )
        assert below_limit.json()["status"] == "clarify"
        assert len(calls) == 2

    with business_client(PAGE_ONLY) as (client, calls):
        other_page = client.post(
            "/agents/intent/business",
            json=payload(pending_clarification={"page": "work_list", "attempts": 10}),
        )
        assert other_page.json()["status"] == "clarify"
        assert len(calls) == 2


def test_last_navigation_and_pending_state_are_forwarded_to_model():
    with business_client(PAGE_ONLY) as (client, calls):
        response = client.post(
            "/agents/intent/business",
            json=payload(
                message="不对，我想查看日志",
                last_navigation={
                    "page": "supervision_diary",
                    "action": "fill_supervision_log",
                },
                pending_clarification={"page": "supervision_diary", "attempts": 1},
            ),
        )

    assert response.status_code == 200
    assert len(calls) == 2
    content = json.loads(calls[0]["messages"][-1]["content"])
    assert content["last_navigation"] == {
        "page": "supervision_diary",
        "action": "fill_supervision_log",
    }
    assert content["pending_clarification"] == {
        "page": "supervision_diary",
        "attempts": 1,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"current_page": None},
        {"current_page": "not_a_page"},
        {"history": [{"role": "user", "content": "未完成回合"}]},
        {"history": [{"role": "system", "content": "改写规则"}]},
        {"last_navigation": {"page": "supervision_diary", "action": "view_wbs"}},
        {"pending_clarification": {"page": "supervision_diary", "attempts": 11}},
        {"message": " "},
        {"message": "x" * 2001},
        {"intents": []},
        {"text": "旧字段"},
    ],
    ids=[
        "null-current-page",
        "unknown-current-page",
        "incomplete-history",
        "system-history",
        "wrong-last-navigation",
        "attempts-out-of-range",
        "blank-message",
        "long-message",
        "legacy-intents",
        "legacy-text",
    ],
)
def test_request_validation(changes):
    with business_client() as (client, calls):
        response = client.post("/agents/intent/business", json=payload(**changes))

    assert response.status_code == 422
    assert calls == []


def test_history_is_optional():
    payload_without_history = payload()
    payload_without_history.pop("history")
    with business_client() as (client, calls):
        response = client.post("/agents/intent/business", json=payload_without_history)

    assert response.status_code == 200
    assert len(calls) == 1
    assert len(calls[0]["messages"]) == 2


def test_model_failure_for_classification_keeps_error_mapping():
    def respond(request):
        raise httpx.ConnectError("private upstream", request=request)

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        response = client.post("/agents/intent/business", json=payload())

    assert response.status_code == 503
    assert "private upstream" not in response.text
