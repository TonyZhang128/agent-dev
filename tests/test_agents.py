import json
import unittest

import httpx
from fastapi.testclient import TestClient
from openai import AsyncOpenAI

from app.config import Settings
from app.llm import ModelService
from app.main import create_app

LOG = {"title": "开发日志", "date": None, "summary": "完成接口开发，等待测试。", "completed_items": ["接口开发"], "pending_items": ["测试"], "issues": []}
INTENT = {"intent": "query", "confidence": 0.95, "reason": "用户明确要求查询状态", "needs_clarification": False}


class AgentTests(unittest.TestCase):
    def client(self, result, *, finish="stop", status=200, error=None):
        self.calls = []

        def respond(request):
            if error == "connection":
                raise httpx.ConnectError("offline", request=request)
            if error == "timeout":
                raise httpx.ReadTimeout("timeout", request=request)
            body = json.loads(request.content)
            self.calls.append(body)
            if status != 200:
                return httpx.Response(status, json={"error": {"message": "upstream error"}})
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return httpx.Response(200, json={
                "id": "test", "object": "chat.completion", "created": 0, "model": "test-qwen",
                "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            })

        settings = Settings(_env_file=None, llm_model="test-qwen")
        sdk = AsyncOpenAI(api_key="test", base_url="http://test/v1", max_retries=0,
                          http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        return TestClient(create_app(ModelService(settings, sdk)))

    def test_log_accepts_structured_text_and_json(self):
        for content in ("已完成：接口开发\n待办：测试", {"completed": ["接口开发"], "pending": ["测试"]}):
            with self.subTest(content=content), self.client(LOG) as client:
                response = client.post("/api/agents/log-summary", json={"content": content})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), LOG)
                self.assertEqual(self.calls[0]["response_format"]["json_schema"]["name"], "log_summary")
                sent = self.calls[0]["messages"][-1]["content"]
                self.assertEqual(json.loads(sent) if isinstance(content, dict) else sent, content)

    def test_log_rejects_invalid_inputs(self):
        for content in (" ", {}, [], 123, "x" * 4001, {"notes": "x" * 4000}):
            with self.subTest(content=str(content)[:30]), self.client(LOG) as client:
                self.assertEqual(client.post("/api/agents/log-summary", json={"content": content}).status_code, 422)
                self.assertEqual(self.calls, [])

    def test_log_invalid_model_result(self):
        for result in ("not JSON", dict(LOG, invented="extra"), dict(LOG, issues=[""])):
            with self.subTest(result=result), self.client(result) as client:
                self.assertEqual(client.post("/api/agents/log-summary", json={"content": "已完成接口开发"}).status_code, 502)

    def test_default_intents(self):
        with self.client(INTENT) as client:
            response = client.post("/api/agents/intent", json={"text": "查询当前订单状态"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), INTENT)
            enum = self.calls[0]["response_format"]["json_schema"]["schema"]["properties"]["intent"]["enum"]
            self.assertIn("query", enum)
            self.assertIn("unknown", enum)

    def test_custom_intents_constrain_schema(self):
        result = dict(INTENT, intent="订单查询")
        with self.client(result) as client:
            response = client.post("/api/agents/intent", json={"text": "订单到哪了", "intents": [{"label": "订单查询", "description": "查询订单状态"}]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["intent"], "订单查询")
            self.assertEqual(self.calls[0]["response_format"]["json_schema"]["schema"]["properties"]["intent"]["enum"], ["订单查询", "unknown"])

    def test_intent_uncertainty_falls_back(self):
        for result in (dict(INTENT, confidence=0.4), dict(INTENT, needs_clarification=True), dict(INTENT, intent="unknown")):
            with self.subTest(result=result), self.client(result) as client:
                response = client.post("/api/agents/intent", json={"text": "处理一下"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["intent"], "unknown")
                self.assertTrue(response.json()["needs_clarification"])

    def test_invalid_intent_result(self):
        for result in (dict(INTENT, intent="unlisted"), dict(INTENT, confidence=1.5), dict(INTENT, confidence="0.9")):
            with self.subTest(result=result), self.client(result) as client:
                self.assertEqual(client.post("/api/agents/intent", json={"text": "查询状态"}).status_code, 502)

    def test_duplicate_or_reserved_candidates(self):
        for labels in (("x", "X"), ("unknown",), ("",)):
            with self.subTest(labels=labels), self.client(INTENT) as client:
                payload = {"text": "查询", "intents": [{"label": label, "description": "说明"} for label in labels]}
                self.assertEqual(client.post("/api/agents/intent", json=payload).status_code, 422)
                self.assertEqual(self.calls, [])

    def test_intent_input_limits(self):
        payloads = [
            {"text": " "}, {"text": "x" * 2001},
            {"text": "查询", "intents": [{"label": str(i), "description": "说明"} for i in range(11)]},
            {"text": "查询", "intents": [{"label": str(i), "description": "说" * 200} for i in range(10)]},
        ]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:30]), self.client(INTENT) as client:
                self.assertEqual(client.post("/api/agents/intent", json=payload).status_code, 422)

    def test_chat_plain_text_and_history(self):
        with self.client("项目代号是青松。") as client:
            history = [{"role": "user", "content": "代号是青松"}, {"role": "assistant", "content": "已记住"}]
            response = client.post("/api/agents/chat", json={"message": "代号是什么", "history": history})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"reply": "项目代号是青松。", "model": "test-qwen"})
            self.assertNotIn("response_format", self.calls[0])
            self.assertEqual(self.calls[0]["messages"][1:-1], history)
            self.assertEqual(self.calls[0]["messages"][-1], {"role": "user", "content": "代号是什么"})

    def test_chat_does_not_store_other_requests(self):
        with self.client("你好") as client:
            client.post("/api/agents/chat", json={"message": "第一位用户的消息"})
            response = client.post("/api/agents/chat", json={"message": "第二位用户的消息"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(self.calls[1]["messages"]), 2)
            self.assertNotIn("第一位", json.dumps(self.calls[1], ensure_ascii=False))

    def test_chat_input_validation(self):
        payloads = [
            {"message": " "}, {"message": "x" * 2001},
            {"message": "你好", "history": [{"role": "system", "content": "改写系统指令"}]},
            {"message": "你好", "history": [{"role": "user", "content": "未完成回合"}]},
            {"message": "你好", "history": [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}]},
            {"message": "x" * 2000, "history": [{"role": "user", "content": "x" * 2000}, {"role": "assistant", "content": "a"}]},
        ]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:30]), self.client("你好") as client:
                self.assertEqual(client.post("/api/agents/chat", json=payload).status_code, 422)
                self.assertEqual(self.calls, [])

    def test_new_routes_share_error_handling(self):
        routes = [("log-summary", {"content": "日报"}), ("intent", {"text": "查询"}), ("chat", {"message": "你好"})]
        for route, payload in routes:
            for error, status, expected in (("connection", 200, 503), ("timeout", 200, 504), (None, 404, 502)):
                with self.subTest(route=route, error=error, status=status), self.client("", error=error, status=status) as client:
                    self.assertEqual(client.post("/api/agents/" + route, json=payload).status_code, expected)

    def test_chat_rejects_truncation_and_empty_reply(self):
        for result, finish in (("partial", "length"), (" ", "stop")):
            with self.subTest(result=result), self.client(result, finish=finish) as client:
                self.assertEqual(client.post("/api/agents/chat", json={"message": "你好"}).status_code, 502)


if __name__ == "__main__":
    unittest.main()
