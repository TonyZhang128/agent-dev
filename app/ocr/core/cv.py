"""OpenCV 基础操作：自适应二值化与横竖框线提取(扫线)。

grid / sheet_scan 的框线处理共用这里的实现；二值化阈值与结构核尺寸
由调用方按场景给定(表样 PDF 渲染图用固定阈值，拍照件用自适应阈值)。
前景约定：线条、文字等暗色笔画为 255，背景为 0。
"""

import cv2
import numpy as np


def binarize(gray, block: int = 25, c: int = 10):
    """灰度图 → 前景为白的自适应阈值图。

    局部均值阈值适应拍照件的光照不均，BINARY_INV 使暗线条、暗文字成为白色
    前景，亮背景成为黑色。block/c 透传给 cv2.adaptiveThreshold。
    """
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, c
    )


def line_mask(bw, kw: int, kh: int):
    """横竖框线掩码：横线核 (kw,1) 与竖线核 (1,kh) 的开运算合并后膨胀 3×3。

    开运算只保留容纳得下细长核的连续笔画，文字和短笔画被滤除；膨胀把断开的
    线接回成封闭格。kw/kh 是线长下限：贯穿表宽/表高的框线才留得下。
    """
    lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (kw, 1)))
    lines |= cv2.morphologyEx(
        bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, kh))
    )
    return cv2.dilate(lines, np.ones((3, 3), np.uint8))
