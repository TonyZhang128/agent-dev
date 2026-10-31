"""对运行中的合并 API 做真实 OCR 验收；仅显式 --out 时写业务输出。"""

import argparse
import json
import os
from pathlib import Path

import httpx

from app.config import ROOT


def verify(client: httpx.Client, photo: str, form: str, cfg: dict, out: str = "") -> dict:
    checks = []

    def data(path: str, payload: dict | None = None) -> dict:
        response = client.get(path) if payload is None else client.post(path, json=payload)
        response.raise_for_status()
        body = response.json()
        if body.get("status") != 200 or "data" not in body:
            raise ValueError(f"{path} 未返回有效文档处理结果")
        checks.append({"path": path, "status": response.status_code})
        return body["data"]

    response = client.get("/health")
    response.raise_for_status()
    if response.json() != {"status": "ok"}:
        raise ValueError("主应用存活检查失败")
    if not data("/health/deps")["ok"]:
        raise ValueError("OCR 运行依赖检查失败")
    fields = data(f"/ocr/sheet/{form}")
    if not fields:
        raise ValueError("表样未提供可填字段")
    response = client.get(f"/ocr/blank/{form}.png")
    response.raise_for_status()
    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("空白表预览不是 PNG")
    recognized = data("/ocr/recognize", {"path": photo, "form": form})
    if not recognized["lines"]:
        raise ValueError("照片未识别出文字")
    simple = data("/ocr/jianbiao", {"path": photo, "form": form, "cfg": cfg})
    if not simple["recognized"]:
        raise ValueError("简表未识别出字段")
    filled = data("/ocr/fill", {"form": form, "cfg": cfg, "values": simple["values"], "out": out})
    if filled["errors"] or (out and not filled["pdf"]):
        raise ValueError("填表公式或文件生成失败")
    draft = data(
        "/wbs/draft",
        {"prefix": "VERIFY", "drawings": [], "basis": {"facts": [["路线起讫", "K0+000~K1+000"]]}},
    )
    if not draft["units"]:
        raise ValueError("WBS 未生成划分初稿")
    return {
        "passed": True,
        "checks": checks,
        "ocr_lines": len(recognized["lines"]),
        "ocr_fields": len(recognized["fields"]),
        "ocr_warning": recognized["warning"],
        "jianbiao_fields": len(simple["recognized"]),
        "sheet_fields": len(fields),
        "generated_pdf": bool(filled["pdf"]),
        "generated_xlsx": bool(filled["xlsx"]),
        "wbs_units": len(draft["units"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", required=True, help="PROJECTS_ROOT 内的照片相对路径")
    parser.add_argument("--form", default="JB12-4.2.2")
    parser.add_argument("--cfg", type=Path, help="可选的配置平台 cfg JSON")
    parser.add_argument("--out", default="", help="数据池内输出 PDF 相对路径，默认不写文件")
    parser.add_argument(
        "--url", default=os.environ.get("BUSINESS_API_URL", "http://127.0.0.1:8309")
    )
    args = parser.parse_args()
    cfg = json.loads(args.cfg.read_text(encoding="utf-8")) if args.cfg else {}
    with httpx.Client(base_url=args.url.rstrip("/"), timeout=180, trust_env=False) as client:
        result = verify(client, args.photo, args.form, cfg, args.out)
    report = ROOT / "verification/ocr/api-live-result.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    print(f"验收报告：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
