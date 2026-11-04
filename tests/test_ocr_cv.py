"""app.ocr.cv 二值化与扫线的回归：框线留得下、文字留不下。"""

import cv2
import numpy as np

from app.ocr.core.cv import binarize, line_mask


def test_binarize_makes_dark_foreground_white():
    gray = np.full((60, 60), 255, np.uint8)
    cv2.line(gray, (5, 30), (55, 30), 0, 2)
    bw = binarize(gray)
    assert bw[30, 5] == 255  # 黑线 → 白前景
    assert bw[0, 0] == 0  # 白底 → 黑


def test_line_mask_keeps_rules_drops_text():
    img = np.full((200, 400), 255, np.uint8)
    cv2.line(img, (20, 50), (380, 50), 0, 2)  # 横框线(贯穿表宽)
    cv2.line(img, (100, 20), (100, 180), 0, 2)  # 竖框线
    cv2.putText(img, "Item", (150, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 0, 1)  # 印刷字
    mask = line_mask(binarize(img), 40, 25)
    assert mask[50, 200] > 0  # 横线留得下
    assert mask[100, 100] > 0  # 竖线留得下
    # 文字区域(避开横竖线及其膨胀)应基本干净
    assert not np.any(mask[95:130, 140:240] > 0)
