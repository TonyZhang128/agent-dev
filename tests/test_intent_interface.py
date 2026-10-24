"""Keep published intent response contracts and examples aligned with the API."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.intent import DEFAULT_INTENTS
from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas import IntentClassification, IntentRequest, IntentResult
from tests.helpers import request_payload

INTERFACE = Path(__file__).parents[1] / "interfaces/intent"


def read_json(name):
    return json.loads((INTERFACE / name).read_text(encoding="utf-8"))


def test_published_intent_response_matches_pydantic_and_openapi():
    schema = read_json("response.schema.json")
    assert schema == IntentResult.model_json_schema()
    assert schema == create_app().openapi()["components"]["schemas"]["IntentResult"]
    assert set(schema["properties"]) == {
        "intent",
        "confidence",
        "reason",
        "needs_clarification",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["intent"]["enum"] == [
        "work_list",
        "supervision_log",
        "image_library",
        "business_management",
        "chat",
        "unknown",
    ]
    request_schema = create_app().openapi()["components"]["schemas"]["IntentRequest"]
    assert request_schema["properties"]["intents"]["maxItems"] == 0


def test_published_default_response_and_internal_classifier_schemas():
    schema = read_json("response.default.schema.json")
    assert schema == IntentResult.model_json_schema()
    app = create_app(ModelService(Settings(_env_file=None)))
    with TestClient(app):
        for payload in ({"text": "打开工作列表"}, {"text": "打开工作列表", "intents": []}):
            classifier_schema = app.state.intent_agent.response_schema(
                IntentRequest(**request_payload(payload))
            )
            assert classifier_schema == IntentClassification.model_json_schema()
            assert classifier_schema["properties"]["reason"]["maxLength"] == 300
            assert classifier_schema["properties"]["intent"] == schema["properties"]["intent"]
    assert "maxLength" not in schema["properties"]["reason"]
    assert schema["properties"]["intent"]["enum"] == [
        "work_list",
        "supervision_log",
        "image_library",
        "business_management",
        "chat",
        "unknown",
    ]


def test_intent_main_examples_contain_only_the_five_business_classes():
    examples = read_json("response.examples.json")
    default_labels = {item.label for item in DEFAULT_INTENTS}
    assert len(examples) == 5
    assert {case["response"]["intent"] for case in examples} == default_labels
    for case in examples:
        request = IntentRequest.model_validate(case["request"])
        result = IntentResult.model_validate(case["response"])
        assert result.model_dump() == case["response"]
        assert not request.intents
        assert result.confidence >= 0.65
        assert not result.needs_clarification


def test_unknown_fallback_examples_are_published_separately():
    examples = read_json("response.fallback.examples.json")
    assert len(examples) >= 2
    for case in examples:
        assert not IntentRequest.model_validate(case["request"]).intents
        result = IntentResult.model_validate(case["response"])
        assert result.intent == "unknown"
        assert result.needs_clarification


@pytest.mark.parametrize("label", ["query", "order_status", "cancel_order", "库存查询"])
def test_response_contract_rejects_retired_and_custom_labels(label):
    with pytest.raises(ValidationError):
        IntentResult.model_validate(read_json("response.example.json") | {"intent": label})


def test_intent_dataset_contains_fixed_classes_and_rejected_custom_requests():
    dataset = json.loads((INTERFACE.parents[1] / "data/intent.json").read_text(encoding="utf-8"))
    assert dataset["version"] == "4.0.0"
    assert len(dataset["samples"]) == 24
    allowed = {item.label for item in DEFAULT_INTENTS} | {"unknown"}
    for case in dataset["samples"]:
        assert not IntentRequest.model_validate(case["request"]).intents
        assert case["expected"]["intent"] in allowed
    assert len(dataset["invalid_requests"]) == 4
    for case in dataset["invalid_requests"]:
        assert case["expected_status"] == 422
        with pytest.raises(ValidationError):
            IntentRequest.model_validate(case["request"])


def test_primary_intent_example_matches_the_documented_navigation_case():
    example = read_json("response.example.json")
    assert IntentResult.model_validate(example).intent == "image_library"
    cases = read_json("response.examples.json")
    assert any(
        case["request"] == request_payload({"text": "你好，帮我打开图片库"})
        and case["response"] == example
        for case in cases
    )
