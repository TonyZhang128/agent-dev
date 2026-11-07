"""整页文字框 → 栏目值：去重、归属、行合并、印刷栏目名剥离和日期归一。

匹配度量用"中心点优先 + 框内覆盖率"，不用 IoU：文本行框和整格框的
IoU 天然很低，覆盖率或中心点才是稳定的判据。
"""

import re
from collections.abc import Callable

import numpy as np

from app.ocr.journal.reading import read_boxes
from app.ocr.journal.spec import (
    FALLBACK_MARGIN,
    MATCH_AMBIGUITY_MARGIN,
    MATCH_CENTER_MARGIN,
    MATCH_COVERAGE_MIN,
    MAX_FALLBACK_FIELDS,
)
from app.ocr.journal.types import FieldReading, FieldSpec, TextBox, TextSegment

Reader = Callable[[np.ndarray], list[TextBox]]

_LABEL_NOISE = re.compile(r"[\s:：_＿□☐\-—()（）《》〈〉\[\]【】]+")


def read_fields(
    sheet: np.ndarray,
    specs: tuple[FieldSpec, ...],
    reader: Reader = read_boxes,
) -> list[FieldReading]:
    """一次整页 OCR 后按栏目取值；只对歧义/漏框字段做有限次裁剪补充识别。"""
    height, width = sheet.shape[:2]
    ocr_results = reader(sheet)
    groups, ambiguous = _assign(ocr_results, specs, width, height)
    readings: dict[str, FieldReading] = {}
    for spec in specs:
        assigned = groups.get(spec.key, [])
        value, conf, segments = _clean_parts(spec, assigned)
        readings[spec.key] = FieldReading(
            spec=spec,
            boxes=tuple(assigned),
            value=value,
            conf=conf,
            ambiguous=spec.key in ambiguous,
            segments=segments,
        )

    order = [spec for spec in specs if readings[spec.key].ambiguous]
    order += [
        spec
        for spec in specs
        if not readings[spec.key].value and not _has_value_box(spec, readings[spec.key].boxes)
    ]
    attempted: set[str] = set()
    attempts = 0
    for spec in order:
        if attempts >= MAX_FALLBACK_FIELDS:
            break
        if spec.key in attempted:
            continue
        attempted.add(spec.key)
        crop = _crop_field(sheet, spec, width, height)
        if crop is None:
            continue
        attempts += 1
        image, offset_x, offset_y = crop
        extra = [_shift(box, offset_x, offset_y) for box in reader(image)]
        extra = [box for box in extra if _center_in(box, spec, width, height, MATCH_CENTER_MARGIN)]
        if not extra:
            continue
        merged = _dedup(list(readings[spec.key].boxes) + extra)
        value, conf, segments = _clean_parts(spec, merged)
        if value:
            readings[spec.key] = FieldReading(
                spec=spec,
                boxes=tuple(_order_lines(merged)),
                value=value,
                conf=conf,
                ambiguous=False,
                segments=segments,
            )
    return [readings[spec.key] for spec in specs]


def _assign(
    boxes: list[TextBox],
    specs: tuple[FieldSpec, ...],
    width: int,
    height: int,
) -> tuple[dict[str, list[TextBox]], set[str]]:
    """根据OCR识别出的文字框，按照空间关系分配给预设好的栏目"""
    groups: dict[str, list[TextBox]] = {spec.key: [] for spec in specs}
    ambiguous: set[str] = set()
    for box in _dedup(boxes):
        scored: list[tuple[float, float, str]] = []
        for spec in specs:
            x0, y0, x1, y1 = _rect_px(spec, width, height)
            intersection = _intersection(box, x0, y0, x1, y1)
            coverage = intersection / box.area
            center_x, center_y = box.center
            margin_x = MATCH_CENTER_MARGIN * width
            margin_y = MATCH_CENTER_MARGIN * height
            center_in = (
                x0 - margin_x <= center_x <= x1 + margin_x
                and y0 - margin_y <= center_y <= y1 + margin_y
            )
            if not center_in and coverage < MATCH_COVERAGE_MIN:
                continue
            # 只有中心落在容差内、实际没有压到栏目区域的框（相邻栏的印刷名）
            # 不参与归属，避免把"编号："带进监理机构。
            if center_in and coverage <= 0.0:
                continue
            distance = float(
                np.hypot(
                    (center_x - (x0 + x1) / 2) / max(width, 1),
                    (center_y - (y0 + y1) / 2) / max(height, 1),
                )
            )
            score = (3.0 if center_in else 0.0) + 2.0 * coverage + 0.5 * (1.0 - min(distance, 1.0))
            scored.append((score, coverage, spec.key))
        if not scored:
            continue
        scored.sort(reverse=True)
        score, _coverage, key = scored[0]
        groups[key].append(box)
        if len(scored) > 1:
            second_score, second_coverage, _ = scored[1]
            if (
                score - second_score < MATCH_AMBIGUITY_MARGIN
                and second_coverage >= MATCH_COVERAGE_MIN
            ):
                ambiguous.add(key)
    return groups, ambiguous


