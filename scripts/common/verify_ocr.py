"""对运行中的合并 API 做真实新版监理日志 OCR 验收。"""

import argparse
import json
import os

import httpx

from app.config import ROOT


def verify(client: httpx.Client, photo: str, task_id: str = "") -> dict:
    checks = []

    response = client.get("/health")
    response.raise_for_status()
    if response.json() != {"status": "ok"}:
        raise ValueError("主应用存活检查失败")
    checks.append({"path": "/health", "status": response.status_code})

    response = client.get("/diagnostics")
    response.raise_for_status()
    if not response.json().get("data", {}).get("ok"):
        raise ValueError("OCR 运行依赖检查失败")
    checks.append({"path": "/diagnostics", "status": response.status_code})

    payload = {"path": photo, "taskId": task_id} if task_id else {"path": photo}
    response = client.post("/ocr/journal", json=payload)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != 200 or "data" not in body:
        raise ValueError("/ocr/journal 未返回有效监理日志结果")
    checks.append({"path": "/ocr/journal", "status": response.status_code})

    processed = body["data"]
    if not processed.get("common") and not processed.get("fields"):
        raise ValueError("监理日志未返回业务字段")
    return {
        "passed": True,
        "checks": checks,
        "task_id": processed.get("taskId"),
        "document_type": processed.get("documentType"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", required=True, help="PROJECTS_ROOT 内的照片相对路径")
    parser.add_argument("--task-id", default="", help="可选业务任务 ID，原样回显到 taskId")
    parser.add_argument(
        "--url", default=os.environ.get("BUSINESS_API_URL", "http://127.0.0.1:8309")
    )
    args = parser.parse_args()
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=180, trust_env=False) as client:
        result = verify(client, args.photo, args.task_id)
    report = ROOT / "verification/ocr/api-live-result.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    print(f"验收报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
