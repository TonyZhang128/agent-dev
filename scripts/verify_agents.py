"""Verify the running API with real Qwen inference; save synthetic test responses."""

import json
import os
import time
from datetime import datetime
from importlib.metadata import version

import httpx

from app.config import ROOT, Settings
from app.schemas import BusinessPlan, ChatResponse, IntentResult, LogSummary


def main():
    settings = Settings()
    base_url = os.environ.get("BUSINESS_API_URL", "http://127.0.0.1:8000")
    report = {
        "checked_at": datetime.now().isoformat(),
        "api_url": base_url,
        "model": settings.llm_model,
        "framework_versions": {
            name: version(name) for name in ("langchain", "langchain-core", "langchain-openai")
        },
        "checks": [],
        "passed": False,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            base_url=base_url, timeout=settings.llm_timeout_seconds + 10, trust_env=False
        ) as client:
            client.get("/ready").raise_for_status()
            document = client.get("/openapi.json")
            document.raise_for_status()
            report["api_version"] = document.json()["info"]["version"]
            for path in ("/api/agents/log-summary", "/api/agents/intent", "/api/agents/chat"):
                assert path in document.json()["paths"], f"route missing: {path}"

            def post(name, path, payload, schema):
                request_started = time.monotonic()
                response = client.post(path, json=payload)
                result = {
                    "name": name,
                    "path": path,
                    "http_status": response.status_code,
                    "seconds": round(time.monotonic() - request_started, 2),
                }
                try:
                    result["response"] = response.json()
                except ValueError:
                    result["response"] = response.text[:500]
                report["checks"].append(result)
                response.raise_for_status()
                parsed = schema.model_validate(response.json())
                print(f"PASS {name}: HTTP {response.status_code}, {result['seconds']}s", flush=True)
                return parsed

            log = post(
                "structured_log",
                "/api/agents/log-summary",
                {
                    "content": {
                        "date": "2026-10-17",
                        "completed": ["完成订单查询接口开发"],
                        "pending": ["等待测试同事验收"],
                        "issues": ["测试环境账号尚未开通"],
                    }
                },
                LogSummary,
            )
            assert (
                log.date == "2026-10-17"
                and log.completed_items
                and log.pending_items
                and log.issues
            )

            text_log = post(
                "text_log",
                "/api/agents/log-summary",
                {"content": "已完成：整理接口文档。待办：明天补充调用示例。问题：无。"},
                LogSummary,
            )
            assert text_log.date is None and text_log.completed_items

            candidates = [
                {"label": "order_status", "description": "查询已有订单的处理状态"},
                {"label": "cancel_order", "description": "取消已有订单"},
            ]
            intent = post(
                "custom_intent",
                "/api/agents/intent",
                {"text": "帮我查询订单 A100 的当前处理状态", "intents": candidates},
                IntentResult,
            )
            assert intent.intent == "order_status" and not intent.needs_clarification
            default = post(
                "default_intent",
                "/api/agents/intent",
                {"text": "请查询订单 A100 当前的状态"},
                IntentResult,
            )
            assert default.intent == "query"
            unknown = post(
                "ambiguous_intent",
                "/api/agents/intent",
                {"text": "我想处理一下那个东西", "intents": candidates},
                IntentResult,
            )
            assert unknown.intent == "unknown" and unknown.needs_clarification

            first_message = "请记住项目代号是青松，只回复：已记住。"
            first = post("chat", "/api/agents/chat", {"message": first_message}, ChatResponse)
            followup = post(
                "chat_with_history",
                "/api/agents/chat",
                {
                    "message": "项目代号是什么？只回答代号。",
                    "history": [
                        {"role": "user", "content": first_message},
                        {"role": "assistant", "content": first.reply},
                    ],
                },
                ChatResponse,
            )
            assert "青松" in followup.reply

            post(
                "existing_business_plan",
                "/api/business/plan",
                {"instruction": "检查报销发票，齐全则提交部门经理审批，否则通知员工补齐。"},
                BusinessPlan,
            )
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        folder = ROOT / "verification"
        folder.mkdir(exist_ok=True)
        (folder / "agents-live-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            f"Passed: {report['passed']}; report: verification/agents-live-result.json", flush=True
        )


if __name__ == "__main__":
    main()
