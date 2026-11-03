"""照片表格按配置格子的识别链：找纸/表格外框 → 透视校正 → 逐格 OCR 取值。

不含任何表种数据：格子配置（cells）与校正目标（destination）由调用方给定——
简表（jianbiao/recognize 的 _frame_dst + layouts/jianbiao.json）和监理日志
（daily_logs 的 _destination + LAYOUT）各自喂自己的配置，复用同一条链。
OCR 引擎在 core/engine；读图与文字层原语在 core/media。
"""

import re

import cv2
import numpy as np

from app.ocr.core.cv import binarize, line_mask
from app.ocr.core.engine import ocr
from app.ocr.core.media import date_value

W = 1000  # 归一化画布默认宽度(像素);实际宽度由 destination 返回,经 scan 显式传给 read_cells


# ───────── 轮廓:找外框 ─────────


def _order(pts: np.ndarray) -> np.ndarray:
    """四个角排成 左上、右上、右下、左下"""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32
    )


def find_frame(img) -> tuple[np.ndarray, str]:
    """面积最大、占照片 ≥ 20% 的四边形;返回 (四角, how)"""
    h, w = img.shape[:2]
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    bw = binarize(g, 25, 10)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))  # 补上手机拍照断开的框线
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < 0.2 * w * h:
            break
        q = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(q) == 4 and cv2.isContourConvex(q):
            return _order(q.reshape(4, 2).astype(np.float32)), "contour"
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32), "whole"


def find_table(img) -> tuple[np.ndarray, str]:
    """先找纸(照片里最大的四边形),校正后在纸里再找表格外框(粗黑框):格子坐标是相对表格外框的。
    返回照片上表格外框的四角;纸里找不到外框就用纸的四角。"""
    paper, how = find_frame(img)
    pw = round(np.linalg.norm(paper[1] - paper[0]))
    ph = round(np.linalg.norm(paper[3] - paper[0]))
    if pw < 50 or ph < 50:
        return paper, how
    M = cv2.getPerspectiveTransform(
        paper, np.array([[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]], np.float32)
    )
    flat = cv2.warpPerspective(img, M, (pw, ph))
    m = max(4, round(min(pw, ph) * 0.01))  # 去掉纸边一圈,纸边本身也是一个四边形
    inner, ihow = find_frame(flat[m : ph - m, m : pw - m])
    if ihow != "contour":
        return paper, how
    back = cv2.perspectiveTransform((inner + m).reshape(1, 4, 2), np.linalg.inv(M)).reshape(4, 2)
    return back.astype(np.float32), how + "+table"


# ───────── 定位 + 逐格取值 ─────────


def scan(image, cells: list[dict], destination) -> tuple:
    """照片 → 找表格外框 → 透视校正 → 逐格 OCR 的共用识别链。

    destination(quad, how) 返回 (目标四角, 输出尺寸):简表锚到宽 W、高 W×aspect
    的表框画布(格子坐标是框内比例),监理日志锚回整页画布(栏目坐标是整页比例)。
    画布宽 size[0] 显式传给 read_cells,保证格子比例换算与校正输出一致。
    返回 (校正图, 外框四角, how, 识别值, 逐格明细)。"""
    quad, how = find_table(image)
    dst, size = destination(quad, how)
    sheet = cv2.warpPerspective(image, cv2.getPerspectiveTransform(quad, dst), size)
    recognized, detail = read_cells(sheet, cells, size[0])
    return sheet, quad, how, recognized, detail


def _dedup(boxes: list[dict]) -> list[dict]:
    """OCR 偶尔把同一个字再单独认一遍(「97.1」后面又跟一个「1」,框压在「97.1」的框里):被大框盖住大半的小框去掉"""

    def inside(a, b):
        ax0, ay0, ax1, ay1 = a["box"]
        bx0, by0, bx1, by1 = b["box"]
        iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
        return iw * ih > 0.5 * (ax1 - ax0) * (ay1 - ay0)

    area = lambda b: (b["box"][2] - b["box"][0]) * (b["box"][3] - b["box"][1])  # noqa: E731
    return [
        a
        for a in boxes
        if not any(b is not a and area(b) > area(a) and inside(a, b) for b in boxes)
    ]


