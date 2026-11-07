"""真实照片本地验收：一次 OCR、字段覆盖图和规则拆分报告；默认不调用 LLM。"""

import argparse
import json
import time
from pathlib import Path

import cv2

from app.config import Settings
from app.ocr import journal
from app.ocr.core.resources import OCRResources, use_resources
from app.ocr.journal.field_matching import field_bounds_on_canvas
from app.ocr.journal.main_work_split import assemble_values, assign_by_headings, split_into_units


def inspect_photo(photo: Path, output: Path, task_id: str = "") -> dict:
    """调用真实 OCR 并显式导出本地报告；规则无法拆分时不伪造成功业务响应。"""
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
    main_work = next(
        reading for reading in recognition.readings if reading.layout.key == "main_work"
    )
    units = split_into_units(main_work.value, main_work.segments)
    assignments = assign_by_headings(units) if units else {}
    payload = None
    if assignments is not None:
        payload = {
            "status": 200,
            "message": "识别完成",
            "data": journal.build_processed_payload(
                recognition, assemble_values(units, assignments)
            ),
        }
    report = {
        "photo": str(photo),
        "table_corners": recognition.alignment.table_quad_in_photo.tolist(),
        "table_rect_on_canvas": recognition.alignment.table_rect_on_canvas,
        "line_support": recognition.alignment.line_support,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "split_strategy": "rules" if assignments is not None else "requires_model",
        "fields": regions,
        "response": payload,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if payload is not None:
        (output / "response.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
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
    print(f"已导出识别报告：{arguments.output}；拆分方式：{report['split_strategy']}")


if __name__ == "__main__":
    main()
