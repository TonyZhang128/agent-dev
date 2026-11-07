"""监理日志识别链的数据结构：只描述阶段之间的输入输出，不放算法。"""

from dataclasses import dataclass
from typing import Literal

import numpy as np

# 页面定位各阶段共用的取值，避免退化为任意字符串。
type LocationKind = Literal["table", "page", "whole"]


@dataclass(frozen=True)
class Photo:
    """读入后的照片；bgr/gray 可能按输入上限缩小，scale 用于把坐标换回原图。"""

    bgr: np.ndarray
    gray: np.ndarray
    width: int
    height: int
    scale: float = 1.0


@dataclass(frozen=True)
class TextBox:
    """OCR 文字框，坐标为所在图像的像素坐标。"""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2

    @property
    def area(self) -> float:
        return max((self.x1 - self.x0) * (self.y1 - self.y0), 1.0)

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)


@dataclass(frozen=True)
class FieldSpec:
    """一个固定栏目的版式定义；rect 为页面比例坐标 x/y/w/h。"""

    key: str
    label: str
    rect: tuple[float, float, float, float]
    kind: Literal["text", "date"] = "text"
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PageLocation:
    """校正后的整页图及其在原图中的位置。"""

    sheet: np.ndarray
    quad: np.ndarray
    kind: LocationKind
    how: str
    width: int
    height: int
    # 缩放后照片 → 校正画布的单应矩阵；可视化时用逆矩阵把栏目坐标画回原图。
    matrix: np.ndarray | None = None


@dataclass(frozen=True)
class TextSegment:
    """最终栏目文本中的一个连续片段，位置相对 FieldReading.value。"""

    text: str
    start: int
    end: int


@dataclass(frozen=True)
class FieldReading:
    """单个栏目的识别结果；segments 只在需要按文字框拆分时填充。"""

    spec: FieldSpec
    boxes: tuple[TextBox, ...]
    value: str
    conf: float
    ambiguous: bool = False
    segments: tuple[TextSegment, ...] = ()
