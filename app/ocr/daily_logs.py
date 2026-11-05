"""监理日志（JLB13）照片识别 → 原始栏目文本 + 业务结构。

与现场简表共用「找外框 → 透视校正 → 逐格 OCR」的识别链路：
  1. 轮廓:照片里找纸/表格外框；找不到就整张照片当外框
  2. 定位:按现场《监理日记》表样把表格外框校正到页面比例坐标，再按固定栏目裁格
  3. 取值:每个栏目单独 OCR，去掉印的栏目名；日期栏归一成 yyyy-mm-dd
  4. 整理:process() 把栏目文本映射成业务结构（documentType/common/fields）
监理日志的栏目是整段长文本，业务整理规则与简表逐格回填不同；识别结果仍需人工核对。
"""

from pathlib import Path

import numpy as np

from app.ocr.core.media import load_image
from app.ocr.core.sheet_scan import scan

CODE = "JLB13"
NAME = "监理日志"
DOCUMENT_TYPE = "supervision_diary"
W = 1000
PAGE_ASPECT = 841.9 / 595.3  # 表样为 A4 竖版
# 表格外框在页面中的比例位置（x0, y0, x1, y1），用于把照片上的表格锚回整页。
TABLE = (0.112, 0.227, 0.886, 0.888)
TABLE_ASPECT = (TABLE[3] - TABLE[1]) * PAGE_ASPECT / (TABLE[2] - TABLE[0])

# 栏目 rect 为整页比例坐标；长文本栏保留整块区域，由 OCR 一次识别。
# inset=0 时整格识别，单元格框线由 read_cells 的 _erase_lines 擦除；手写内容常顶到格边。
LAYOUT = (
    {
        "field": "project",
        "label": "公路工程项目",
        "rect": [0.300, 0.130, 0.280, 0.035],
        "inset": 0.0,
    },
    {
        "field": "number",
        "label": "编号",
        "rect": [0.800, 0.205, 0.090, 0.027],
        "inset": 0.0,
    },
    {
        "field": "supervision_org",
        "label": "监理机构",
        "rect": [0.248, 0.227, 0.638, 0.058],
        "inset": 0.0,
    },
    {
        "field": "recorder",
        "label": "记录人",
        "rect": [0.248, 0.285, 0.332, 0.053],
        "inset": 0.0,
    },
    {
        "field": "weather",
        "label": "天气",
        "rect": [0.740, 0.285, 0.146, 0.053],
        "inset": 0.0,
    },
    {
        "field": "position",
        "label": "岗位",
        "rect": [0.248, 0.338, 0.332, 0.060],
        "inset": 0.0,
    },
    {
        "field": "date",
        "label": "记录时间",
        "rect": [0.740, 0.338, 0.146, 0.060],
        "type": "date",
        "inset": 0.0,
    },
    {
        "field": "reviewer",
        "label": "审核人",
        "rect": [0.752, 0.888, 0.138, 0.030],
        "inset": 0.0,
    },
    {
        "field": "construction",
        "label": "主要施工情况",
        "rect": [0.248, 0.398, 0.638, 0.082],
        "inset": 0.0,
    },
    {
        "field": "witness",
        "label": "旁站情况",
        "rect": [0.248, 0.480, 0.638, 0.101],
        "inset": 0.0,
    },
    {
        "field": "patrol",
        "label": "巡视情况",
        "rect": [0.248, 0.581, 0.638, 0.056],
        "inset": 0.0,
    },
    {
        "field": "issues",
        "label": "发现的问题及处理结果",
        "rect": [0.248, 0.637, 0.638, 0.130],
        "inset": 0.0,
    },
    {
        "field": "next_day_plan",
        "label": "次日工作计划和管控重点",
        "rect": [0.248, 0.767, 0.638, 0.121],
        "inset": 0.0,
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


def process(recognized: dict, detail: list[dict], task_id: str = "") -> dict:
    """把逐栏 OCR 结果整理成监理日记业务结构。

    只做字段映射和空值归一，不推断、不补写识别不到的内容；缺失栏目返回 None。
    `task_id` 由调用方提供并原样回显，本服务不生成任务 ID。
    """

    def text(key: str) -> str | None:
        value = (recognized.get(key) or "").strip()
        return value or None

    return {
        "taskId": task_id.strip() or None,
        "documentType": DOCUMENT_TYPE,
        "common": {
            "projectName": text("project"),
            "documentNo": text("number"),
            "supervisionOrg": text("supervision_org"),
            "recorderName": text("recorder"),
            "recorderPosition": text("position"),
            "weather": text("weather"),
            "logDate": text("date"),
            "reviewerName": text("reviewer"),
        },
        "fields": {
            "mainWork": {
                "construction": text("construction"),
                "witness": text("witness"),
                "patrol": text("patrol"),
            },
            "issues": text("issues"),
            "nextDayPlan": text("next_day_plan"),
        },
    }


def run(photo: Path | None, img: str = "", task_id: str = "") -> dict:
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
        "processed": process(recognized, detail, task_id),
        "warning": "未检测到表格外框，按整张照片校正，请核对定位" if how == "whole" else "",
        "image": {"width": width, "height": height},
    }
