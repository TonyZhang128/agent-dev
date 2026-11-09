"""整页文字框 → 栏目值：去重、归属、行合并、印刷栏目名剥离和日期归一。

匹配度量用"中心点优先 + 框内覆盖率"，不用 IoU：文本行框和整格框的
IoU 天然很低，覆盖率或中心点才是稳定的判据。
"""

import re
from collections.abc import Callable
from datetime import date

import cv2
import numpy as np

from app.ocr.journal.models import FieldLayout, FieldReading, FieldValue, OcrTextBox, ValueSegment
from app.ocr.journal.ocr_adapter import detect_text_boxes

Reader = Callable[[np.ndarray], list[OcrTextBox]]

_LABEL_NOISE = re.compile(r"[\s:：_＿□☐\-—()（）《》〈〉\[\]【】]+")

# 容许像素舍入及细线边缘误差；明显缺失的区域不能当作拍摄到的空栏。
MIN_VISIBLE_FRACTION = 0.98
MATCH_COVERAGE_MIN = 0.5
MATCH_CENTER_MARGIN = 0.002
# 接近均分的跨栏框应稳定拒绝，不因中心点的亚像素变化改变归属。
MATCH_SECONDARY_COVERAGE_MIN = 0.4
MATCH_COVERAGE_GAP_MIN = 0.1
SAME_LINE_HORIZONTAL_OVERLAP_MAX = 0.2


def extract_fields(
    canvas: np.ndarray,
    layouts: tuple[FieldLayout, ...],
    table_rect: tuple[float, float, float, float],
    reader: Reader = detect_text_boxes,
    *,
    valid_mask: np.ndarray | None = None,
) -> list[FieldReading]:
    """一次整页 OCR 后按栏目取值；空字段和歧义字段不触发重复识别。"""
    height, width = canvas.shape[:2]
    ocr_results = reader(canvas)
    groups, ambiguous = _assign_boxes_to_fields(ocr_results, layouts, (width, height), table_rect)
    readings: dict[str, FieldReading] = {}
    for layout in layouts:
        assigned = groups.get(layout.key, [])
        visible_fraction = _field_visible_fraction(layout, (width, height), table_rect, valid_mask)
        if visible_fraction < MIN_VISIBLE_FRACTION:
            assigned = []
            ambiguous.add(layout.key)
        field_value = _extract_field_value(layout, assigned)
        readings[layout.key] = FieldReading(
            layout=layout,
            boxes=tuple(assigned),
            value=field_value.text,
            confidence=field_value.confidence,
            ambiguous=layout.key in ambiguous,
            segments=field_value.segments,
            visible_fraction=visible_fraction,
        )

    return [readings[layout.key] for layout in layouts]


def _field_visible_fraction(
    layout: FieldLayout,
    canvas_size: tuple[int, int],
    table_rect: tuple[float, float, float, float],
    mask: np.ndarray | None,
) -> float:
    width, height = canvas_size
    if mask is None:
        return 1.0
    x0, y0, x1, y1 = (
        int(round(coordinate))
        for coordinate in field_bounds_on_canvas(layout, canvas_size, table_rect)
    )
    expected_area = max((x1 - x0) * (y1 - y0), 1)
    region = mask[max(y0, 0) : min(y1, height), max(x0, 0) : min(x1, width)]
    return min(float(np.count_nonzero(region)) / expected_area, 1.0)


def _assign_boxes_to_fields(
    boxes: list[OcrTextBox],
    layouts: tuple[FieldLayout, ...],
    canvas_size: tuple[int, int],
    table_rect: tuple[float, float, float, float],
) -> tuple[dict[str, list[OcrTextBox]], set[str]]:
    """根据OCR识别出的文字框，按照空间关系分配给预设好的栏目"""
    width, height = canvas_size
    table_width = (table_rect[2] - table_rect[0]) * width
    table_height = (table_rect[3] - table_rect[1]) * height
    groups: dict[str, list[OcrTextBox]] = {layout.key: [] for layout in layouts}
    ambiguous: set[str] = set()
    for box in _deduplicate_boxes(boxes):
        scored: list[tuple[float, float, str, bool]] = []
        for layout in layouts:
            x0, y0, x1, y1 = field_bounds_on_canvas(layout, canvas_size, table_rect)
            # OCR 可把印刷标签与填写值检测为一个框；只在确认前缀标签时扩大匹配区。
            compact_text = _remove_whitespace(box.text)
            if (
                layout.label_rect_in_table is not None
                and _strip_printed_label(compact_text, layout) != compact_text
            ):
                lx0, ly0, lx1, ly1 = bounds_on_canvas(
                    layout.label_rect_in_table, canvas_size, table_rect
                )
                x0, y0 = min(x0, lx0), min(y0, ly0)
                x1, y1 = max(x1, lx1), max(y1, ly1)
            intersection = _overlap_area(box, x0, y0, x1, y1)
            coverage = intersection / box.area
            center_x, center_y = box.center
            margin_x = MATCH_CENTER_MARGIN * table_width
            margin_y = MATCH_CENTER_MARGIN * table_height
            center_in = (
                x0 - margin_x <= center_x <= x1 + margin_x
                and y0 - margin_y <= center_y <= y1 + margin_y
            )
            if not center_in and coverage < MATCH_SECONDARY_COVERAGE_MIN:
                continue
            # 只有中心落在容差内、实际没有压到栏目区域的框（相邻栏的印刷名）
            # 不参与归属，避免把"编号："带进监理机构。
            if center_in and coverage <= 0.0:
                continue
            distance = float(
                np.hypot(
                    (center_x - (x0 + x1) / 2) / max(table_width, 1),
                    (center_y - (y0 + y1) / 2) / max(table_height, 1),
                )
            )
            score = (3.0 if center_in else 0.0) + 2.0 * coverage + 0.5 * (1.0 - min(distance, 1.0))
            scored.append((score, coverage, layout.key, center_in))
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
    return groups, ambiguous


