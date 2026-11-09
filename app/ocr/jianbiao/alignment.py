"""简表表格核验、直角旋转与透视校正。"""

from dataclasses import replace

import cv2
import numpy as np

from app.errors import JianbiaoFrameNotFound, JournalFrameNotFound
from app.ocr.jianbiao.models import CanvasAlignment
from app.ocr.jianbiao.template import JianbiaoTemplate
from app.ocr.journal.table_detection import detect_table

TABLE_MIN_WIDTH = 1000
TABLE_MAX_WIDTH = 1800
CANVAS_MAX_SIDE = 2600
CANVAS_PADDING_IN_TABLE = 0.03


def canvas_extent_in_table(template: JianbiaoTemplate) -> tuple[float, float, float, float]:
    """画布覆盖表格和全部表外字段，不依赖纸张边缘。"""
    regions = [(0.0, 0.0, 1.0, 1.0)]
    for field in template.fields:
        regions.append(field.rect_in_table)
        if field.label_rect_in_table is not None:
            regions.append(field.label_rect_in_table)
    padding = CANVAS_PADDING_IN_TABLE
    return (
        min(rect[0] for rect in regions) - padding,
        min(rect[1] for rect in regions) - padding,
        max(rect[0] + rect[2] for rect in regions) + padding,
        max(rect[1] + rect[3] for rect in regions) + padding,
    )


def align_canvas(image: np.ndarray, template: JianbiaoTemplate) -> CanvasAlignment:
    """依次尝试原向和三个直角方向，只有通过模板核验的方向才能进入 OCR。"""
    last_error: JianbiaoFrameNotFound | None = None
    rotations = (
        None,
        cv2.ROTATE_90_COUNTERCLOCKWISE,
        cv2.ROTATE_90_CLOCKWISE,
        cv2.ROTATE_180,
    )
    for rotation in rotations:
        oriented = image if rotation is None else cv2.rotate(image, rotation)
        try:
            alignment = _align_oriented(oriented, template)
        except JianbiaoFrameNotFound as exc:
            last_error = exc
            continue
        if rotation is None:
            return alignment
        corners = _corners_in_original(
            alignment.table_quad_in_photo,
            rotation,
            original_size=(image.shape[1], image.shape[0]),
        )
        return replace(alignment, table_quad_in_photo=corners)
    raise JianbiaoFrameNotFound("未检测到与模板匹配的简表表格") from last_error


def _align_oriented(image: np.ndarray, template: JianbiaoTemplate) -> CanvasAlignment:
    """在单个候选方向上执行结构核验和透视校正。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    try:
        match = detect_table(gray, template, aspect_range=template.aspect_range)
    except JournalFrameNotFound as exc:
        raise JianbiaoFrameNotFound("未检测到与模板匹配的简表表格") from exc
    table_width = (
        np.linalg.norm(match.corners[1] - match.corners[0])
        + np.linalg.norm(match.corners[2] - match.corners[3])
    ) / 2
    table_width = float(np.clip(table_width, TABLE_MIN_WIDTH, TABLE_MAX_WIDTH))
    left, top, right, bottom = canvas_extent_in_table(template)
    width = table_width * (right - left)
    height = table_width * template.height_aspect * (bottom - top)
    scale = min(1.0, CANVAS_MAX_SIDE / max(width, height))
    canvas_size = (round(width * scale), round(height * scale))
    placement = (
        -left / (right - left),
        -top / (bottom - top),
        (1 - left) / (right - left),
        (1 - top) / (bottom - top),
    )
    destination = np.array(
        [
            [placement[0], placement[1]],
            [placement[2], placement[1]],
            [placement[2], placement[3]],
            [placement[0], placement[3]],
        ],
        np.float32,
    )
    destination *= np.asarray(canvas_size, np.float32)
    matrix = cv2.getPerspectiveTransform(match.corners.astype(np.float32), destination)
    canvas = cv2.warpPerspective(
        image, matrix, canvas_size, flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255)
    )
    return CanvasAlignment(
        canvas=canvas,
        table_quad_in_photo=match.corners,
        table_rect_on_canvas=placement,
        line_support=match.line_support,
    )


def _corners_in_original(
    corners: np.ndarray,
    rotation: int,
    original_size: tuple[int, int],
) -> np.ndarray:
    """将旋转候选图上的四角逆变换到原始照片，供覆盖图和诊断使用。"""
    width, height = original_size
    if rotation == cv2.ROTATE_90_COUNTERCLOCKWISE:
        matrix = np.array([[0, -1, width - 1], [1, 0, 0], [0, 0, 1]], np.float32)
    elif rotation == cv2.ROTATE_90_CLOCKWISE:
        matrix = np.array([[0, 1, 0], [-1, 0, height - 1], [0, 0, 1]], np.float32)
    elif rotation == cv2.ROTATE_180:
        matrix = np.array([[-1, 0, width - 1], [0, -1, height - 1], [0, 0, 1]], np.float32)
    else:
        raise ValueError("不支持的简表旋转方向")
    return cv2.perspectiveTransform(corners.reshape(1, -1, 2).astype(np.float32), matrix)[0]
