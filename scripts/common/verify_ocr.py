"""对运行中的合并 API 做真实新版监理日志 OCR 验收。"""

import argparse
import json
import os

import httpx

from app.config import ROOT
from app.schemas.ocr import JournalRecognitionResponse, JournalResponse


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
    response = client.post("/ocr/journal/recognize", json=payload)
    response.raise_for_status()
    recognized = JournalRecognitionResponse.model_validate(response.json())
    checks.append({"path": "/ocr/journal/recognize", "status": response.status_code})

    response = client.post("/ocr/journal/process", json=recognized.data.model_dump(mode="json"))
    response.raise_for_status()
    processed = JournalResponse.model_validate(response.json()).data.jsonData
    checks.append({"path": "/ocr/journal/process", "status": response.status_code})

    response = client.post("/ocr/journal", json=payload)
    response.raise_for_status()
    combined = JournalResponse.model_validate(response.json()).data.jsonData
    checks.append({"path": "/ocr/journal", "status": response.status_code})
    # 模型措辞可能不同，普通栏目和原文回显必须一致；内容质量仍需独立人工核对。
    if (
        combined.common != processed.common
        or combined.fields.issues != processed.fields.issues
        or combined.fields.nextDayPlan != processed.fields.nextDayPlan
        or combined.fields.mainWork.content != processed.fields.mainWork.content
    ):
        raise ValueError("两阶段与组合入口的业务栏目或工作原文不一致")
    source = next(field.text for field in recognized.data.fields if field.key == "main_work")
    if processed.fields.mainWork.content != (source or ""):
        raise ValueError("业务生成未原样保留工作原文")
    return {
        "passed": True,
        "checks": checks,
        "task_id": recognized.data.taskId,
        "document_type": recognized.data.documentType,
        "content_quality": "requires_human_review",
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
