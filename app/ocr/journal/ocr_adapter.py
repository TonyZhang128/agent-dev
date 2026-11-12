"""识别一层：只在模型边界处适配 RapidOCR 输出，不含业务规则。"""

import numpy as np

from app.ocr.core.engine import detect_text
from app.ocr.journal.models import OcrTextBox


def detect_text_boxes(image: np.ndarray) -> list[OcrTextBox]:
    """整页或栏目裁剪图 → 文字框；模型异常由 engine 原样上抛。"""
    boxes: list[OcrTextBox] = []
    for detection in detect_text(image):
        text = detection.text
        x0, y0 = (min(point[axis] for point in detection.polygon) for axis in (0, 1))
        x1, y1 = (max(point[axis] for point in detection.polygon) for axis in (0, 1))
        boxes.append(
            OcrTextBox(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                confidence=detection.confidence,
                polygon=detection.polygon,
            )
        )
    return boxes
