"""把简表识别值映射为调用方约定的 JSON；不补写示例值或空字段。"""

import json
import math
import re
from pathlib import Path
from typing import Any, TypedDict

import cv2

from app.ocr.jianbiao.models import JianbiaoRecognition
from app.ocr.jianbiao.template import load_template


class JianbiaoCommon(TypedDict):
    projectName: str | None
    documentNo: str | None
    inspectorName: str | None
    inspectDate: str | None
    position: str | None


class SpotCheckRecord(TypedDict):
    rowIndex: int
    checkItem: str | None
    standardValue: str | None
    measuredValue: str | None
    passRate: float | None


class JianbiaoFields(TypedDict):
    records: list[SpotCheckRecord]


class JianbiaoPayload(TypedDict):
    taskId: str | None
    documentType: str
    common: JianbiaoCommon
    fields: JianbiaoFields


class JianbiaoResponse(TypedDict):
    status: int
    message: str
    data: JianbiaoPayload


def build_recognition_response(recognition: JianbiaoRecognition) -> JianbiaoResponse:
    """输出固定公共字段和全部记录行；未识别、歧义及非法数字均为 null。"""
    template = load_template(recognition.source_template_id)
    values = {key: value.strip() or None for key, value in recognition.values.items()}
    records: list[SpotCheckRecord] = []
    for row in template.row_groups:
        index = row.record_index
        records.append(
            {
                "rowIndex": index,
                "checkItem": values.get(f"check_item_{index}"),
                "standardValue": values.get(f"standard_value_{index}"),
                "measuredValue": values.get(f"measured_value_{index}"),
                "passRate": _pass_rate(values.get(f"pass_rate_{index}")),
            }
        )
    return {
        "status": 200,
        "message": "识别完成",
        "data": {
            "taskId": recognition.task_id.strip() or None,
            "documentType": template.template_id,
            "common": {
                "projectName": values.get("project"),
                "documentNo": values.get("number"),
                "inspectorName": values.get("inspector"),
                "inspectDate": values.get("inspect_date"),
                "position": values.get("position"),
            },
            "fields": {"records": records},
        },
    }


def build_diagnostics(recognition: JianbiaoRecognition) -> dict[str, Any]:
    """逐字段识别值、置信度、歧义标记和逐线支持率，供人工复核。"""
    return {
        "source_template_id": recognition.source_template_id,
        "line_support": recognition.alignment.line_support,
        "readings": [
            {
                "key": reading.key,
                "value": reading.value,
                "confidence": reading.confidence,
                "ambiguous": reading.ambiguous,
            }
            for reading in recognition.readings
        ],
    }


def export_recognition_outputs(recognition: JianbiaoRecognition, directory: Path) -> None:
    """写出约定 JSON、逐字段诊断和校正画布；HTTP out 参数与命令行验收共用。"""
    directory.mkdir(parents=True, exist_ok=True)
    response = build_recognition_response(recognition)
    (directory / "response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "diagnostics.json").write_text(
        json.dumps(build_diagnostics(recognition), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    cv2.imencode(".png", recognition.alignment.canvas)[1].tofile(directory / "aligned.png")


def _pass_rate(text: str | None) -> float | None:
    """只有完整数值（可带百分号）才进入数值字段，不用模糊截取伪造数字。"""
    if text is None or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)%?", text):
        return None
    value = float(text.removesuffix("%"))
    return value if math.isfinite(value) else None
