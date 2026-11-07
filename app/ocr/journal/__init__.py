"""监理日志照片识别：定位表格 → 单次整页 OCR → 栏目匹配 → 业务结构。

这条链路独立于旧的逐格识别实现。同步阶段只做 OCR 并返回 JournalSheet；
mainWork 拆分由 Agent 在异步层完成，最终由 build_result() 组装业务结构。
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.ocr.journal.fields import read_fields
from app.ocr.journal.frame import locate
from app.ocr.journal.image import load_photo
from app.ocr.journal.reading import read_boxes
from app.ocr.journal.spec import DOCUMENT_TYPE, FIELD_SPECS, FORM_CODE, FORM_NAME
from app.ocr.journal.split import MAX_SPLIT_CHARACTERS, split_main_work
from app.ocr.journal.types import FieldReading, FieldSpec, PageLocation, Photo
from app.schemas.ocr import MainWorkValues

WARNING_NO_FRAME = "未检测到表格外框，按整张照片校正，请核对定位"

__all__ = [
    "MAX_SPLIT_CHARACTERS",
    "JournalSheet",
    "build_result",
    "read_sheet",
    "split_main_work",
]


@dataclass(frozen=True)  # 不可重新赋值的数据类
class JournalSheet:
    """同步 OCR 阶段的完整结果；不包含任何业务字段分配。"""

    source: Photo
    location: PageLocation
    readings: tuple[FieldReading, ...]
    task_id: str = ""


def read_sheet(photo: Path | None, img: str = "", task_id: str = "") -> JournalSheet:
    """OCR识别监理日记图片
    输入：图片路径与 base64 图片至少提供一个，同时提供时优先 base64。

    返回的 FieldReading 保留 mainWork 原文与文字框位置片段；本函数不调用模型。
    """
    source = load_photo(photo, img)
    location = locate(source)
    readings = read_fields(location.sheet, FIELD_SPECS, read_boxes)
    return JournalSheet(source, location, tuple(readings), task_id)


def build_result(sheet: JournalSheet, values: MainWorkValues) -> dict:
    """组装内部结果；HTTP 层只取 processed。"""
    recognized = _recognized(sheet.readings)
    return {
        "form": FORM_CODE,
        "formName": FORM_NAME,
        "frame": {
            "how": sheet.location.how,
            "quad": np.rint(sheet.location.quad).astype(int).tolist(),
        },
        "recognized": recognized,
        "detail": _detail(sheet.readings, sheet.location),
        "processed": _processed(recognized, values, sheet.task_id),
        "warning": WARNING_NO_FRAME if sheet.location.kind == "whole" else "",
        "image": {"width": sheet.source.width, "height": sheet.source.height},
    }


def _recognized(readings: tuple[FieldReading, ...]) -> dict[str, str]:
    """原始栏目值；mainWork 必须先拆分，不能再整段复制到三个子栏。"""
    values: dict[str, str] = {}
    for reading in readings:
        if reading.value and reading.spec.key != "mainWork":
            values[reading.spec.key] = reading.value
    return values


def _detail(readings: tuple[FieldReading, ...], location: PageLocation) -> list[dict]:
    return [
        {
            "field": reading.spec.key,
            "label": reading.spec.label,
            "value": reading.value,
            "conf": reading.conf,
            "rect": _detail_rect(reading.spec, location),
        }
        for reading in readings
    ]


def _detail_rect(spec: FieldSpec, location: PageLocation) -> list[int]:
    x, y, width, height = spec.rect
    canvas_width, canvas_height = location.width, location.height
    return [
        round(x * canvas_width),
        round(y * canvas_height),
        round((x + width) * canvas_width),
        round((y + height) * canvas_height),
    ]


def _processed(recognized: dict, values: MainWorkValues, task_id: str) -> dict:
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
                "construction": values.construction,
                "witness": values.witness,
                "patrol": values.patrol,
            },
            "issues": text("issues"),
            "nextDayPlan": text("next_day_plan"),
        },
    }
