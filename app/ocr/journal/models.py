"""监理日志识别链的数据结构：只描述阶段之间的输入输出，不放算法。"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np


@dataclass(frozen=True)
class LoadedPhoto:
    """EXIF 校正后的照片；宽高为缩小前尺寸，downscale_ratio 为工作图缩放比例。"""

    bgr: np.ndarray
    gray: np.ndarray
    width: int
    height: int
    downscale_ratio: float = 1.0


@dataclass(frozen=True)
class OcrTextBox:
    """OCR 文字框，坐标为所在图像的像素坐标。"""

    text: str
    x0: float  # 左上
    y0: float
    x1: float
    y1: float  # 右下
    confidence: float
    polygon: tuple[tuple[float, float], ...] = ()

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    @property
    def area(self) -> float:
        if self.polygon:
            return max(abs(float(cv2.contourArea(np.asarray(self.polygon, np.float32)))), 1.0)
        return max((self.x1 - self.x0) * (self.y1 - self.y0), 1.0)

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


@dataclass(frozen=True)
class FieldLayout:
    """字段及标签均以table左上角为原点、宽高为单位，使用u/v/w/h。"""

    key: str
    label: str
    rect_in_table: tuple[float, float, float, float]
    kind: Literal["text", "date"] = "text"
    aliases: tuple[str, ...] = ()
    label_rect_in_table: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class CanvasAlignment:
    """校正画布与来源覆盖；四角坐标相对于 EXIF 校正后、缩小前的照片。"""

    canvas: np.ndarray
    table_quad_in_photo: np.ndarray
    table_rect_on_canvas: tuple[float, float, float, float]
    # 缩放后照片 → 校正画布的单应矩阵；可视化时用逆矩阵把栏目坐标画回原图。
    work_image_to_canvas: np.ndarray
    source_coverage_mask: np.ndarray
    line_support: tuple[float, ...]

    @property
    def canvas_width(self) -> int:
        return int(self.canvas.shape[1])

    @property
    def canvas_height(self) -> int:
        return int(self.canvas.shape[0])


@dataclass(frozen=True)
class ValueSegment:
    """最终栏目文本中的一个连续片段，位置相对 FieldReading.value。"""

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class FieldValue:
    """清洗后的字段原文、识别置信度与可追溯片段。"""

    text: str
    confidence: float
    segments: tuple[ValueSegment, ...] = ()


@dataclass(frozen=True)
class FieldReading:
    """单个栏目的识别结果；segments 只在需要按文字框拆分时填充。"""

    layout: FieldLayout
    boxes: tuple[OcrTextBox, ...]
    value: str
    confidence: float
    ambiguous: bool = False
    segments: tuple[ValueSegment, ...] = ()
    visible_fraction: float = 1.0


@dataclass(frozen=True)
class JournalRecognition:
    """本次照片识别结果；图像、覆盖掩码和字段均由请求拥有。"""

    photo: LoadedPhoto
    alignment: CanvasAlignment
    readings: tuple[FieldReading, ...]
    task_id: str = ""
    boxes: tuple[OcrTextBox, ...] = ()
