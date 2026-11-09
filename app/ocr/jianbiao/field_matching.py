"""将单次整页 OCR 的文字框归属到简表字段。"""

import re
from datetime import date

import cv2
import numpy as np

from app.ocr.jianbiao.models import FieldReading, OcrTextBox
from app.ocr.jianbiao.template import JianbiaoTemplate, TemplateField

MATCH_COVERAGE_MIN = 0.5
MATCH_SECONDARY_COVERAGE_MIN = 0.4
MATCH_COVERAGE_GAP_MIN = 0.1
_DATE_PATTERN = re.compile(r"(20\d{2})\s*[年.\-/\s]\s*(\d{1,2})\s*[月.\-/\s]\s*(\d{1,2})")
_DATE_COMPACT = re.compile(r"\s*(20\d{2})(\d{2})(\d{2})\s*")


def bounds_on_canvas(
    rect_in_table: tuple[float, float, float, float],
    canvas_size: tuple[int, int],
    table_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """把表格相对坐标换算到当前校正画布。"""
    width, height = canvas_size
    tx0, ty0, tx1, ty1 = table_rect
    table_width = (tx1 - tx0) * width
    table_height = (ty1 - ty0) * height
    u, v, field_width, field_height = rect_in_table
    return (
        tx0 * width + u * table_width,
        ty0 * height + v * table_height,
        tx0 * width + (u + field_width) * table_width,
        ty0 * height + (v + field_height) * table_height,
    )


def extract_fields(
    canvas: np.ndarray,
    template: JianbiaoTemplate,
    table_rect: tuple[float, float, float, float],
    boxes: list[OcrTextBox],
) -> list[FieldReading]:
    """按中心点和覆盖率分配；前两名接近的跨栏文字标记歧义并清空。"""
    canvas_size = (canvas.shape[1], canvas.shape[0])
    fields = template.fields
    groups: dict[str, list[OcrTextBox]] = {field.key: [] for field in fields}
    ambiguous: set[str] = set()
    for box in boxes:
        scored: list[tuple[float, float, str, bool]] = []
        for field in fields:
            bounds = bounds_on_canvas(field.rect_in_table, canvas_size, table_rect)
            coverage = _coverage(box, bounds)
            x0, y0, x1, y1 = bounds
            center_x, center_y = box.center
            center_in = x0 <= center_x <= x1 and y0 <= center_y <= y1
            if not center_in and coverage < MATCH_SECONDARY_COVERAGE_MIN:
                continue
            if center_in and coverage <= 0:
                continue
            score = (3.0 if center_in else 0.0) + 2.0 * coverage
            scored.append((score, coverage, field.key, center_in))
        if not scored:
            continue
        scored.sort(reverse=True)
        _score, coverage, key, center_in = scored[0]
        if len(scored) > 1:
            _second_score, second_coverage, second_key, _second_center = scored[1]
            if (
                abs(coverage - second_coverage) <= MATCH_COVERAGE_GAP_MIN
                and second_coverage >= MATCH_SECONDARY_COVERAGE_MIN
            ):
                ambiguous.update((key, second_key))
                continue
        if not center_in and coverage < MATCH_COVERAGE_MIN:
            continue
        groups[key].append(box)
    readings: list[FieldReading] = []
    for field in fields:
        if field.key in ambiguous:
            readings.append(FieldReading(field.key, "", 0.0, ambiguous=True))
        else:
            readings.append(_reading(field, groups[field.key]))
    return readings


def _coverage(box: OcrTextBox, bounds: tuple[float, float, float, float]) -> float:
    if box.area <= 0:
        return 0.0
    x0, y0, x1, y1 = bounds
    if box.polygon:
        polygon = np.asarray(box.polygon, np.float32)
        region = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)
        area, _ = cv2.intersectConvexConvex(polygon, region)
        return max(float(area), 0.0) / box.area
    width = max(0.0, min(box.x1, x1) - max(box.x0, x0))
    height = max(0.0, min(box.y1, y1) - max(box.y0, y0))
    return width * height / box.area


def _reading(field: TemplateField, boxes: list[OcrTextBox]) -> FieldReading:
    ordered = sorted(boxes, key=lambda box: (round(box.center[1] / 12), box.x0))
    text = _remove_layout_whitespace("".join(box.text for box in ordered))
    text = _strip_printed_labels(text, field)
    text = re.sub(r"^[\s:：_＿·•\-—]+", "", text)
    if field.kind == "date":
        text = _normalize_date(text)
    confidence = round(sum(box.confidence for box in ordered) / len(ordered), 3) if ordered else 0.0
    return FieldReading(field.key, text, confidence)


def _remove_layout_whitespace(text: str) -> str:
    """去掉排版空白，但保留数字与英文单位之间有语义的空格。"""
    return re.sub(r"(?<!\d)\s+|\s+(?![A-Za-z])", "", text)


def _strip_printed_labels(text: str, field: TemplateField) -> str:
    """循环剥离英文标注键、印刷栏目名和行占位符，保留其后的真实值。"""
    labels = sorted({field.key, field.label, *field.aliases} - {""}, key=len, reverse=True)
    remaining = text
    while remaining:
        for label in labels:
            if remaining.startswith(label):
                remaining = remaining[len(label) :].lstrip(" :：_＿·•-—")
                break
        else:
            break
    return remaining


def _normalize_date(text: str) -> str:
    match = _DATE_PATTERN.search(text) or _DATE_COMPACT.fullmatch(text)
    if not match:
        return text
    year, month, day = (int(value) for value in match.groups())
    try:
        date(year, month, day)
    except ValueError:
        return text
    return f"{year}-{month:02d}-{day:02d}"
