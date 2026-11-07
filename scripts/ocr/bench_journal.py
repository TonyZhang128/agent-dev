"""批量运行新版监理日志识别，输出到 Git 忽略的 verification/。

示例：
    uv run --locked python -m scripts.ocr.bench_journal ./photos
    uv run --locked python -m scripts.ocr.bench_journal app/ocr/resources/jl1.jpg --output /tmp/result.json

脚本只做批量 OCR 和结果归档，不调用 mainWork 拆分模型、不读取模板、不修改数据池；
真实识别需要可用的 OCR 模型目录和 OCR_DEVICE 配置。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.ocr import journal

SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_OUTPUT = Path("verification/ocr/journal-bench.json")


def _photos(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(
        path for path in target.iterdir() if path.is_file() and path.suffix.lower() in SUFFIXES
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量运行新版监理日志识别。")
    parser.add_argument("photos", type=Path, help="照片文件或目录。")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"结果 JSON 路径；默认 {DEFAULT_OUTPUT}。",
    )
    args = parser.parse_args(argv)
    if not args.photos.exists():
        parser.error(f"照片路径不存在：{args.photos}")
    paths = _photos(args.photos)
    if not paths:
        parser.error(f"目录内没有可识别的图片：{args.photos}")

    results = []
    for path in paths:
        started = time.perf_counter()
        try:
            sheet = journal.read_sheet(path)
        except Exception as exc:  # noqa: BLE001 —— 批处理逐张记录失败，不中断其余照片
            results.append({"path": path.name, "error": type(exc).__name__})
            continue
        main_work = next(
            (reading.value for reading in sheet.readings if reading.spec.key == "mainWork"),
            "",
        )
        results.append(
            {
                "path": path.name,
                "ms": round((time.perf_counter() - started) * 1000),
                "frame": sheet.location.how,
                "warning": (journal.WARNING_NO_FRAME if sheet.location.kind == "whole" else ""),
                "mainWork": main_work,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已写入 {args.output}（{len(results)} 张）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
