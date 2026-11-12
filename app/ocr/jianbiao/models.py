"""简表识别各阶段的请求内数据结构。"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OcrTextBox:
    """OCR 文字及其画布坐标。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float
    polygon: tuple[tuple[float, float], ...] = ()

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


@dataclass(frozen=True)
class FieldReading:
    """单个简表字段的识别结果。"""

    key: str
    value: str
    confidence: float
    ambiguous: bool = False


@dataclass(frozen=True)
class CanvasAlignment:
    """透视校正后的画布及表格定位证据。"""

    canvas: np.ndarray
    table_quad_in_photo: np.ndarray
    table_rect_on_canvas: tuple[float, float, float, float]
    line_support: tuple[float, ...]


@dataclass(frozen=True)
class JianbiaoRecognition:
    """简表原值、逐字段诊断和本次任务标识。"""

    source_template_id: str
    values: dict[str, str]
    readings: tuple[FieldReading, ...]
    alignment: CanvasAlignment
    task_id: str = ""
