import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from tests.helpers import request_payload

VALID = {
    "goal": "处理报销申请",
    "steps": [
        {
            "step": 1,
            "action": "检查发票",
            "responsible_role": "财务",
            "condition": "收到申请",
            "expected_output": "核验结果",
        }
    ],
    "assumptions": [],
    "questions": [],
}


@pytest.fixture
def plan_client():
    def make(content=None, finish="stop", status=200, unavailable=False):

        def respond(request):
            if unavailable:
                raise httpx.ConnectError("offline", request=request)
            if request.url.path.endswith("/models"):
                return httpx.Response(
                    200,
                    json={
                        "object": "list",
                        "data": [
                            {
                                "id": "test-qwen",
                                "object": "model",
                                "created": 0,
                                "owned_by": "local",
                            }
                        ],
                    },
                )
            body = json.loads(request.content)
            assert body["response_format"]["type"] == "json_schema"
            assert not body["response_format"]["json_schema"]["schema"]["additionalProperties"]
            assert body["model"] == "test-qwen"
            assert body["reasoning_effort"] == "none"
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "upstream error"}})
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
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(VALID) if content is None else content,
                            },
                        }
                    ],
                },
            )

        settings = Settings(_env_file=None, llm_model="test-qwen")
        service = ModelService(
            settings,
            http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
            http_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(respond), trust_env=False
            ),
        )
        return TestClient(create_app(service))

    return make


def test_sdk_schema_and_route(plan_client):
    with plan_client() as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200
        response = client.post(
            "/api/business/plan", json=request_payload({"instruction": "审核报销"})
        )
        assert response.status_code == 200
        assert response.json() == VALID


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"instruction": "  "},
        {"instruction": "x" * 2001},
        {"instruction": 42},
        {"instruction": "x", "extra": True},
    ],
    ids=["missing", "blank", "too-long", "wrong-type", "extra-field"],
)
def test_invalid_inputs(plan_client, body):
    with plan_client() as client:
        assert client.post("/api/business/plan", json=request_payload(body)).status_code == 422


@pytest.mark.parametrize(
    "content",
    ("invalid json", "{}", json.dumps(dict(VALID, steps=[dict(VALID["steps"][0], step=2)]))),
    ids=["invalid-json", "missing-fields", "invalid-step"],
)
def test_bad_model_json(plan_client, content):
    with plan_client(content=content) as client:
        assert (
            client.post(
                "/api/business/plan", json=request_payload({"instruction": "审核报销"})
            ).status_code
            == 502
        )


def test_truncated_output(plan_client):
    with plan_client(finish="length") as client:
        assert (
            client.post(
                "/api/business/plan", json=request_payload({"instruction": "审核报销"})
            ).status_code
            == 502
        )


def test_upstream_failure(plan_client):
    with plan_client(status=404) as client:
        assert (
            client.post(
                "/api/business/plan", json=request_payload({"instruction": "审核报销"})
            ).status_code
            == 502
        )


def test_unavailable(plan_client):
    with plan_client(unavailable=True) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert (
            client.post(
                "/api/business/plan", json=request_payload({"instruction": "审核报销"})
            ).status_code
            == 503
        )
