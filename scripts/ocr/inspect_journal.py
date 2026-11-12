"""真实照片本地验收：一次 OCR、字段覆盖图和原始识别报告；默认不调用 LLM。"""

import argparse
import json
import time
from pathlib import Path

import cv2

from app.config import Settings
from app.ocr import journal
from app.ocr.core.resources import OCRResources, use_resources
from app.ocr.journal.field_matching import field_bounds_on_canvas
from app.ocr.journal.output import merge_main_work


def inspect_photo(photo: Path, output: Path, task_id: str = "") -> dict:
    """调用真实 OCR 并导出识别结果；业务生成统一使用 process，不在检查脚本中另建路径。"""
    resources = OCRResources(Settings())
    started = time.perf_counter()
    try:
        with use_resources(resources):
            recognition = journal.recognize_journal(photo, task_id=task_id)
    finally:
        resources.close()
    canvas = recognition.alignment.canvas.copy()
    regions = []
    for reading in recognition.readings:
        left, top, right, bottom = (
            round(coordinate)
            for coordinate in field_bounds_on_canvas(
                reading.layout,
                (recognition.alignment.canvas_width, recognition.alignment.canvas_height),
                recognition.alignment.table_rect_on_canvas,
            )
        )
        cv2.rectangle(canvas, (left, top), (right, bottom), (0, 160, 0), 2)
        cv2.putText(
            canvas,
            reading.layout.key,
            (left + 3, top + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 120, 0),
            1,
        )
        regions.append(
            {
                "field": reading.layout.key,
                "value": reading.value,
                "confidence": reading.confidence,
                "ambiguous": reading.ambiguous,
                "visible_fraction": reading.visible_fraction,
                "rect": [left, top, right, bottom],
                "boxes": [
                    {"text": box.text, "polygon": box.polygon, "confidence": box.confidence}
                    for box in reading.boxes
                ],
            }
        )
    source = merge_main_work(recognition.readings)
    recognized = journal.build_recognition_response(recognition)
    report = {
        "photo": str(photo),
        "table_corners": recognition.alignment.table_quad_in_photo.tolist(),
        "table_rect_on_canvas": recognition.alignment.table_rect_on_canvas,
        "line_support": recognition.alignment.line_support,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "generation_required": bool(source.strip()),
        "fields": regions,
        "recognition": recognized.model_dump(mode="json"),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "recognition.json").write_text(
        recognized.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    # 此工具不生成业务结果，清除旧版本遗留结果以免误认成本次输出。
    (output / "response.json").unlink(missing_ok=True)
    cv2.imencode(".png", canvas)[1].tofile(output / "fields.png")
    cv2.imencode(".png", recognition.alignment.source_coverage_mask)[1].tofile(
        output / "coverage.png"
    )
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("verification/ocr/journal"))
    parser.add_argument("--task-id", default="")
    arguments = parser.parse_args(argv)
    report = inspect_photo(arguments.photo, arguments.output, arguments.task_id)
    print(f"已导出识别报告：{arguments.output}；需要生成：{report['generation_required']}")


if __name__ == "__main__":
    main()
