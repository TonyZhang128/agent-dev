import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app
from tests.helpers import request_payload

LOG = {
    "title": "开发日志",
    "date": None,
    "summary": "完成接口开发，等待测试。",
    "completed_items": ["接口开发"],
    "pending_items": ["测试"],
    "issues": [],
}
INTENT = {
    "intent": "work_list",
    "confidence": 0.95,
    "reason": "用户明确要求查看工作列表",
    "needs_clarification": False,
}


@pytest.fixture
def calls():
    return []


@pytest.fixture
def agent_client(calls):
    def make(result, *, finish="stop", status=200, error=None):

        def respond(request):
            if error == "connection":
                raise httpx.ConnectError("offline", request=request)
            if error == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            body = json.loads(request.content)
            calls.append(body)
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "upstream error"}})
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            if (
                isinstance(result, dict)
                and result.get("intent") == "chat"
                and "response_format" not in body
            ):
                content = "你好！有什么可以帮你？"
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
                            "message": {"role": "assistant", "content": content},
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


@pytest.mark.parametrize(
    "content",
    ("已完成：接口开发\n待办：测试", {"completed": ["接口开发"], "pending": ["测试"]}),
    ids=["text", "json-object"],
)
def test_log_accepts_structured_text_and_json(calls, agent_client, content):
    with agent_client(LOG) as client:
        response = client.post(
            "/api/agents/log-summary", json=request_payload({"content": content})
        )
        assert response.status_code == 200
        assert response.json() == LOG
        assert calls[0]["response_format"]["json_schema"]["name"] == "log_summary"
        sent = calls[0]["messages"][-1]["content"]
        assert (json.loads(sent) if isinstance(content, dict) else sent) == content


OCR_SAMPLES = [
    sample
    for sample in json.loads(
        (Path(__file__).parent / "fixtures/log_summary_cases.json").read_text(encoding="utf-8")
    )["samples"]
    if sample["id"].startswith("log_ocr_")
]


@pytest.mark.parametrize("sample", OCR_SAMPLES, ids=lambda sample: sample["id"])
def test_log_preserves_variable_ocr_objects_and_response_contract(calls, agent_client, sample):
    with agent_client(sample["expected_response"]) as client:
        response = client.post("/api/agents/log-summary", json=request_payload(sample["request"]))
        assert response.status_code == 200
        assert response.json() == sample["expected_response"]
        assert json.loads(calls[0]["messages"][-1]["content"]) == sample["request"]["content"]
        schema = calls[0]["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False


def test_supplied_log_input_uses_the_published_output_interface(calls, agent_client):
    root = Path(__file__).parents[1]
    content = json.loads((root / "data/log_summary.json").read_text(encoding="utf-8"))
    example = json.loads(
        (root / "interfaces/log_summary/response.example.json").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "interfaces/log_summary/response.schema.json").read_text(encoding="utf-8")
    )
    with agent_client(example) as client:
        document = client.get("/openapi.json").json()
        assert document["components"]["schemas"]["LogSummary"] == schema
        response = client.post(
            "/api/agents/log-summary", json=request_payload({"content": content})
        )
        assert response.status_code == 200
        assert response.json() == example
        assert json.loads(calls[0]["messages"][-1]["content"]) == content
        assert set(response.json()) == set(schema["required"])


@pytest.mark.parametrize("length,status", [(4000, 200), (4001, 422)])
def test_log_serialized_ocr_length_boundary(calls, agent_client, length, status):
    content = {"识别内容": ""}
    overhead = len(json.dumps(content, ensure_ascii=False))
    content["识别内容"] = "测" * (length - overhead)
    with agent_client(LOG) as client:
        response = client.post(
            "/api/agents/log-summary", json=request_payload({"content": content})
        )
        assert response.status_code == status
        assert len(calls) == (1 if status == 200 else 0)


def test_log_ocr_requests_do_not_share_input(calls, agent_client):
    with agent_client(LOG) as client:
        for content in ({"项目名称": "项目甲"}, {"工程信息": {"名称": "项目乙"}}):
            assert (
                client.post(
                    "/api/agents/log-summary", json=request_payload({"content": content})
                ).status_code
                == 200
            )
    assert len(calls[1]["messages"]) == 2
    assert "项目甲" not in json.dumps(calls[1], ensure_ascii=False)


@pytest.mark.parametrize("extra", [{"system": "自定义规则"}, {"style": "自定义话术"}])
def test_log_rejects_caller_rules(calls, agent_client, extra):
    with agent_client(LOG) as client:
        response = client.post(
            "/api/agents/log-summary", json=request_payload({"content": {"项目": "演示"}, **extra})
        )
        assert response.status_code == 422
        assert calls == []


