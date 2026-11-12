"""RapidOCR 输出到简表文字框的唯一适配层。"""

import numpy as np

from app.ocr.core.engine import detect_text
from app.ocr.jianbiao.models import OcrTextBox


def detect_text_boxes(image: np.ndarray) -> list[OcrTextBox]:
    """对校正画布执行一次完整 OCR。"""
    boxes: list[OcrTextBox] = []
    for detection in detect_text(image):
        if not detection.text.strip():
            continue
        x0, y0 = (min(point[axis] for point in detection.polygon) for axis in (0, 1))
        x1, y1 = (max(point[axis] for point in detection.polygon) for axis in (0, 1))
        boxes.append(
            OcrTextBox(
                text=detection.text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                confidence=detection.confidence,
                polygon=detection.polygon,
            )
        )
    return boxes