def _has_value_box(spec: FieldSpec, boxes: tuple[TextBox, ...] | list[TextBox]) -> bool:
    return any(not _is_pure_label(box.text, spec) for box in boxes)


def _clean(spec: FieldSpec, boxes: list[TextBox]) -> tuple[str, float]:
    text, conf, _segments = _clean_parts(spec, boxes)
    return text, conf


def _clean_parts(
    spec: FieldSpec, boxes: list[TextBox]
) -> tuple[str, float, tuple[TextSegment, ...]]:
    kept = [
        box for box in _dedup(boxes) if _compact(box.text) and not _is_pure_label(box.text, spec)
    ]
    kept = _order_lines(kept)
    chunks = [_compact(box.text) for box in kept]
    joined = "".join(chunks)
    stripped = _strip_label(joined, spec)
    text, kept_indices = _trim_map(stripped)
    if spec.kind == "date":
        text = _normalise_date(text)
    conf = round(sum(box.conf for box in kept) / len(kept), 3) if kept else 0.0
    segments = _segments(spec, chunks, joined, stripped, text, kept_indices)
    return text, conf, segments


def _dedup(boxes: list[TextBox]) -> list[TextBox]:
    kept: list[TextBox] = []
    for box in sorted(boxes, key=lambda item: item.area, reverse=True):
        duplicate = False
        for other in kept:
            if _covered_by(box, other) and (
                _similar(box.text, other.text) or _compact(box.text) in _compact(other.text)
            ):
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def _covered_by(box: TextBox, other: TextBox) -> bool:
    intersection = _intersection(box, other.x0, other.y0, other.x1, other.y1)
    return intersection >= 0.9 * box.area


