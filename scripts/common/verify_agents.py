"""Verify the running API with the supplied OCR input and versioned regression cases."""

import json
import os
import time
import unicodedata
from datetime import datetime
from importlib.metadata import version

import httpx

from app.config import ROOT, Settings
from app.schemas import BusinessPlan, ChatResponse, IntentResult, LogSummary


def log_matches_expectations(log: LogSummary, sample: dict) -> bool:
    """Check versioned factual constraints; wording still needs human review."""

    def normalize(text: str) -> str:
        return "".join(unicodedata.normalize("NFKC", text).split())

    expected = sample["expected_response"]
    if log.date != expected["date"]:
        return False
    # Check presence/absence without requiring the model to copy reference prose.
    for field in ("completed_items", "pending_items", "issues"):
        if bool(getattr(log, field)) != bool(expected[field]):
            return False
    rules = sample.get("acceptance", {})
    summary = normalize(log.summary)
    text = normalize(log.model_dump_json())
    return all(normalize(value) in summary for value in rules.get("summary_contains", [])) and all(
        normalize(value) not in text for value in rules.get("text_excludes", [])
    )


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

            def post(name, path, payload, schema, *, expected_status=200):
                payload = {
                    "user_id": "verification-user",
                    "session_id": "verification-session",
                    **payload,
                }
                if path in ("/api/agents/intent", "/api/agents/chat"):
                    payload = {"history": [], **payload}
                request_started = time.monotonic()
                response = client.post(path, json=payload)
                result = {
                    "name": name,
                    "path": path,
                    "request": payload,
                    "http_status": response.status_code,
                    "seconds": round(time.monotonic() - request_started, 2),
                }
                try:
                    result["response"] = response.json()
                except ValueError:
                    result["response"] = response.text[:500]
                report["checks"].append(result)
                if expected_status != 200:
                    result["expected_http_status"] = expected_status
                    result["passed"] = response.status_code == expected_status
                    assert result["passed"], (
                        f"{name}: expected HTTP {expected_status}, got {response.status_code}"
                    )
                    print(f"PASS {name}: HTTP {response.status_code}", flush=True)
                    return None
                response.raise_for_status()
                parsed = schema.model_validate(response.json())
                print(f"HTTP {name}: {response.status_code}, {result['seconds']}s", flush=True)
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

            log_dataset = json.loads(
                (ROOT / "tests" / "fixtures" / "log_summary_cases.json").read_text(encoding="utf-8")
            )
            report["log_summary_dataset_version"] = log_dataset["version"]
            assert log_dataset["samples"], "log summary dataset must not be empty"
            log_mismatches = []
            provided_content = json.loads(
                (ROOT / "data" / "log_summary.json").read_text(encoding="utf-8")
            )
            provided_example = json.loads(
                (ROOT / "interfaces" / "log_summary" / "response.example.json").read_text(
                    encoding="utf-8"
                )
            )
            provided_log = post(
                "provided_ocr_log",
                "/api/agents/log-summary",
                {"content": provided_content},
                LogSummary,
            )
            provided_check = report["checks"][-1]
            provided_check["expected"] = provided_example
            provided_check["passed"] = log_matches_expectations(
                provided_log, {"expected_response": provided_example}
            )
            if not provided_check["passed"]:
                log_mismatches.append("provided_ocr_log")
            for sample in log_dataset["samples"]:
                log = post(sample["id"], log_dataset["endpoint"], sample["request"], LogSummary)
                check = report["checks"][-1]
                check["expected"] = sample["expected_response"]
                check["acceptance"] = sample.get("acceptance", {})
                check["passed"] = log_matches_expectations(log, sample)
                if not check["passed"]:
                    log_mismatches.append(sample["id"])
                print(f"{'PASS' if check['passed'] else 'FAIL'} {sample['id']}", flush=True)
            assert not log_mismatches, (
                f"log summary dataset mismatches: {', '.join(log_mismatches)}"
            )

            dataset = json.loads((ROOT / "data" / "intent.json").read_text(encoding="utf-8"))
            report["intent_dataset_version"] = dataset["version"]
            assert dataset["samples"], "intent dataset must not be empty"
            mismatches = []
            for sample in dataset["samples"]:
                intent = post(sample["id"], dataset["endpoint"], sample["request"], IntentResult)
                check = report["checks"][-1]
                check["expected"] = sample["expected"]
                check["passed"] = (
                    intent.intent == sample["expected"]["intent"]
                    and intent.needs_clarification == sample["expected"]["needs_clarification"]
                    and (
                        (intent.intent == "unknown" and intent.needs_clarification)
                        or (intent.confidence >= 0.65 and not intent.needs_clarification)
                    )
                )
                if not check["passed"]:
                    mismatches.append(sample["id"])
                print(f"{'PASS' if check['passed'] else 'FAIL'} {sample['id']}", flush=True)
            assert not mismatches, f"intent dataset mismatches: {', '.join(mismatches)}"
            for sample in dataset.get("invalid_requests", []):
                post(
                    sample["id"],
                    dataset["endpoint"],
                    sample["request"],
                    None,
                    expected_status=sample["expected_status"],
                )

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
