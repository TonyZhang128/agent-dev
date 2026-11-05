"""监理日志照片识别：定位表格 → 单次整页 OCR → 栏目匹配 → 业务结构。

这条链路独立于旧的逐格识别实现；对外只暴露 read_photo()。
"""

from pathlib import Path

import numpy as np

from app.ocr.journal.fields import read_fields
from app.ocr.journal.frame import locate
from app.ocr.journal.image import load_photo
from app.ocr.journal.reading import read_boxes
from app.ocr.journal.spec import (
    DOCUMENT_TYPE,
    FIELD_SPECS,
    FORM_CODE,
    FORM_NAME,
    MAIN_WORK_PARTS,
)
from app.ocr.journal.types import FieldReading, FieldSpec, PageLocation, Photo

WARNING_NO_FRAME = "未检测到表格外框，按整张照片校正，请核对定位"


def read_photo(photo: Path | None, img: str = "", task_id: str = "") -> dict:
    """识别监理日志照片；照片路径与 base64 图片至少提供一个，同时提供时优先 base64。"""
    source = load_photo(photo, img)
    location = locate(source)
    readings = read_fields(location.sheet, FIELD_SPECS, read_boxes)
    return _result(source, location, readings, task_id)


def _result(
    source: Photo,
    location: PageLocation,
    readings: list[FieldReading],
    task_id: str,
) -> dict:
    recognized = _recognized(readings)
    return {
        "form": FORM_CODE,
        "formName": FORM_NAME,
        "frame": {
            "how": location.how,
            "quad": np.rint(location.quad).astype(int).tolist(),
        },
        "recognized": recognized,
        "detail": _detail(readings, location),
        "processed": _processed(recognized, task_id),
        "warning": WARNING_NO_FRAME if location.kind == "whole" else "",
        "image": {"width": source.width, "height": source.height},
    }


def _recognized(readings: list[FieldReading]) -> dict[str, str]:
    """mainWork 整格结果暂时同时回填到 construction/witness/patrol。"""
    values: dict[str, str] = {}
    for reading in readings:
        if not reading.value:
            continue
        if reading.spec.key == "mainWork":
            for key, _label in MAIN_WORK_PARTS:
                values[key] = reading.value
        else:
            values[reading.spec.key] = reading.value
    return values


def _detail(readings: list[FieldReading], location: PageLocation) -> list[dict]:
    items: list[dict] = []
    for reading in readings:
        rect = _detail_rect(reading.spec, location)
        if reading.spec.key == "mainWork":
            for field, label in MAIN_WORK_PARTS:
                items.append(
                    {
                        "field": field,
                        "label": label,
                        "value": reading.value,
                        "conf": reading.conf,
                        "rect": rect,
                    }
                )
        else:
            items.append(
                {
                    "field": reading.spec.key,
                    "label": reading.spec.label,
                    "value": reading.value,
                    "conf": reading.conf,
                    "rect": rect,
                }
            )
    return items


def _detail_rect(spec: FieldSpec, location: PageLocation) -> list[int]:
    x, y, width, height = spec.rect
    canvas_width, canvas_height = location.width, location.height
    return [
        round(x * canvas_width),
        round(y * canvas_height),
        round((x + width) * canvas_width),
        round((y + height) * canvas_height),
    ]


def _processed(recognized: dict, task_id: str) -> dict:
    def text(key: str) -> str | None:
        value = (recognized.get(key) or "").strip()
        return value or None

    return {
        "taskId": task_id.strip() or None,
        "documentType": DOCUMENT_TYPE,
        "common": {
            "projectName": text("project"),
            "documentNo": text("number"),
            "supervisionOrg": text("supervision_org"),
            "recorderName": text("recorder"),
            "recorderPosition": text("position"),
            "weather": text("weather"),
            "logDate": text("date"),
            "reviewerName": text("reviewer"),
        },
        "fields": {
            "mainWork": {
                "construction": text("construction"),
                "witness": text("witness"),
                "patrol": text("patrol"),
            },
            "issues": text("issues"),
            "nextDayPlan": text("next_day_plan"),
        },
    }
