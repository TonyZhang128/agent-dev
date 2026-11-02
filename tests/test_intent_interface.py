"""已发布的业务意图响应契约、示例和版本化数据集保持同步。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas.agents import BusinessIntentRequest, BusinessIntentResult
from app.schemas.intent_catalog_generated import ACTION_CODES, CATALOG_VERSION, PAGE_CODES
from scripts.docs.openapi_contract import build_contract

INTERFACE = Path(__file__).parents[1] / "interfaces/intent"


def read_json(name):
    return json.loads((INTERFACE / name).read_text(encoding="utf-8"))


def test_published_business_response_matches_pydantic_and_openapi():
    schema = read_json("response.schema.json")
    assert schema == BusinessIntentResult.model_json_schema()
    assert schema == build_contract()["components"]["schemas"]["BusinessIntentResult"]
    assert set(schema["properties"]) == {
        "status",
        "page",
        "action",
        "confidence",
        "message",
        "options",
        "catalog_version",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["status"]["enum"] == [
        "resolved",
        "clarify",
        "chat",
        "unknown",
    ]
    assert schema["$defs"]["BusinessIntentOption"]["properties"]["page"]["enum"] == list(PAGE_CODES)
    assert schema["$defs"]["BusinessIntentOption"]["properties"]["action"]["enum"] == list(
        ACTION_CODES
    )


def test_compatibility_schema_is_identical():
    assert read_json("response.default.schema.json") == read_json("response.schema.json")


def test_published_examples_validate_as_requests_and_responses():
    examples = read_json("response.examples.json")
    assert len(examples) >= 4
    statuses = set()
    for case in examples:
        request = BusinessIntentRequest.model_validate(case["request"])
        result = BusinessIntentResult.model_validate(case["response"])
        assert result.model_dump() == case["response"]
        assert request.current_page in PAGE_CODES
        assert result.catalog_version == CATALOG_VERSION
        statuses.add(result.status)
        if result.status == "clarify":
            assert result.action is None
            assert result.options
            assert all(option.page == result.page for option in result.options)
        if result.status == "resolved":
            assert result.action is not None
    assert statuses == {"resolved", "clarify", "chat", "unknown"}


def test_unknown_and_clarify_examples_are_published_separately():
    examples = read_json("response.fallback.examples.json")
    assert len(examples) >= 2
    assert {case["response"]["status"] for case in examples} == {"unknown", "clarify"}


def test_response_contract_rejects_legacy_business_shape():
    with pytest.raises(ValidationError):
        BusinessIntentResult.model_validate(
            {
                "intent": "work_list",
                "confidence": 0.9,
                "reason": "打开工作列表",
                "needs_clarification": False,
            }
        )


def test_versioned_intent_dataset_shape():
    dataset = json.loads((INTERFACE.parents[1] / "data/intent.json").read_text(encoding="utf-8"))
    assert dataset["version"] == "5.0.0"
    assert dataset["endpoint"] == "/agents/intent/business"
    assert dataset["samples"]
    for case in dataset["samples"]:
        request = BusinessIntentRequest.model_validate(case["request"])
        expected = case["expected"]
        assert expected["status"] in {"resolved", "clarify", "chat", "unknown"}
        assert request.current_page in PAGE_CODES
        if expected["status"] == "resolved":
            assert expected["page"] in PAGE_CODES
            assert expected["action"] in ACTION_CODES
        elif expected["status"] == "clarify":
            assert expected["page"] in PAGE_CODES
            assert expected["action"] is None
        else:
            assert expected["page"] is None
            assert expected["action"] is None
    assert dataset["invalid_requests"]
    for case in dataset["invalid_requests"]:
        assert case["expected_status"] == 422
        with pytest.raises(ValidationError):
            BusinessIntentRequest.model_validate(case["request"])


def test_chat_agent_is_shared_with_business_intent():
    app = create_app(
        ModelService(
            Settings(_env_file=None, llm_model="test-qwen"),
        )
    )
    with TestClient(app):
        assert app.state.business_intent_agent.chat_agent is app.state.chat_agent
        assert app.state.business_intent_agent.clarify_agent is app.state.clarify_agent
