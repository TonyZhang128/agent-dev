"""Intent chat routing uses real agents with mocked model HTTP responses."""

import asyncio
import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas import IntentResult
from tests.helpers import request_payload

CLASSIFICATION = {
    "intent": "chat",
    "confidence": 0.95,
    "reason": "没有导航诉求。",
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
def intent_client(classification=None, *, reply="你好！有什么可以帮你？", failure=None):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return completion(json.dumps(classification or CLASSIFICATION, ensure_ascii=False))
        if failure == "connection":
            raise httpx.ConnectError("secret upstream body", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("secret upstream body", request=request)
        if failure == "http-error":
            return httpx.Response(500, json={"error": {"message": "secret upstream body"}})
        if failure == "refusal":
            response = completion("")
            data = response.json()
            data["choices"][0]["message"]["refusal"] = "refused"
            return httpx.Response(200, json=data)
        text = reply(body["messages"][-1]["content"]) if callable(reply) else reply
        return completion(text, "length" if failure == "truncated" else "stop")

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        yield client, calls


@pytest.mark.parametrize("confidence", [0.65, 0.95, 1.0])
@pytest.mark.parametrize(
    "reply", ["你好！有什么可以帮你？", "详细回答。" * 100], ids=["short", "long"]
)
def test_chat_intent_returns_chat_agent_reply(confidence, reply):
    classification = CLASSIFICATION | {"confidence": confidence}
    with intent_client(classification, reply="  " + reply + "\n") as (client, calls):
        response = client.post("/agents/intent", json=request_payload({"text": "你好"}))
        assert response.status_code == 200
        assert response.json() == classification | {"reason": reply}
        assert len(calls) == 2
        assert calls[0]["response_format"]["json_schema"]["strict"] is True
        assert "response_format" not in calls[1]
        assert calls[1]["temperature"] == 0.7
        assert calls[1]["messages"][-1] == {"role": "user", "content": "你好"}
        assert len(calls[1]["messages"]) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "work_list"},
        {"intent": "supervision_log"},
        {"intent": "image_library"},
        {"intent": "business_management"},
        {"intent": "unknown"},
        {"confidence": 0.6499},
        {"needs_clarification": True},
    ],
)
def test_other_and_uncertain_intents_do_not_call_chat(changes):
    classification = CLASSIFICATION | changes
    fallback = (
        classification["intent"] == "unknown"
        or classification["confidence"] < 0.65
        or classification["needs_clarification"]
    )
    expected = classification | (
        {"intent": "unknown", "needs_clarification": True} if fallback else {}
    )
    with intent_client(classification) as (client, calls):
        response = client.post("/agents/intent", json=request_payload({"text": "用户的输入"}))
        assert response.status_code == 200
        assert response.json() == expected
        assert len(calls) == 1


@pytest.mark.parametrize(
    "failure,reply,status",
    [
        ("connection", "unused", 503),
        ("timeout", "unused", 504),
        ("http-error", "unused", 502),
        ("truncated", "不完整回答", 502),
        ("refusal", "unused", 502),
        (None, "  ", 502),
    ],
)
def test_chat_failure_is_not_reported_as_success(failure, reply, status):
    with intent_client(reply=reply, failure=failure) as (client, calls):
        response = client.post("/agents/intent", json=request_payload({"text": "用户的私密输入"}))
        assert response.status_code == status
        assert len(calls) == 2
        assert "secret upstream body" not in response.text
        assert "用户的私密输入" not in response.text


def test_intent_chat_messages_are_isolated_from_other_endpoints_and_requests():
    with intent_client(reply=lambda text: "回答：" + text) as (client, calls):
        client.post("/agents/chat", json=request_payload({"message": "另一位用户的历史"}))
        for text in ("我是甲", "我是乙"):
            response = client.post("/agents/intent", json=request_payload({"text": text}))
            assert response.json()["reason"] == "回答：" + text
        assert len(calls[-1]["messages"]) == 2
        assert "我是甲" not in json.dumps(calls[-1], ensure_ascii=False)
        assert "另一位用户" not in json.dumps(calls[-1], ensure_ascii=False)


@pytest.mark.parametrize("intent", ["work_list", "unknown", "chat"])
def test_reason_length_only_relaxed_for_final_chat_response(intent):
    payload = CLASSIFICATION | {"intent": intent, "reason": "答" * 301}
    if intent == "chat":
        assert IntentResult.model_validate(payload).reason == payload["reason"]
    else:
        with pytest.raises(ValidationError):
            IntentResult.model_validate(payload)
    # Classification reasons stay short even when the final response can contain a long reply.
    with intent_client(payload) as (client, calls):
        response = client.post("/agents/intent", json=request_payload({"text": "你好"}))
        assert response.status_code == 502
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_intent_classification_and_chat_share_total_timeout():
    calls = []

    async def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        await asyncio.sleep(0.12)
        content = json.dumps(CLASSIFICATION) if "response_format" in body else "你好！"
        return completion(content)

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen", llm_timeout_seconds=0.2),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    app = create_app(service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/agents/intent", json=request_payload({"text": "你好"}))
            assert response.status_code == 504
            assert len(calls) == 2
