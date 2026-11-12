"""保护 interfaces/ OpenAPI 契约与当前应用实现同步，并明确草案状态。"""

import json
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.main import create_app
from scripts.docs.openapi_contract import DRAFT_PATH, OFFICIAL_PATH, build_contract
from scripts.docs.render_api_markdown import (
    DEFAULT_OUTPUT,
    load_contract,
    render,
)
from scripts.docs.render_api_markdown import (
    contract_path as markdown_contract_path,
)

ROOT = Path(__file__).parents[1]


def contract_path() -> Path:
    return OFFICIAL_PATH if OFFICIAL_PATH.is_file() else DRAFT_PATH


def read_contract() -> dict:
    return json.loads(contract_path().read_text(encoding="utf-8"))


def registered_operations() -> set[tuple[str, str]]:
    app = create_app()
    return {
        (method.upper(), route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_contract_matches_current_application():
    assert read_contract() == build_contract(official=contract_path() == OFFICIAL_PATH)


def test_generated_review_document_is_current():
    source = markdown_contract_path()
    expected = render(load_contract(source), source.resolve())
    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == expected


def test_contract_covers_exactly_the_registered_operations():
    contract = read_contract()
    documented = {
        (method.upper(), path)
        for path, operations in contract["paths"].items()
        for method in operations
    }
    assert documented == registered_operations()
    assert len(documented) == 10


def test_operation_ids_are_unique():
    operation_ids = [
        operation["operationId"]
        for operations in read_contract()["paths"].values()
        for operation in operations.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))


def test_every_operation_declares_contract_status_and_source():
    for path, operations in read_contract()["paths"].items():
        for method, operation in operations.items():
            label = f"{method.upper()} {path}"
            assert operation["x-contract-status"] in {"confirmed", "pending-review"}, label
            assert operation["x-contract-source"].strip(), label
            assert operation["x-side-effects"].strip(), label
            assert operation["x-idempotency"].strip(), label


def test_draft_and_review_states_are_explicit():
    contract = read_contract()
    if contract_path() == DRAFT_PATH:
        assert contract["info"]["x-contract-status"] == "draft-pending-review"
        assert {
            path
            for path, operations in contract["paths"].items()
            if any(op["x-contract-status"] == "pending-review" for op in operations.values())
        } == {"/ocr/jianbiao"}
    else:
        assert contract["info"]["x-contract-status"] == "confirmed"
        assert contract["info"]["x-contract-version"] == "0.1.0"
        assert contract["info"]["x-review-status"] == "approved"
        assert all(
            operation["x-contract-status"] == "confirmed"
            for methods in contract["paths"].values()
            for operation in methods.values()
        )


def test_agent_error_semantics_are_documented():
    paths = read_contract()["paths"]
    for path in (
        "/agents/log-summary",
        "/agents/intent/business",
        "/agents/intent/archive",
        "/agents/chat",
    ):
        responses = paths[path]["post"]["responses"]
        assert {"200", "422", "502", "503", "504"} <= set(responses)
        assert responses["422"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/RequestError"
        }


def test_post_operations_have_request_examples():
    for path, operations in read_contract()["paths"].items():
        if "post" not in operations:
            continue
        content = operations["post"]["requestBody"]["content"]["application/json"]
        assert content.get("example"), path


def test_document_endpoints_declare_envelope_and_errors():
    paths = read_contract()["paths"]
    for path in (
        "/ocr/journal",
        "/diagnostics",
    ):
        method = "get" if path == "/diagnostics" else "post"
        schema = paths[path][method]["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["$ref"].startswith("#/components/schemas/")
        assert schema["$ref"].endswith("Response")


def test_journal_documents_generation_failure():
    responses = read_contract()["paths"]["/ocr/journal"]["post"]["responses"]
    assert {"200", "400", "422", "502", "503"} <= set(responses)
    assert responses["502"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorDetail"
    }


def test_jianbiao_documents_the_recognition_errors():
    # 简表尚未获批，检查草案；既有正式契约一致性断言继续严格检测新增路由。
    draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    assert draft == build_contract()
    assert draft["paths"]["/ocr/jianbiao"]["post"]["x-contract-status"] == "pending-review"
    responses = draft["paths"]["/ocr/jianbiao"]["post"]["responses"]
    assert {"200", "400", "422", "503"} <= set(responses)
    assert responses["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorDetail"
    }


def test_fixed_output_schemas_are_still_the_published_contracts():
    schemas = read_contract()["components"]["schemas"]
    log_summary = json.loads(
        (ROOT / "interfaces/log_summary/response.schema.json").read_text(encoding="utf-8")
    )
    intent = json.loads(
        (ROOT / "interfaces/intent/response.schema.json").read_text(encoding="utf-8")
    )
    archive = json.loads(
        (ROOT / "interfaces/intent/archive/response.schema.json").read_text(encoding="utf-8")
    )
    assert schemas["LogSummary"] == log_summary
    assert schemas["BusinessIntentResult"] == intent
    assert schemas["ArchiveIntentResult"] == archive
    journal = json.loads(
        (ROOT / "interfaces/journal/response.schema.json").read_text(encoding="utf-8")
    )
    from scripts.docs.openapi_contract import _resolve_schema_refs, _validation_shape

    def component_refs(node):
        if isinstance(node, dict):
            return {
                key: (
                    item.replace("#/$defs/", "#/components/schemas/")
                    if key == "$ref"
                    else component_refs(item)
                )
                for key, item in node.items()
                if key != "$defs"
            }
        if isinstance(node, list):
            return [component_refs(item) for item in node]
        return node

    expected_components = {
        name: component_refs(schema) for name, schema in journal["$defs"].items()
    }
    assert _validation_shape(
        _resolve_schema_refs(schemas["JournalResponse"], schemas)
    ) == _validation_shape(_resolve_schema_refs(component_refs(journal), expected_components))
    response = read_contract()["paths"]["/ocr/journal"]["post"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/JournalResponse"
    }


def test_approved_journal_contract_matches_and_detects_validation_drift():
    from scripts.docs import openapi_contract

    spec = build_contract()
    assert openapi_contract.approved_journal_differences(spec) == []
    spec["components"]["schemas"]["JournalOCRBox"]["properties"]["confidence"]["maximum"] = 0.5
    differences = openapi_contract.approved_journal_differences(spec)
    assert differences and any("JournalOCRBox" in item for item in differences)


def test_approved_journal_contract_detects_request_and_route_drift():
    from scripts.docs import openapi_contract

    spec = build_contract()
    spec["components"]["schemas"]["JournalProcessRequest"]["required"] = []
    assert any(
        "JournalProcessRequest" in item
        for item in openapi_contract.approved_journal_differences(spec)
    )
    del spec["paths"]["/ocr/journal/process"]
    assert any(
        "/ocr/journal/process" in item
        for item in openapi_contract.approved_journal_differences(spec)
    )


@pytest.mark.parametrize("schema", [{"type": "string"}, {}])
def test_approved_contract_detects_raw_response_drift_before_documentation_override(
    monkeypatch, schema
):
    from scripts.docs import openapi_contract

    app = create_app()
    spec = app.openapi()
    spec["paths"]["/ocr/journal/recognize"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] = schema
    monkeypatch.setattr(openapi_contract, "create_app", lambda: app)
    differences = openapi_contract.approved_journal_differences(openapi_contract.build_contract())
    assert differences and any("/ocr/journal/recognize" in item for item in differences)
