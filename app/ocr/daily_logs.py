"""监理日志（JLB13）照片识别 → 原始栏目文本 + 后处理占位。

与现场简表共用「找外框 → 透视校正 → 逐格 OCR」的识别链路：
  1. 轮廓:照片里找纸/表格外框；找不到就整张照片当外框
  2. 定位:按 JLB13 表样把表格外框校正到页面比例坐标，再按固定栏目裁格
  3. 取值:每个栏目单独 OCR，去掉印的栏目名；日期栏归一成 yyyy-mm-dd
监理日志的栏目是整段长文本，业务整理规则与简表逐格回填不同，先由
`process()` 占位；接口当前返回识别草稿，由业务端 / App 人工核对。
"""

from pathlib import Path

import numpy as np

from app.ocr.core.media import load_image
from app.ocr.core.sheet_scan import scan

CODE = "JLB13"
NAME = "监理日志"
W = 1000
PAGE_ASPECT = 841.9 / 595.3  # JLB13 表样为 A4 竖版
# JLB13 表格外框在页面中的比例位置（x0, y0, x1, y1），用于把照片上的表格锚回整页。
TABLE = (0.1417, 0.2011, 0.9180, 0.8124)
TABLE_ASPECT = (TABLE[3] - TABLE[1]) * PAGE_ASPECT / (TABLE[2] - TABLE[0])

# 栏目 rect 为整页比例坐标；长文本栏保留整块区域，由 OCR 一次识别。
LAYOUT = (
    {
        "field": "project",
        "label": "公路工程项目",
        "rect": [0.366, 0.060, 0.165, 0.025],
    },
    {
        "field": "number",
        "label": "编号",
        "rect": [0.745, 0.135, 0.126, 0.025],
    },
    {
        "field": "supervision_org",
        "label": "监理机构",
        "rect": [0.2893, 0.2025, 0.6257, 0.0419],
    },
    {
        "field": "recorder",
        "label": "记录人",
        "rect": [0.2893, 0.2460, 0.2964, 0.0318],
    },
    {
        "field": "date",
        "label": "日期",
        "rect": [0.6986, 0.2460, 0.2164, 0.0318],
        "type": "date",
    },
    {
        "field": "reviewer",
        "label": "审核人",
        "rect": [0.2893, 0.2798, 0.2964, 0.0288],
    },
    {
        "field": "weather",
        "label": "天气情况",
        "rect": [0.6986, 0.2798, 0.2164, 0.0288],
    },
    {
        "field": "construction",
        "label": "主要施工情况",
        "rect": [0.2893, 0.3106, 0.6257, 0.2354],
    },
    {
        "field": "supervision_work",
        "label": "监理主要工作",
        "rect": [0.2893, 0.5480, 0.6257, 0.1318],
    },
    {
        "field": "issues",
        "label": "问题及处理情况",
        "rect": [0.2893, 0.6813, 0.6257, 0.1298],
    },
)


def _destination(quad: np.ndarray, how: str) -> tuple:
    """外框 → (整页画布上的目标四角, 输出尺寸)。

    找到表格内框时直接锚到 JLB13 的表格位置；只有纸/整张照片时按长宽比判断
    它更像整页还是更像表格，避免把整页照片当表格裁掉页眉页脚。
    """
    height = round(W * PAGE_ASPECT)
    if not how.endswith("+table"):
        width = np.linalg.norm(quad[1] - quad[0])
        frame_aspect = np.linalg.norm(quad[3] - quad[0]) / width if width else PAGE_ASPECT
        if abs(frame_aspect - TABLE_ASPECT) < abs(frame_aspect - PAGE_ASPECT):
            x0, y0, x1, y1 = TABLE
        else:
            x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    else:
        x0, y0, x1, y1 = TABLE
    dst = np.array(
        [
            [x0 * W, y0 * height],
            [x1 * W, y0 * height],
            [x1 * W, y1 * height],
            [x0 * W, y1 * height],
        ],
        np.float32,
    )
    return dst, (W, height)


def process(recognized: dict, detail: list[dict]) -> dict:
    """监理日志识别结果的后处理（待实现）。

    监理日志与简表结构不同：栏目是整段长文本、日期栏印着「年月日」，需要按
    日志结构整理而不是逐格回填目标表。该函数先占位；调用方目前应直接使用
    `recognized` 和 `detail` 的原始识别结果。
    """
    return {}


def run(photo: Path | None, img: str = "") -> dict:
    """识别监理日志照片；照片路径与 base64 图片至少提供一个，同时提供时优先用 base64。"""
    image = load_image(photo, img)
    _sheet, quad, how, recognized, detail = scan(image, list(LAYOUT), _destination)
    height, width = image.shape[:2]
    return {
        "form": CODE,
        "formName": NAME,
        "frame": {"how": how, "quad": quad.round().astype(int).tolist()},
        "recognized": recognized,
        "detail": detail,
        "processed": process(recognized, detail),
        "warning": "未检测到表格外框，按整张照片校正，请核对定位" if how == "whole" else "",
        "image": {"width": width, "height": height},
    }
