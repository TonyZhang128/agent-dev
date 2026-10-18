import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from app.agents.runtime import build_agent, invoke_agent
from app.config import Settings
from app.llm import ModelService
from app.main import create_app


def completion(message, finish="stop"):
    return httpx.Response(
        200,
        json={
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-qwen",
            "choices": [
                {"index": 0, "finish_reason": finish, "message": {"role": "assistant", **message}}
            ],
        },
    )


def models_for(respond, **settings):
    return ModelService(
        Settings(_env_file=None, llm_model="test-qwen", **settings),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )


@pytest.mark.asyncio
async def test_concurrent_custom_intents_are_isolated():

    def respond(request):
        body = json.loads(request.content)
        label = body["response_format"]["json_schema"]["schema"]["properties"]["intent"]["enum"][0]
        return completion(
            {
                "content": json.dumps(
                    {
                        "intent": label,
                        "confidence": 0.95,
                        "reason": "符合候选描述",
                        "needs_clarification": False,
                    }
                )
            }
        )

    service = models_for(respond)
    app = create_app(service)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def classify(label):
                response = await client.post(
                    "/api/agents/intent",
                    json={
                        "text": "查询记录",
                        "intents": [{"label": label, "description": "查询指定记录"}],
                    },
                )
                assert response.status_code == 200
                return response.json()["intent"]

            assert await asyncio.gather(classify("lookup_a"), classify("lookup_b")) == [
                "lookup_a",
                "lookup_b",
            ]
    assert service.http_client.is_closed
    assert service.http_async_client.is_closed


@pytest.mark.asyncio
async def test_total_timeout_bounds_the_agent():

    async def respond(request):
        await asyncio.sleep(0.2)
        return completion({"content": "late"})

    app = create_app(models_for(respond, llm_timeout_seconds=0.02))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/agents/chat", json={"message": "你好"})
            assert response.status_code == 504


@pytest.mark.asyncio
async def test_langchain_tool_loop_can_be_extended():
    calls = []

    @tool
    def add(a: int, b: int) -> int:
        """Add two integers and return their sum."""
        return a + b

    class Total(BaseModel):
        value: int

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return completion(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_add",
                            "type": "function",
                            "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'},
                        }
                    ],
                },
                "tool_calls",
            )
        assert any(
            message.get("role") == "tool" and message["content"] == "5"
            for message in body["messages"]
        )
        return completion({"content": '{"value": 5}'})

    service = models_for(respond)
    try:
        agent = build_agent(
            service,
            name="calculate",
            prompt="Use add to calculate the sum.",
            schema=Total.model_json_schema(),
            tools=(add,),
        )
        result = await invoke_agent(agent, service, [HumanMessage(content="2 + 3")])
        assert Total.model_validate(result["structured_response"]).value == 5
        assert len(calls) == 2
    finally:
        await service.close()


@pytest.mark.parametrize(
    "message,finish",
    (({"content": "{}", "refusal": "refused"}, "stop"), ({"content": "{}"}, "content_filter")),
    ids=["refusal", "content-filter"],
)
def test_refusal_and_content_filter_return_502(message, finish):
    service = models_for(lambda request, m=message, f=finish: completion(m, f))
    with TestClient(create_app(service)) as client:
        response = client.post("/api/agents/log-summary", json={"content": "已完成文档"})
        assert response.status_code == 502


def test_unregistered_tool_calls_return_502():
    response = {
        "content": None,
        "tool_calls": [
            {"id": "x", "type": "function", "function": {"name": "unknown_tool", "arguments": "{}"}}
        ],
    }
    with TestClient(
        create_app(models_for(lambda request: completion(response, "tool_calls")))
    ) as client:
        assert client.post("/api/agents/chat", json={"message": "执行任务"}).status_code == 502


def test_readiness_handles_malformed_metadata():
    with TestClient(
        create_app(models_for(lambda request: httpx.Response(200, json={"data": None})))
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
