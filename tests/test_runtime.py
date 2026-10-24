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
from tests.helpers import request_payload


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
async def test_concurrent_fixed_intent_requests_are_isolated():
    cases = {
        "打开工作列表": "work_list",
        "填写监理日志": "supervision_log",
        "打开图片库": "image_library",
        "进入业务管理": "business_management",
        "你好": "chat",
        "谢谢": "chat",
    }

    def respond(request):
        body = json.loads(request.content)
        assert len(body["messages"]) == 2
        if "response_format" not in body:
            return completion({"content": "回答：" + body["messages"][-1]["content"]})
        content = json.loads(body["messages"][-1]["content"])
        assert [item["label"] for item in content["intents"]] == list(dict.fromkeys(cases.values()))
        label = cases[content["text"]]
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

            async def classify(text):
                payload = {"text": text, "intents": []}
                response = await client.post("/api/agents/intent", json=request_payload(payload))
                assert response.status_code == 200
                if cases[text] == "chat":
                    assert response.json()["reason"] == "回答：" + text
                return response.json()["intent"]

            assert await asyncio.gather(*(classify(text) for text in cases)) == list(cases.values())
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
            response = await client.post(
                "/api/agents/chat", json=request_payload({"message": "你好"})
            )
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
        response = client.post(
            "/api/agents/log-summary", json=request_payload({"content": "已完成文档"})
        )
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
        assert (
            client.post(
                "/api/agents/chat", json=request_payload({"message": "执行任务"})
            ).status_code
            == 502
        )


def test_readiness_handles_malformed_metadata():
    with TestClient(
        create_app(models_for(lambda request: httpx.Response(200, json={"data": None})))
    ) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
