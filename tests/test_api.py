import json
import unittest

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelService
from app.main import create_app

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


class APITests(unittest.TestCase):
    def client(self, content=None, finish="stop", status=200, unavailable=False):
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
            self.assertEqual(body["response_format"]["type"], "json_schema")
            self.assertFalse(
                body["response_format"]["json_schema"]["schema"]["additionalProperties"]
            )
            self.assertEqual(body["model"], "test-qwen")
            self.assertEqual(body["reasoning_effort"], "none")
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

    def test_sdk_schema_and_route(self):
        with self.client() as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 200)
            response = client.post("/api/business/plan", json={"instruction": "审核报销"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), VALID)

    def test_invalid_inputs(self):
        with self.client() as client:
            for body in (
                {},
                {"instruction": "  "},
                {"instruction": "x" * 2001},
                {"instruction": 42},
                {"instruction": "x", "extra": True},
            ):
                with self.subTest(body=str(body)[:40]):
                    self.assertEqual(client.post("/api/business/plan", json=body).status_code, 422)

    def test_bad_model_json(self):
        broken = dict(VALID, steps=[dict(VALID["steps"][0], step=2)])
        for content in ("invalid json", "{}", json.dumps(broken)):
            with self.subTest(content=content), self.client(content=content) as client:
                self.assertEqual(
                    client.post("/api/business/plan", json={"instruction": "审核报销"}).status_code,
                    502,
                )

    def test_truncated_output(self):
        with self.client(finish="length") as client:
            self.assertEqual(
                client.post("/api/business/plan", json={"instruction": "审核报销"}).status_code, 502
            )

    def test_upstream_failure(self):
        with self.client(status=404) as client:
            self.assertEqual(
                client.post("/api/business/plan", json={"instruction": "审核报销"}).status_code, 502
            )

    def test_unavailable(self):
        with self.client(unavailable=True) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(
                client.post("/api/business/plan", json={"instruction": "审核报销"}).status_code, 503
            )


if __name__ == "__main__":
    unittest.main()
