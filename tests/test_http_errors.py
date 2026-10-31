"""Pin public error semantics while changing HTTP handler organization."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from tests.helpers import request_payload


@pytest.mark.parametrize(
    "failure,status,detail",
    [
        ("timeout", 504, "模型推理超时"),
        ("connection", 503, "模型服务不可达，请检查 Ollama/vLLM"),
        ("upstream", 502, "模型服务返回错误，请检查模型名称和服务日志"),
        ("empty", 502, "模型未返回完整且符合约定的结果"),
        ("context", 422, "请求超过输入上限，或当前输入与系统提示词超出上下文预算"),
    ],
)
def test_model_error_bodies_remain_safe_and_exact(failure, status, detail, caplog):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret upstream body", request=request)
        if failure == "connection":
            raise httpx.ConnectError("secret upstream body", request=request)
        if failure == "upstream":
            return httpx.Response(429, json={"error": {"message": "secret upstream body"}})
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
                        "message": {"role": "assistant", "content": ""},
                    }
                ],
            },
        )

    settings = Settings(
        _env_file=None,
        llm_model="test-qwen",
        conversation_max_input_characters=1 if failure == "context" else 1000000,
    )
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        response = client.post("/agents/chat", json=request_payload({"message": "用户的私密输入"}))
    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert "secret upstream body" not in caplog.text
    assert "用户的私密输入" not in caplog.text
    if failure == "upstream":
        assert any(
            record.name == "app.main" and record.getMessage() == "Model server returned HTTP 429"
            for record in caplog.records
        )


def test_validation_error_keeps_only_public_fields():
    service = ModelService(Settings(_env_file=None))
    with TestClient(create_app(service)) as client:
        response = client.post(
            "/agents/chat",
            json={
                "user_id": "private-user",
                "session_id": "private-session",
                "message": "private-message",
                "history": [{"role": "system", "content": "private-history"}],
            },
        )
    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", "history", 0, "role"],
                "msg": "Input should be 'user' or 'assistant'",
            }
        ]
    }
