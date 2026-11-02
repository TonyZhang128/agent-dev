"""业务意图的聊天分流、消息隔离和总超时。"""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app

CHAT = {
    "kind": "chat",
    "confidence": 0.95,
    "reason": "一般交流。",
    "needs_clarification": False,
}


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


def payload(message):
    return {
        "user_id": "test-user",
        "session_id": "test-session",
        "message": message,
        "current_page": "workbench",
        "history": [],
    }


def service_for(respond, **settings):
    return ModelService(
        Settings(_env_file=None, llm_model="test-qwen", **settings),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )


def test_business_chat_messages_are_isolated():
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return completion(json.dumps(CHAT))
        return completion("回答：" + body["messages"][-1]["content"])

    with TestClient(create_app(service_for(respond))) as client:
        first = client.post("/agents/intent/business", json=payload("我是甲"))
        second = client.post("/agents/intent/business", json=payload("我是乙"))

    assert first.status_code == second.status_code == 200
    assert first.json()["message"] == "回答：我是甲"
    assert second.json()["message"] == "回答：我是乙"
    assert "我是甲" not in json.dumps(calls[-1], ensure_ascii=False)
    assert "test-session" not in json.dumps(calls[-1], ensure_ascii=False)


@pytest.mark.asyncio
async def test_classification_and_chat_share_total_timeout():
    calls = []

    async def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        await asyncio.sleep(0.12)
        content = json.dumps(CHAT) if "response_format" in body else "你好！"
        return completion(content)

    service = service_for(respond, llm_timeout_seconds=0.2)
    app = create_app(service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/agents/intent/business", json=payload("你好"))
            assert response.status_code == 504
            assert len(calls) == 2
