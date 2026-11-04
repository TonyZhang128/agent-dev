"""归档端意图识别复用同一流程，只由 IntentProfile 提供标签和提示词。"""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import get_args

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.profiles import IntentProfile
from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.prompts import load_prompt
from app.schemas.agents import (
    ArchiveIntentResult,
    BusinessIntentResult,
    IntentDefinition,
)
from tests.helpers import request_payload

ARCHIVE_CLASSIFICATION = {
    "intent": "A",
    "confidence": 0.95,
    "reason": "匹配 A 类归档业务。",
    "needs_clarification": False,
}
INTERFACE = Path(__file__).parents[1] / "interfaces/intent/archive"


def read_json(name):
    return json.loads((INTERFACE / name).read_text(encoding="utf-8"))


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


@contextmanager
def archive_client(classification=None):
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        result = classification or ARCHIVE_CLASSIFICATION
        return completion(json.dumps(result, ensure_ascii=False))

    service = ModelService(
        Settings(_env_file=None, llm_model="test-qwen"),
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    with TestClient(create_app(service)) as client:
        yield client, calls


def test_archive_intent_uses_its_own_labels_prompt_and_schema():
    with archive_client() as (client, calls):
        response = client.post(
            "/agents/intent/archive", json=request_payload({"text": "把这个文件归档"})
        )

    assert response.status_code == 200
    assert response.json() == ARCHIVE_CLASSIFICATION
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]
    assert schema["name"] == "intent_archive"
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["intent"]["enum"] == [
        "A",
        "B",
        "C",
        "D",
        "unknown",
    ]
    assert "文件归档系统" in calls[0]["messages"][0]["content"]
    content = json.loads(calls[0]["messages"][-1]["content"])
    assert content["text"] == "把这个文件归档"
    assert [item["label"] for item in content["intents"]] == ["A", "B", "C", "D"]


def test_archive_rejects_caller_supplied_candidates_before_inference():
    with archive_client() as (client, calls):
        response = client.post(
            "/agents/intent/archive",
            json=request_payload(
                {
                    "text": "归档文件",
                    "intents": [{"label": "A", "description": "调用方指定的分类"}],
                }
            ),
        )

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("score,intent", [(0.0, "unknown"), (0.6499, "unknown"), (0.65, "A")])
def test_archive_confidence_boundary(score, intent):
    with archive_client(ARCHIVE_CLASSIFICATION | {"confidence": score}) as (client, calls):
        response = client.post("/agents/intent/archive", json=request_payload({"text": "归档文件"}))

    assert response.status_code == 200
    assert response.json()["confidence"] == score
    assert response.json()["intent"] == intent
    assert response.json()["needs_clarification"] is (score < 0.65)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"intent": "unknown"},
        {"needs_clarification": True},
        {"confidence": 0.4},
    ],
    ids=["unknown", "needs-clarification", "low-confidence"],
)
def test_archive_uncertainty_falls_back_without_chat(changes):
    with archive_client(ARCHIVE_CLASSIFICATION | changes) as (client, calls):
        response = client.post("/agents/intent/archive", json=request_payload({"text": "你好"}))

    assert response.status_code == 200
    assert response.json()["intent"] == "unknown"
    assert response.json()["needs_clarification"] is True
    assert len(calls) == 1


@pytest.mark.parametrize("label", ["work_list", "chat", "E", "a"])
def test_archive_rejects_labels_outside_its_contract(label):
    with archive_client(ARCHIVE_CLASSIFICATION | {"intent": label}) as (client, calls):
        response = client.post("/agents/intent/archive", json=request_payload({"text": "归档文件"}))

    assert response.status_code == 502
    assert len(calls) == 1


def test_archive_profile_has_no_chat_agent_and_shares_the_application_lifecycle():
    app = create_app(
        ModelService(
            Settings(_env_file=None, llm_model="test-qwen"),
            http_client=httpx.Client(transport=httpx.MockTransport(lambda _: None)),
            http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)),
        )
    )
    with TestClient(app):
        assert app.state.archive_intent_agent is not app.state.business_intent_agent
        assert app.state.archive_intent_agent.chat_agent is None
        assert app.state.business_intent_agent.chat_agent is app.state.chat_agent
        assert app.state.business_intent_agent.clarify_agent is app.state.clarify_agent


def test_published_archive_schema_matches_pydantic_and_openapi():
    schema = read_json("response.schema.json")
    assert schema == ArchiveIntentResult.model_json_schema()
    openapi = create_app().openapi()
    assert schema == openapi["components"]["schemas"]["ArchiveIntentResult"]
    assert schema["properties"]["intent"]["enum"] == ["A", "B", "C", "D", "unknown"]
    assert schema["properties"]["reason"]["maxLength"] == 300


def test_published_archive_example_and_business_schema_are_separate():
    example = read_json("response.example.json")
    assert ArchiveIntentResult.model_validate(example).model_dump() == example
    assert example["intent"] == "A"
    assert BusinessIntentResult.model_validate(
        {
            "status": "resolved",
            "page": "supervision_diary",
            "action": "fill_supervision_log",
            "confidence": 0.9,
            "message": None,
            "options": None,
            "catalog_version": "test",
        }
    )
    with pytest.raises(ValidationError):
        BusinessIntentResult.model_validate(example)


def test_profile_rejects_configuration_that_drifts_from_its_response_model():
    with pytest.raises(ValueError, match="missing labels"):
        IntentProfile(
            name="drifted",
            agent_name="intent_drifted",
            prompt_name="intent/archive",
            intents=(IntentDefinition(label="E", description="未在响应模型中声明"),),
            classification_type=ArchiveIntentResult,
            response_type=ArchiveIntentResult,
        )
    with pytest.raises(ValueError, match="extra labels"):
        IntentProfile(
            name="subset",
            agent_name="intent_subset",
            prompt_name="intent/archive",
            intents=(IntentDefinition(label="A", description="只声明一个分类"),),
            classification_type=ArchiveIntentResult,
            response_type=ArchiveIntentResult,
        )


def test_prompt_loader_accepts_profile_subdirectories_and_blocks_traversal():
    assert "文件归档系统" in load_prompt("intent/archive")
    assert "业务系统" in load_prompt("intent/business")
    with pytest.raises(ValueError):
        load_prompt("../intent/business")


def test_archive_labels_are_derived_from_the_profile_enum():
    assert set(get_args(ArchiveIntentResult.model_fields["intent"].annotation)) == {
        "A",
        "B",
        "C",
        "D",
        "unknown",
    }