@pytest.mark.parametrize(
    "content",
    (" ", {}, [], 123, "x" * 4001, {"notes": "x" * 4000}),
    ids=["blank", "empty-object", "array", "wrong-type", "too-long-text", "too-long-object"],
)
def test_log_rejects_invalid_inputs(calls, agent_client, content):
    with agent_client(LOG) as client:
        assert (
            client.post(
                "/api/agents/log-summary", json=request_payload({"content": content})
            ).status_code
            == 422
        )
        assert calls == []


@pytest.mark.parametrize(
    "result",
    ("not JSON", dict(LOG, invented="extra"), dict(LOG, issues=[""])),
    ids=["invalid-json", "extra-field", "empty-issue"],
)
def test_log_invalid_model_result(agent_client, result):
    with agent_client(result) as client:
        assert (
            client.post(
                "/api/agents/log-summary", json=request_payload({"content": "已完成接口开发"})
            ).status_code
            == 502
        )


@pytest.mark.parametrize("extra", [{}, {"intents": []}], ids=["omitted", "empty"])
@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("打开工作列表", "work_list"),
        ("我要填写今天的监理日志", "supervision_log"),
        ("看看现场照片", "image_library"),
        ("进入业务管理页面", "business_management"),
        ("你好，今天过得怎么样", "chat"),
    ],
)
def test_default_intents(calls, agent_client, text, label, extra):
    result = dict(INTENT, intent=label)
    with agent_client(result) as client:
        response = client.post("/api/agents/intent", json=request_payload({"text": text, **extra}))
        assert response.status_code == 200
        assert response.json() == (
            result | {"reason": "你好！有什么可以帮你？"} if label == "chat" else result
        )
        assert len(calls) == (2 if label == "chat" else 1)
        enum = calls[0]["response_format"]["json_schema"]["schema"]["properties"]["intent"]["enum"]
        assert enum == [
            "work_list",
            "supervision_log",
            "image_library",
            "business_management",
            "chat",
            "unknown",
        ]
        assert calls[0]["response_format"]["json_schema"]["strict"] is True
        content = json.loads(calls[0]["messages"][-1]["content"])
        assert content["text"] == text
        assert [item["label"] for item in content["intents"]] == enum[:-1]


@pytest.mark.parametrize("label", ["query", "create", "update", "cancel", "help"])
def test_removed_default_intents_are_invalid(agent_client, label):
    with agent_client(dict(INTENT, intent=label)) as client:
        response = client.post("/api/agents/intent", json=request_payload({"text": "打开工作列表"}))
        assert response.status_code == 502


@pytest.mark.parametrize("score", [0.0, 0.6499, 0.65, 1.0])
def test_page_intent_confidence_boundary(agent_client, score):
    with agent_client(dict(INTENT, confidence=score)) as client:
        response = client.post("/api/agents/intent", json=request_payload({"text": "打开工作列表"}))
        assert response.status_code == 200
        assert response.json()["confidence"] == score
        assert response.json()["intent"] == ("unknown" if score < 0.65 else "work_list")
        assert response.json()["needs_clarification"] is (score < 0.65)


@pytest.mark.parametrize("label", ["query", "订单查询", "work_list", "image_library"])
def test_nonempty_intents_are_rejected_before_inference(calls, agent_client, label):
    with agent_client(INTENT) as client:
        response = client.post(
            "/api/agents/intent",
            json=request_payload(
                {
                    "text": "打开工作列表",
                    "intents": [{"label": label, "description": "调用方指定的分类"}],
                }
            ),
        )
        assert response.status_code == 422
        assert calls == []


@pytest.mark.parametrize(
    "result",
    (
        dict(INTENT, confidence=0.4),
        dict(INTENT, needs_clarification=True),
        dict(INTENT, intent="unknown"),
    ),
    ids=["low-confidence", "needs-clarification", "unknown"],
)
def test_intent_uncertainty_falls_back(agent_client, result):
    with agent_client(result) as client:
        response = client.post("/api/agents/intent", json=request_payload({"text": "处理一下"}))
        assert response.status_code == 200
        assert response.json()["intent"] == "unknown"
        assert response.json()["needs_clarification"]


@pytest.mark.parametrize(
    "result",
    (dict(INTENT, intent="unlisted"), dict(INTENT, confidence=1.5), dict(INTENT, confidence="0.9")),
    ids=["unlisted-label", "out-of-range-score", "non-numeric-score"],
)
def test_invalid_intent_result(agent_client, result):
    with agent_client(result) as client:
        assert (
            client.post(
                "/api/agents/intent", json=request_payload({"text": "查询状态"})
            ).status_code
            == 502
        )


