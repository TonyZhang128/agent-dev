"""将已识别字段和 mainWork 分类值映射到既有业务结构。"""

from typing import TypedDict

import cv2
import numpy as np

from app.ocr.journal.field_matching import field_bounds_on_canvas
from app.ocr.journal.main_work_split import merge_main_work
from app.ocr.journal.models import JournalRecognition, OcrTextBox
from app.schemas.ocr import (
    JournalImageInfo,
    JournalOCRBox,
    JournalOCRField,
    JournalPolygon,
    JournalRecognitionData,
    JournalRecognitionResponse,
    MainWorkValues,
)

DOCUMENT_TYPE = "supervision_diary"


class JournalCommon(TypedDict):
    """既有外部协议的公共字段，保持 camelCase 序列化名称。"""

    projectName: str | None
    documentNo: str | None
    supervisionOrg: str | None
    recorderName: str | None
    recorderPosition: str | None
    weather: str | None
    logDate: str | None
    reviewerName: str | None


class MainWorkPayload(TypedDict):
    """mainWork 已分类原文。"""

    construction: str | None
    witness: str | None
    patrol: str | None


class JournalFields(TypedDict):
    """既有协议中的业务栏目。"""

    mainWork: MainWorkPayload
    issues: str | None
    nextDayPlan: str | None


class JournalPayload(TypedDict):
    """HTTP data 内的业务对象；不改变响应模型或 OpenAPI。"""

    taskId: str | None
    documentType: str
    common: JournalCommon
    fields: JournalFields


def build_processed_payload(
    recognition: JournalRecognition, values: MainWorkValues
) -> JournalPayload:
    """只映射已提取值，不补写模板占位符、示例值或当前日期。"""
    recognized = {
        reading.layout.key: reading.value.strip() or None for reading in recognition.readings
    }
    return {
        "taskId": recognition.task_id.strip() or None,
        "documentType": DOCUMENT_TYPE,
        "common": {
            "projectName": recognized.get("project"),
            "documentNo": recognized.get("number"),
            "supervisionOrg": recognized.get("supervision_org"),
            "recorderName": recognized.get("recorder"),
            "recorderPosition": recognized.get("position"),
            "weather": recognized.get("weather"),
            "logDate": recognized.get("date"),
            "reviewerName": recognized.get("reviewer"),
        },
        "fields": {
            "mainWork": {
                "construction": values.construction,
                "witness": values.witness,
                "patrol": values.patrol,
            },
            "issues": recognized.get("issues"),
            "nextDayPlan": recognized.get("next_day_plan"),
        },
    }


def _polygon(points: np.ndarray) -> JournalPolygon:
    """保留四角环绕顺序，显式转换为可校验、可序列化的像素坐标。"""
    if points.shape != (4, 2):
        raise ValueError("识别区域必须包含四个角点")
    return (
        (float(points[0, 0]), float(points[0, 1])),
        (float(points[1, 0]), float(points[1, 1])),
        (float(points[2, 0]), float(points[2, 1])),
        (float(points[3, 0]), float(points[3, 1])),
    )


def _box_corners(box: OcrTextBox) -> np.ndarray:
    if box.polygon:
        return np.asarray(box.polygon, dtype=np.float64)
    return np.array(
        [[box.x0, box.y0], [box.x1, box.y0], [box.x1, box.y1], [box.x0, box.y1]],
        dtype=np.float64,
    )


def build_recognition_response(recognition: JournalRecognition) -> JournalRecognitionResponse:
    """导出全部框与拆分前栏目；坐标回投原图，不修改本次识别结果。"""
    alignment = recognition.alignment
    canvas_to_work = np.linalg.inv(alignment.work_image_to_canvas)

    def photo_polygon(corners: np.ndarray) -> JournalPolygon:
        projected = cv2.perspectiveTransform(corners[None], canvas_to_work)[0]
        return _polygon(projected / recognition.photo.downscale_ratio)

    # 用对象身份关联，避免内容和坐标相等的重复检测框获得同一个 ID。
    identifiers = {id(box): f"box-{index}" for index, box in enumerate(recognition.boxes, 1)}
    boxes = [
        JournalOCRBox(
            id=identifiers[id(box)],
            text=box.text,
            confidence=box.confidence,
            polygon=photo_polygon(_box_corners(box)),
        )
        for box in recognition.boxes
    ]
    fields = []
    for reading in recognition.readings:
        x0, y0, x1, y1 = field_bounds_on_canvas(
            reading.layout,
            (alignment.canvas_width, alignment.canvas_height),
            alignment.table_rect_on_canvas,
        )
        text = (
            merge_main_work(recognition.readings)
            if reading.layout.key == "main_work"
            else reading.value.strip()
        )
        fields.append(
            JournalOCRField.model_validate(
                {
                    "key": reading.layout.key,
                    "label": reading.layout.label,
                    "text": text or None,
                    "confidence": reading.confidence,
                    "polygon": photo_polygon(
                        np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float64)
                    ),
                    "boxIds": [identifiers[id(box)] for box in reading.boxes],
                    "ambiguous": reading.ambiguous,
                    "visibleFraction": reading.visible_fraction,
                }
            )
        )
    return JournalRecognitionResponse(
        status=200,
        message="识别完成",
        data=JournalRecognitionData(
            taskId=recognition.task_id.strip() or None,
            documentType=DOCUMENT_TYPE,
            image=JournalImageInfo(
                width=recognition.photo.width,
                height=recognition.photo.height,
                coordinateSpace="exif_corrected_original",
            ),
            tablePolygon=_polygon(alignment.table_quad_in_photo),
            boxes=boxes,
            fields=fields,
        ),
    )
