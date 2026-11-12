"""以已验证table为唯一锚点建立画布，保留表外字段；不提供纸张/整图回退。"""

import cv2
import numpy as np

from app.ocr.journal.models import CanvasAlignment, LoadedPhoto
from app.ocr.journal.table_detection import detect_table
from app.ocr.journal.template import JournalTemplate, load_template

TABLE_MIN_WIDTH = 1000
TABLE_MAX_WIDTH = 1800
CANVAS_MAX_SIDE = 2600
CANVAS_PADDING_IN_TABLE = 0.03


def canvas_extent_in_table(template: JournalTemplate) -> tuple[float, float, float, float]:
    """画布范围由table和表外字段并集决定，与PDF纸张大小无关。"""
    regions = [(0.0, 0.0, 1.0, 1.0)]
    for field in template.fields:
        regions.extend((field.rect_in_table, field.label_rect_in_table))
    padding = CANVAS_PADDING_IN_TABLE
    return (
        min(rect[0] for rect in regions) - padding,
        min(rect[1] for rect in regions) - padding,
        max(rect[0] + rect[2] for rect in regions) + padding,
        max(rect[1] + rect[3] for rect in regions) + padding,
    )


def table_rect_on_canvas(template: JournalTemplate) -> tuple[float, float, float, float]:
    """将table本身映射到画布，返回归一化x0/y0/x1/y1。"""
    left, top, right, bottom = canvas_extent_in_table(template)
    return (
        -left / (right - left),
        -top / (bottom - top),
        (1 - left) / (right - left),
        (1 - top) / (bottom - top),
    )


def align_canvas(photo: LoadedPhoto) -> CanvasAlignment:
    """只接受通过模板拓扑核验的table；失败异常发生在OCR之前。"""
    template = load_template()
    match = detect_table(photo.gray, template)  # 检测table
    table_width = (
        np.linalg.norm(match.corners[1] - match.corners[0])
        + np.linalg.norm(match.corners[2] - match.corners[3])
    ) / 2
    table_width = float(np.clip(table_width, TABLE_MIN_WIDTH, TABLE_MAX_WIDTH))
    left, top, right, bottom = canvas_extent_in_table(template)  # 由table与表外字段并集决定画布范围
    width = table_width * (right - left)
    height = table_width * template.table_aspect * (bottom - top)
    scale = min(1.0, CANVAS_MAX_SIDE / max(width, height))
    canvas_size = (round(width * scale), round(height * scale))
    tx0, ty0, tx1, ty1 = placement = table_rect_on_canvas(template)
    destination = np.array([[tx0, ty0], [tx1, ty0], [tx1, ty1], [tx0, ty1]], dtype=np.float32)
    destination *= np.asarray(canvas_size, np.float32)
    matrix = cv2.getPerspectiveTransform(match.corners.astype(np.float32), destination)
    canvas = cv2.warpPerspective(
        photo.bgr, matrix, canvas_size, flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255)
    )
    coverage = cv2.warpPerspective(
        np.full(photo.gray.shape, 255, np.uint8),
        matrix,
        canvas_size,
        flags=cv2.INTER_NEAREST,
        borderValue=0,
    )
    return CanvasAlignment(
        canvas=canvas,
        table_quad_in_photo=match.corners / photo.downscale_ratio,
        table_rect_on_canvas=placement,
        work_image_to_canvas=matrix,
        source_coverage_mask=coverage,
        line_support=match.line_support,
    )