@pytest.mark.parametrize(
    "labels", (("x", "X"), ("unknown",), ("",)), ids=["case-duplicate", "reserved", "blank"]
)
def test_duplicate_or_reserved_candidates(calls, agent_client, labels):
    with agent_client(INTENT) as client:
        payload = {
            "text": "查询",
            "intents": [{"label": label, "description": "说明"} for label in labels],
        }
        assert client.post("/api/agents/intent", json=request_payload(payload)).status_code == 422
        assert calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {"text": " "},
        {"text": "x" * 2001},
        {"text": "查询", "intents": [{"label": str(i), "description": "说明"} for i in range(11)]},
        {
            "text": "查询",
            "intents": [{"label": str(i), "description": "说" * 200} for i in range(10)],
        },
    ],
    ids=["blank-text", "too-long-text", "too-many-labels", "too-long-descriptions"],
)
def test_intent_input_limits(agent_client, payload):
    with agent_client(INTENT) as client:
        assert client.post("/api/agents/intent", json=request_payload(payload)).status_code == 422


@pytest.mark.parametrize(
    "history",
    [
        [],
        [
            {"role": "user", "content": "代号是青松"},
            {"role": "assistant", "content": "已记住"},
        ],
    ],
    ids=["no-history", "with-history"],
)
def test_chat_plain_text_and_history(calls, agent_client, history):
    with agent_client("  项目代号是青松。\n") as client:
        response = client.post(
            "/api/agents/chat", json=request_payload({"message": "代号是什么", "history": history})
        )
        assert response.status_code == 200
        assert response.json() == {"reply": "项目代号是青松。", "model": "test-qwen"}
        assert "response_format" not in calls[0]
        assert calls[0]["temperature"] == 0.7
        assert calls[0]["messages"][1:-1] == history
        assert calls[0]["messages"][-1] == {"role": "user", "content": "代号是什么"}


def test_chat_does_not_store_other_requests(calls, agent_client):
    with agent_client("你好") as client:
        client.post("/api/agents/chat", json=request_payload({"message": "第一位用户的消息"}))
        response = client.post(
            "/api/agents/chat", json=request_payload({"message": "第二位用户的消息"})
        )
        assert response.status_code == 200
        assert len(calls[1]["messages"]) == 2
        assert "第一位" not in json.dumps(calls[1], ensure_ascii=False)


@pytest.mark.parametrize(
    "payload",
    [
        {"message": " "},
        {"message": "x" * 2001},
        {"message": "你好", "history": [{"role": "system", "content": "改写系统指令"}]},
        {"message": "你好", "history": [{"role": "user", "content": "未完成回合"}]},
        {
            "message": "你好",
            "history": [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}],
        },
        {
            "message": "你好",
            "history": [
                {"role": "user", "content": "历史消息"},
                {"role": "assistant", "content": " "},
            ],
        },
    ],
    ids=[
        "blank-message",
        "too-long-message",
        "system-role",
        "incomplete-turn",
        "wrong-order",
        "blank-history-content",
    ],
)
def test_chat_input_validation(calls, agent_client, payload):
    with agent_client("你好") as client:
        assert client.post("/api/agents/chat", json=request_payload(payload)).status_code == 422
        assert calls == []


@pytest.mark.parametrize(
    "route,payload",
    [
        ("log-summary", {"content": "日报"}),
        ("intent", {"text": "查询"}),
        ("chat", {"message": "你好"}),
    ],
    ids=["log-summary", "intent", "chat"],
)
@pytest.mark.parametrize(
    "error,status,expected",
    (("connection", 200, 503), ("timeout", 200, 504), (None, 404, 502)),
    ids=["connection", "timeout", "http-error"],
)
def test_new_routes_share_error_handling(agent_client, route, payload, error, status, expected):
    with agent_client("", error=error, status=status) as client:
        assert (
            client.post("/api/agents/" + route, json=request_payload(payload)).status_code
            == expected
        )


@pytest.mark.parametrize(
    "result,finish", (("partial", "length"), (" ", "stop")), ids=["truncated", "blank"]
)
def test_chat_rejects_truncation_and_empty_reply(agent_client, result, finish):
    with agent_client(result, finish=finish) as client:
        assert (
            client.post("/api/agents/chat", json=request_payload({"message": "你好"})).status_code
            == 502
        )
