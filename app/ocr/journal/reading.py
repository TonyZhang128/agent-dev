"""识别一层：只在模型边界处适配 RapidOCR 输出，不含业务规则。"""

import numpy as np

from app.ocr.core.engine import ocr
from app.ocr.journal.types import TextBox


def read_boxes(image: np.ndarray) -> list[TextBox]:
    """整页或栏目裁剪图 → 文字框；模型异常由 engine 原样上抛。"""
    boxes: list[TextBox] = []
    for item in ocr(image):
        text = str(item.get("s") or "")
        if not text.strip():
            continue
        x0, y0, x1, y1 = (float(value) for value in item["box"])
        boxes.append(
            TextBox(
                text=text,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                conf=min(max(float(item.get("conf", 0.0)), 0.0), 1.0),
            )
        )
    return boxes