def _cell_value(boxes: list[dict], label: str, typ: str) -> tuple[str, float]:
    """格子里认出的字 → 值:去掉印的栏目名;数字栏只取数字"""
    boxes = _dedup(boxes)
    lab = re.sub(r"\s", "", label)
    # 印的栏目名在格子左上角(小字、单独一个框),整框就是栏目名(或它的后半截:裁格子时头一两个字可能被裁掉)的去掉
    boxes = [
        b
        for b in boxes
        if not (
            lab
            and re.sub(r"\s", "", b["s"])
            and lab.endswith(re.sub(r"\s", "", b["s"]))
            and (len(re.sub(r"\s", "", b["s"])) >= 2 or lab.isdigit())
        )
    ]
    boxes = sorted(boxes, key=lambda b: (round(b["box"][1] / 12), b["box"][0]))
    text = re.sub(r"\s", "", " ".join(b["s"] for b in boxes))
    # 栏目名和填的字 OCR 连成一个框时:按「栏目名的后缀」去掉;印刷字被认错一个字(处理→里)时按后 2 个字去
    for k in range(len(lab)):
        if len(lab) - k >= 2 and text.startswith(lab[k:]):
            text = text[len(lab) - k :]
            break
    else:
        i = text.find(lab[-2:]) if len(lab) >= 3 else -1
        if 0 <= i <= 2:
            text = text[i + 2 :]
    text = re.sub(r"^[:：_＿]+", "", text)
    conf = round(sum(b["conf"] for b in boxes) / len(boxes), 3) if boxes else 0.0
    if typ == "number":
        text = re.sub(r"[一—－–](?=\d)", "-", text)  # 手写的负号常被认成「一」
        m = re.findall(r"-?\d+(?:\.\d+)?", text)
        return (m[-1] if m else ""), conf  # 格子左上角印的点号(1~5)在前,手写的数在后
    if typ == "date":
        return date_value(text), conf
    return text, conf


def _erase_lines(crop):
    """格子边上残留的框线(校正有一两个像素偏差时会裁进来)涂白,免得被认成「1」或「一」:
    横线 = 宽度过半的横向连续黑段,竖线 = 高度过半的竖向连续黑段"""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bw = binarize(g, 21, 12)
    h, w = bw.shape
    out = crop.copy()
    out[line_mask(bw, max(10, w // 2), max(10, h // 2)) > 0] = 255
    return out


def read_cells(sheet, cells: list[dict], width: int = W) -> tuple[dict, list[dict]]:
    """每个格子单独 OCR(往里收 4%,避开框线);width 是校正画布的宽(格子 x 比例 × width)"""
    H = sheet.shape[0]
    values, detail = {}, []
    for c in cells:
        if not c.get("field"):  # 表上印好的检查项目名,不识别
            continue
        x, y, w, h = c["rect"]
        x0, y0 = int((x + w * 0.04) * width), int((y + h * 0.04) * H)
        x1, y1 = int((x + w * 0.96) * width), int((y + h * 0.96) * H)
        crop = sheet[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop = _erase_lines(crop)
        crop = cv2.copyMakeBorder(
            crop, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=(255, 255, 255)
        )  # OCR 对贴边的字不敏感
        val, conf = _cell_value(ocr(crop), c.get("label", ""), c.get("type", ""))
        if val:
            values[c["field"]] = val
        detail.append(
            {
                "field": c["field"],
                "label": c.get("label", ""),
                "value": val,
                "conf": conf,
                "rect": [x0, y0, x1, y1],
            }
        )
    return values, detail
