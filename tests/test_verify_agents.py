import json

import httpx
import pytest
from pydantic import ValidationError

from scripts.common import verify_agents


@pytest.mark.parametrize("matched", [True, False], ids=["match", "wrong-page"])
@pytest.mark.parametrize("log_matched", [True, False], ids=["valid-ocr", "wrong-ocr"])
@pytest.mark.parametrize("reject_custom", [True, False], ids=["reject-custom", "accept-custom"])
def test_live_verifier_checks_versioned_datasets(
    tmp_path, monkeypatch, matched, log_matched, reject_custom
):
    sent_requests = []
    data = tmp_path / "data"
    data.mkdir()
    (data / "intent.json").write_text(
        json.dumps(
            {
                "version": "test-v2",
                "endpoint": "/api/agents/intent",
                "samples": [
                    {
                        "id": "test_image_library",
                        "request": {"text": "打开图片库"},
                        "expected": {"intent": "image_library", "needs_clarification": False},
                    }
                ],
                "invalid_requests": [
                    {
                        "id": "test_reject_custom",
                        "request": {"text": "打开图片库", "intents": [{"label": "other"}]},
                        "expected_status": 422,
                    }
                ],
            }
        )
    )
    ocr_request = {
        "user_id": "verification-user",
        "session_id": "verification-session",
        "content": {
            "表格名称": "抽检记录表",
            "计划开始日期": "2024年10月25日",
            "检测数据": {"宽度(mm)": {"实测值": [1000, 1005], "合格率": None}},
        },
    }
    (data / "log_summary.json").write_text(json.dumps(ocr_request["content"]))
    fixtures = tmp_path / "tests/fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "log_summary_cases.json").write_text(
        json.dumps(
            {
                "version": "ocr-test-v1",
                "endpoint": "/api/agents/log-summary",
                "samples": [
                    {
                        "id": "ocr_variant",
                        "request": ocr_request,
                        "expected_response": {
                            "date": None,
                            "completed_items": [],
                            "pending_items": [],
                            "issues": [],
                        },
                        "acceptance": {"summary_contains": ["1000", "1005", "宽度"]},
                    }
                ],
            }
        )
    )
    interface = tmp_path / "interfaces/log_summary"
    interface.mkdir(parents=True)
    (interface / "response.example.json").write_text(
        json.dumps(
            {
                "title": "抽检记录",
                "date": None,
                "summary": "宽度实测1000、1005mm。",
                "completed_items": [],
                "pending_items": [],
                "issues": [],
            }
        )
    )

    def respond(request):
        path = request.url.path
        payload = json.loads(request.content) if request.content else {}
        if request.method == "POST":
            sent_requests.append(payload)
        if path == "/ready":
            result = {"status": "ready"}
        elif path == "/openapi.json":
            result = {
                "info": {"version": "test"},
                "paths": {f"/api/agents/{name}": {} for name in ("log-summary", "intent", "chat")},
            }
        elif path == "/api/agents/log-summary":
            content = payload["content"]
            result = {
                "title": "测试日志",
                "date": content.get("date") if isinstance(content, dict) else None,
                "summary": "完成文档，等待验收，账号尚未开通。",
                "completed_items": ["完成文档"],
                "pending_items": ["等待验收"],
                "issues": ["账号尚未开通"],
            }
            if payload == ocr_request:
                result.update(
                    summary="记录宽度实测值为1000、1005mm。" if log_matched else "数据缺失。",
                    completed_items=[],
                    pending_items=[],
                    issues=[],
                )
        elif path == "/api/agents/intent":
            if payload.get("intents") and reject_custom:
                return httpx.Response(422, json={"detail": [{"type": "too_long"}]})
            result = {
                "intent": "image_library" if matched else "work_list",
                "confidence": 0.95,
                "reason": "识别页面",
                "needs_clarification": False,
            }
        elif path == "/api/agents/chat":
            result = {"reply": "青松", "model": "test"}
        else:
            result = {
                "goal": "检查发票",
                "steps": [
                    {
                        "step": 1,
                        "action": "检查",
                        "responsible_role": "经理",
                        "condition": "收到发票",
                        "expected_output": "检查结果",
                    }
                ],
                "assumptions": [],
                "questions": [],
            }
        return httpx.Response(200, json=result)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(verify_agents.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(verify_agents, "ROOT", tmp_path)
    if matched and log_matched and reject_custom:
        verify_agents.main()
    else:
        with pytest.raises(AssertionError):
            verify_agents.main()
    report = json.loads((tmp_path / "verification/agents-live-result.json").read_text())
    assert [item["request"] for item in report["checks"]] == sent_requests
    assert report["log_summary_dataset_version"] == "ocr-test-v1"
    provided_check = next(item for item in report["checks"] if item["name"] == "provided_ocr_log")
    assert provided_check["request"] == ocr_request
    ocr_check = next(item for item in report["checks"] if item["name"] == "ocr_variant")
    assert ocr_check["request"] == ocr_request
    assert ocr_check["passed"] is log_matched
    if log_matched:
        assert report["intent_dataset_version"] == "test-v2"
        check = next(item for item in report["checks"] if item["name"] == "test_image_library")
        assert check["expected"] == {"intent": "image_library", "needs_clarification": False}
        assert check["passed"] is matched
        if matched:
            rejected = next(
                item for item in report["checks"] if item["name"] == "test_reject_custom"
            )
            assert rejected["expected_http_status"] == 422
            assert rejected["passed"] is reject_custom
    assert report["passed"] is (matched and log_matched and reject_custom)
    if report["passed"]:
        assert [item["name"] for item in report["checks"]] == [
            "structured_log",
            "text_log",
            "provided_ocr_log",
            "ocr_variant",
            "test_image_library",
            "test_reject_custom",
            "chat",
            "chat_with_history",
            "existing_business_plan",
        ]


def test_live_verifier_records_readiness_failure(tmp_path, monkeypatch):
    client = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
    )
    monkeypatch.setattr(verify_agents.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(verify_agents, "ROOT", tmp_path)
    with pytest.raises(httpx.HTTPStatusError):
        verify_agents.main()
    report = json.loads((tmp_path / "verification/agents-live-result.json").read_text())
    assert report["checks"] == []
    assert report["passed"] is False
    assert report["error"].startswith("HTTPStatusError:")
    assert client.is_closed


@pytest.mark.parametrize(
    "status,body,error",
    [
        (200, "not-json", json.JSONDecodeError),
        (200, "{}", ValidationError),
        (503, '{"detail":"unavailable"}', httpx.HTTPStatusError),
    ],
    ids=["not-json", "invalid-schema", "upstream-failure"],
)
def test_live_verifier_records_response_before_validation_failure(
    tmp_path, monkeypatch, status, body, error
):
    def respond(request):
        if request.url.path == "/ready":
            return httpx.Response(200)
        if request.url.path == "/openapi.json":
            return httpx.Response(
                200,
                json={
                    "info": {"version": "test"},
                    "paths": {
                        f"/api/agents/{name}": {} for name in ("log-summary", "intent", "chat")
                    },
                },
            )
        return httpx.Response(status, text=body)

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(verify_agents.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(verify_agents, "ROOT", tmp_path)
    with pytest.raises(error):
        verify_agents.main()
    report = json.loads((tmp_path / "verification/agents-live-result.json").read_text())
    assert report["passed"] is False
    assert len(report["checks"]) == 1
    check = report["checks"][0]
    assert check["name"] == "structured_log"
    assert check["http_status"] == status
    assert check["response"] == (body if body == "not-json" else json.loads(body))
    assert check["request"]["user_id"] == "verification-user"
    assert check["request"]["session_id"] == "verification-session"
    assert check["request"]["content"]["date"] == "2026-10-17"
    assert report["error"].startswith(error.__name__ + ":")
    assert client.is_closed


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, True),
        ({"date": "2024年10月25日"}, False),
        ({"summary": "宽度实测1000mm。"}, False),
        ({"summary": "宽度实测1000、1005mm，全部合格。"}, False),
        ({"completed_items": ["已完成验收"]}, False),
        ({"pending_items": ["安排复检"]}, False),
        ({"issues": ["宽度不合格"]}, False),
        ({"summary": "宽 度实测１０００、１００５ mm。"}, True),
    ],
    ids=[
        "valid",
        "planned-date",
        "missing-value",
        "invented-pass",
        "completion",
        "plan",
        "issue",
        "ocr-spacing",
    ],
)
def test_log_evaluation_rejects_unsupported_facts(changes, expected):
    from app.schemas import LogSummary

    result = LogSummary.model_validate(
        {
            "title": "抽检记录",
            "date": None,
            "summary": "宽度实测1000、1005mm。",
            "completed_items": [],
            "pending_items": [],
            "issues": [],
            **changes,
        }
    )
    sample = {
        "expected_response": {
            "date": None,
            "completed_items": [],
            "pending_items": [],
            "issues": [],
        },
        "acceptance": {
            "summary_contains": ["宽度", "1000", "1005", "mm"],
            "text_excludes": ["全部合格"],
        },
    }
    assert verify_agents.log_matches_expectations(result, sample) is expected
