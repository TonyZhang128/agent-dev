"""将已识别字段和 mainWork 分类值映射到既有业务结构。"""

from collections.abc import Sequence

import cv2
import numpy as np

from app.ocr.journal.field_matching import field_bounds_on_canvas
from app.ocr.journal.models import FieldReading, JournalRecognition, OcrTextBox
from app.schemas.ocr import (
    JournalImageInfo,
    JournalOCRBox,
    JournalOCRField,
    JournalPolygon,
    JournalRecognitionData,
    JournalRecognitionResponse,
)

DOCUMENT_TYPE = "supervision_diary"


def merge_main_work(readings: Sequence[FieldReading]) -> str:
    """合并已排好阅读顺序的OCR片段；有问题的片段索引不能导致丢原文。"""
    reading = next((item for item in readings if item.layout.key == "main_work"), None)
    if reading is None:
        return ""
    source = reading.value.strip()
    if not source:
        return ""
    fragments = reading.segments
    if fragments and "".join(fragment.text for fragment in fragments) == source:
        return "\n".join(fragment.text for fragment in fragments if fragment.text).strip()
    return source


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
