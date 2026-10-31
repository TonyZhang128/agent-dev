"""Protect router composition, public contracts and application-local resources."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from tests.helpers import request_payload


def test_full_openapi_matches_contract_snapshot():
    expected = json.loads(
        (Path(__file__).parent / "fixtures/api-openapi.json").read_text(encoding="utf-8")
    )
    app = create_app()
    assert app.openapi() == expected
    # OpenAPI merges duplicate paths; inspect registration as well as documentation.
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    operations = [(method, route.path) for route in routes for method in route.methods]
    assert len(operations) == len(set(operations)) == 5


def test_aggregate_router_can_be_mounted_in_another_application():
    from app.api.router import api_router

    app = FastAPI()
    app.include_router(api_router)
    # Invalid business inputs must be rejected before accessing application resources.
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        for path in (
            "/agents/log-summary",
            "/agents/intent",
            "/agents/chat",
        ):
            assert client.post(path, json={}).status_code == 422
        assert set(client.get("/openapi.json").json()["paths"]) == {
            "/health",
            "/ready",
            "/agents/log-summary",
            "/agents/intent",
            "/agents/chat",
        }


@pytest.mark.parametrize(
    "scenario,expected_status,expected_body",
    [
        ("available", 200, {"status": "ready"}),
        (
            "missing",
            503,
            {"detail": "模型未安装或 LLM_MODEL 与服务端模型名称不匹配"},
        ),
        *[
            (scenario, 503, {"detail": "模型服务不可达，请检查 Ollama/vLLM"})
            for scenario in ("connection", "timeout", "upstream", "json", "metadata")
        ],
    ],
)
def test_system_routes_preserve_readiness_and_liveness(scenario, expected_status, expected_body):
    def respond(request):
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        if scenario == "connection":
            raise httpx.ConnectError("private upstream details", request=request)
        if scenario == "timeout":
            raise httpx.ReadTimeout("private upstream details", request=request)
        if scenario == "upstream":
            return httpx.Response(500, json={"error": "private upstream details"})
        if scenario == "json":
            return httpx.Response(200, text="private invalid JSON")
        if scenario == "metadata":
            return httpx.Response(200, json={"data": None})
        return httpx.Response(
            200, json={"data": [{"id": "test-qwen" if scenario == "available" else "other"}]}
        )

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/ready")
        assert response.status_code == expected_status
        assert response.json() == expected_body
        assert client.get("/health").status_code == 200


def test_routers_reuse_agents_within_each_application_and_isolate_applications():
    def respond(request):
        model = json.loads(request.content)["model"]
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
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": f"reply from {model}"},
                    }
                ],
            },
        )

    def service_for(model):
        return ModelService(
            Settings(_env_file=None, llm_model=model),
            http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
            http_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond), trust_env=False
            ),
        )

    first_service, second_service = service_for("first"), service_for("second")
    first_app, second_app = create_app(first_service), create_app(second_service)
    resource_names = (
        "model_service",
        "log_summary_agent",
        "chat_agent",
        "intent_agent",
    )
    with TestClient(first_app) as first, TestClient(second_app) as second:
        first_resources = [getattr(first_app.state, name) for name in resource_names]
        second_resources = [getattr(second_app.state, name) for name in resource_names]
        assert all(a is not b for a, b in zip(first_resources, second_resources, strict=True))
        for client, model in ((first, "first"), (second, "second"), (first, "first")):
            response = client.post("/agents/chat", json=request_payload({"message": "你好"}))
            assert response.status_code == 200
            assert response.json() == {"reply": f"reply from {model}", "model": model}
        for app, resources in ((first_app, first_resources), (second_app, second_resources)):
            assert all(
                getattr(app.state, name) is resource
                for name, resource in zip(resource_names, resources, strict=True)
            )
            assert app.state.intent_agent.chat_agent is app.state.chat_agent
    for service in (first_service, second_service):
        assert service.http_client.is_closed
        assert service.http_async_client.is_closed