def _extract_field_value(layout: FieldLayout, boxes: list[OcrTextBox]) -> FieldValue:
    kept = [
        box
        for box in _deduplicate_boxes(boxes)
        if _remove_whitespace(box.text) and not _is_label_only(box.text, layout)
    ]
    kept = _sort_reading_order(kept)
    chunks = [_remove_whitespace(box.text) for box in kept]
    joined = "".join(chunks)
    stripped = _strip_printed_label(joined, layout)
    text, kept_indices = _trim_placeholders(stripped)
    if layout.kind == "date":
        text = _normalize_date(text)
    confidence = round(sum(box.confidence for box in kept) / len(kept), 3) if kept else 0.0
    segments = _build_value_segments(layout, chunks, joined, stripped, text, kept_indices)
    return FieldValue(text, confidence, segments)


def _deduplicate_boxes(boxes: list[OcrTextBox]) -> list[OcrTextBox]:
    kept: list[OcrTextBox] = []
    for box in sorted(boxes, key=lambda item: item.area, reverse=True):
        duplicate = False
        for other in kept:
            if _is_box_covered(box, other) and (
                _labels_similar(box.text, other.text)
                or _remove_whitespace(box.text) in _remove_whitespace(other.text)
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def _is_box_covered(box: OcrTextBox, other: OcrTextBox) -> bool:
    intersection = _overlap_area(box, other.x0, other.y0, other.x1, other.y1)
    return intersection >= 0.9 * box.area


def _sort_reading_order(boxes: list[OcrTextBox]) -> list[OcrTextBox]:
    if not boxes:
        return []
    heights = sorted(box.height for box in boxes)
    threshold = max(6.0, 0.6 * heights[len(heights) // 2])
    lines: list[list[OcrTextBox]] = []
    for box in sorted(boxes, key=lambda item: (item.center[1], item.center[0])):
        for line in lines:
            mean_y = sum(item.center[1] for item in line) / len(line)
            # 同一列上下两行的检测框可能纵向重叠；不能因中心接近就按x重排标题和正文。
            horizontal_neighbors = all(
                max(0.0, min(box.x1, item.x1) - max(box.x0, item.x0))
                <= SAME_LINE_HORIZONTAL_OVERLAP_MAX * min(box.x1 - box.x0, item.x1 - item.x0)
                for item in line
            )
            if abs(box.center[1] - mean_y) <= threshold and horizontal_neighbors:
                line.append(box)
                break
        else:
            lines.append([box])
    lines.sort(key=lambda line: sum(item.center[1] for item in line) / len(line))
    ordered: list[OcrTextBox] = []
    for line in lines:
        ordered.extend(sorted(line, key=lambda item: item.x0))
    return ordered


def _strip_printed_label(text: str, layout: FieldLayout) -> str:
    """去掉和值连在同一个框里的印刷栏目名（含认错一个字的变体）。"""
    if not text:
        return ""
    labels = sorted({layout.label, *layout.aliases}, key=len, reverse=True)
    for label in labels:
        key = _normalize_label(label)
        if not key:
            continue
        for size in range(len(key), min(len(text), len(key) + 3) + 1):
            if _labels_similar(_normalize_label(text[:size]), key):
                return re.sub(r"^[\s:：_＿\-—]+", "", text[size:])
    return text


def _is_label_only(text: str, layout: FieldLayout) -> bool:
    key = _normalize_label(text)
    return bool(key) and any(
        _labels_similar(key, _normalize_label(label)) for label in (layout.label, *layout.aliases)
    )


_TRIMMED_CHARACTERS = "□☐"
_TRIM_EDGE = ":：_＿"


def _trim_placeholders(text: str) -> tuple[str, list[int]]:
    """按原 _trim 规则清洗，并返回每个保留字符在入参中的下标。"""
    kept = [(index, char) for index, char in enumerate(text) if char not in _TRIMMED_CHARACTERS]
    while kept and _is_trim_edge(kept[0][1]):
        kept.pop(0)
    while kept and _is_trim_edge(kept[-1][1]):
        kept.pop()
    value = "".join(char for _, char in kept)
    if re.fullmatch(r"[年月日\s:：_＿\-—]*", value):
        return "", []
    return value, [index for index, _ in kept]


def _is_trim_edge(char: str) -> bool:
    return char.isspace() or char in _TRIM_EDGE


def _build_value_segments(
    layout: FieldLayout,
    chunks: list[str],
    joined: str,
    stripped: str,
    text: str,
    kept_indices: list[int],
) -> tuple[ValueSegment, ...]:
    """把每个保留文字框映射回最终 text；只有 mainWork 需要位置片段。"""
    if layout.key != "main_work" or not text:
        return ()
    prefix = len(joined) - len(stripped)
    if prefix < 0 or not joined.endswith(stripped):
        return (ValueSegment(text=text, start=0, end=len(text)),)
    final_index = {index: position for position, index in enumerate(kept_indices)}
    segments: list[ValueSegment] = []
    cursor = 0
    for chunk in chunks:
        positions = []
        for offset in range(len(chunk)):
            position = final_index.get(cursor + offset - prefix)
            if position is not None:
                positions.append(position)
        cursor += len(chunk)
        if positions:
            start, end = positions[0], positions[-1] + 1
            segments.append(ValueSegment(text=text[start:end], start=start, end=end))
    return tuple(segments) or (ValueSegment(text=text, start=0, end=len(text)),)


_DATE_PATTERN = re.compile(r"(20\d{2})\s*[年.\-/\s]\s*(\d{1,2})\s*[月.\-/\s]\s*(\d{1,2})")
_DATE_COMPACT = re.compile(r"\s*(20\d{2})(\d{2})(\d{2})\s*")


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


def _labels_similar(first: str, second: str) -> bool:
    first_key, second_key = _normalize_label(first), _normalize_label(second)
    if not first_key or not second_key:
        return False
    if first_key == second_key:
        return True
    if abs(len(first_key) - len(second_key)) > max(2, len(second_key) // 3):
        return False
    distance = _levenshtein_distance(first_key, second_key)
    if len(first_key) <= 3 or len(second_key) <= 3:
        return distance <= 1
    return (
        distance <= max(1, len(second_key) // 4)
        or _bigram_similarity(first_key, second_key) >= 0.75
    )


def _levenshtein_distance(first: str, second: str) -> int:
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for row, char in enumerate(first, 1):
        current = [row]
        for column, other in enumerate(second, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (char != other),
                )
            )
        previous = current
    return previous[-1]


def _bigram_similarity(first: str, second: str) -> float:
    if len(first) < 2 or len(second) < 2:
        return 1.0 if first == second else 0.0
    first_pairs = {first[index : index + 2] for index in range(len(first) - 1)}
    second_pairs = {second[index : index + 2] for index in range(len(second) - 1)}
    return 2 * len(first_pairs & second_pairs) / (len(first_pairs) + len(second_pairs))


def _normalize_label(text: str) -> str:
    return _LABEL_NOISE.sub("", text or "")


def _remove_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def bounds_on_canvas(
    rect_in_table: tuple[float, float, float, float],
    canvas_size: tuple[int, int],
    table_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """table相对u/v/w/h → 当前画布像素；表外区域允许负值或超1。"""
    width, height = canvas_size
    tx0, ty0, tx1, ty1 = table_rect
    table_width, table_height = (tx1 - tx0) * width, (ty1 - ty0) * height
    u, v, field_width, field_height = rect_in_table
    return (
        tx0 * width + u * table_width,
        ty0 * height + v * table_height,
        tx0 * width + (u + field_width) * table_width,
        ty0 * height + (v + field_height) * table_height,
    )


def field_bounds_on_canvas(
    layout: FieldLayout,
    canvas_size: tuple[int, int],
    table_rect: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """字段只能通过当前table落点换算，不能从页面宽高直接推断。"""
    return bounds_on_canvas(layout.rect_in_table, canvas_size, table_rect)


def _overlap_area(box: OcrTextBox, x0: float, y0: float, x1: float, y1: float) -> float:
    if box.polygon:
        polygon = np.asarray(box.polygon, np.float32)
        region = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)
        area, _ = cv2.intersectConvexConvex(polygon, region)
        return max(float(area), 0.0)
    inner_width = max(0.0, min(box.x1, x1) - max(box.x0, x0))
    inner_height = max(0.0, min(box.y1, y1) - max(box.y0, y0))
    return inner_width * inner_height