def _order_lines(boxes: list[TextBox]) -> list[TextBox]:
    if not boxes:
        return []
    heights = sorted(box.height for box in boxes)
    threshold = max(6.0, 0.6 * heights[len(heights) // 2])
    lines: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda item: (item.center[1], item.center[0])):
        for line in lines:
            mean_y = sum(item.center[1] for item in line) / len(line)
            if abs(box.center[1] - mean_y) <= threshold:
                line.append(box)
                break
        else:
            lines.append([box])
    lines.sort(key=lambda line: sum(item.center[1] for item in line) / len(line))
    ordered: list[TextBox] = []
    for line in lines:
        ordered.extend(sorted(line, key=lambda item: item.x0))
    return ordered


def _strip_label(text: str, spec: FieldSpec) -> str:
    """去掉和值连在同一个框里的印刷栏目名（含认错一个字的变体）。"""
    if not text:
        return ""
    labels = sorted({spec.label, *spec.aliases}, key=len, reverse=True)
    for label in labels:
        key = _label_key(label)
        if not key:
            continue
        for size in range(len(key), min(len(text), len(key) + 3) + 1):
            if _similar(_label_key(text[:size]), key):
                return re.sub(r"^[\s:：_＿\-—]+", "", text[size:])
    return text


def _is_pure_label(text: str, spec: FieldSpec) -> bool:
    key = _label_key(text)
    return bool(key) and any(
        _similar(key, _label_key(label)) for label in (spec.label, *spec.aliases)
    )


_TRIMMED_CHARACTERS = "□☐"
_TRIM_EDGE = ":：_＿"


def _trim(text: str) -> str:
    return _trim_map(text)[0]


def _trim_map(text: str) -> tuple[str, list[int]]:
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


def _segments(
    spec: FieldSpec,
    chunks: list[str],
    joined: str,
    stripped: str,
    text: str,
    kept_indices: list[int],
) -> tuple[TextSegment, ...]:
    """把每个保留文字框映射回最终 text；只有 mainWork 需要位置片段。"""
    if spec.key != "mainWork" or not text:
        return ()
    prefix = len(joined) - len(stripped)
    if prefix < 0 or not joined.endswith(stripped):
        return (TextSegment(text=text, start=0, end=len(text)),)
    final_index = {index: position for position, index in enumerate(kept_indices)}
    segments: list[TextSegment] = []
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
            segments.append(TextSegment(text=text[start:end], start=start, end=end))
    return tuple(segments) or (TextSegment(text=text, start=0, end=len(text)),)


_DATE_PATTERN = re.compile(r"(20\d{2})\s*[年.\-/\s]\s*(\d{1,2})\s*[月.\-/\s]\s*(\d{1,2})")
_DATE_COMPACT = re.compile(r"\s*(20\d{2})(\d{2})(\d{2})\s*")


def _normalise_date(text: str) -> str:
    match = _DATE_PATTERN.search(text) or _DATE_COMPACT.fullmatch(text)
    if not match:
        return text
    year, month, day = (int(value) for value in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return text
    return f"{year}-{month:02d}-{day:02d}"


def _similar(first: str, second: str) -> bool:
    first_key, second_key = _label_key(first), _label_key(second)
    if not first_key or not second_key:
        return False
    if first_key == second_key:
        return True
    if abs(len(first_key) - len(second_key)) > max(2, len(second_key) // 3):
        return False
    distance = _edit_distance(first_key, second_key)
    if len(first_key) <= 3 or len(second_key) <= 3:
        return distance <= 1
    return distance <= max(1, len(second_key) // 4) or _dice(first_key, second_key) >= 0.75


def _edit_distance(first: str, second: str) -> int:
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


def _dice(first: str, second: str) -> float:
    if len(first) < 2 or len(second) < 2:
        return 1.0 if first == second else 0.0
    first_pairs = {first[index : index + 2] for index in range(len(first) - 1)}
    second_pairs = {second[index : index + 2] for index in range(len(second) - 1)}
    return 2 * len(first_pairs & second_pairs) / (len(first_pairs) + len(second_pairs))


def _label_key(text: str) -> str:
    return _LABEL_NOISE.sub("", text or "")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _rect_px(spec: FieldSpec, width: int, height: int) -> tuple[float, float, float, float]:
    x, y, w, h = spec.rect
    return x * width, y * height, (x + w) * width, (y + h) * height


def _intersection(box: TextBox, x0: float, y0: float, x1: float, y1: float) -> float:
    inner_width = max(0.0, min(box.x1, x1) - max(box.x0, x0))
    inner_height = max(0.0, min(box.y1, y1) - max(box.y0, y0))
    return inner_width * inner_height


def _center_in(box: TextBox, spec: FieldSpec, width: int, height: int, margin: float) -> bool:
    x0, y0, x1, y1 = _rect_px(spec, width, height)
    center_x, center_y = box.center
    margin_x, margin_y = margin * width, margin * height
    return x0 - margin_x <= center_x <= x1 + margin_x and y0 - margin_y <= center_y <= y1 + margin_y


def _crop_field(
    sheet: np.ndarray, spec: FieldSpec, width: int, height: int
) -> tuple[np.ndarray, int, int] | None:
    x0, y0, x1, y1 = _rect_px(spec, width, height)
    margin_x, margin_y = FALLBACK_MARGIN * width, FALLBACK_MARGIN * height
    left = max(0, int(round(x0 - margin_x)))
    top = max(0, int(round(y0 - margin_y)))
    right = min(width, int(round(x1 + margin_x)))
    bottom = min(height, int(round(y1 + margin_y)))
    if right <= left or bottom <= top:
        return None
    return sheet[top:bottom, left:right], left, top


def _shift(box: TextBox, offset_x: int, offset_y: int) -> TextBox:
    return TextBox(
        text=box.text,
        x0=box.x0 + offset_x,
        y0=box.y0 + offset_y,
        x1=box.x1 + offset_x,
        y1=box.y1 + offset_y,
        conf=box.conf,
    )
