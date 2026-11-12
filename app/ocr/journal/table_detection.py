"""真实表格检测：共线边候选必须逐线匹配模板结构，纸张外缘不是成功锚点。"""

from dataclasses import dataclass
from itertools import combinations
from typing import Protocol

import cv2
import numpy as np

from app.errors import JournalFrameNotFound


class TableLine(Protocol):
    """表格核验所需的最小线段结构，业务模板可各自定义完整模型。"""

    @property
    def axis(self) -> str: ...

    @property
    def position(self) -> float: ...

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...


class TableField(Protocol):
    """反向边界核验所需的字段结构。"""

    @property
    def rect_in_table(self) -> tuple[float, float, float, float]: ...

    @property
    def inside_table(self) -> bool: ...


class TableTemplate(Protocol):
    """日志和简表共享表格拓扑检测的结构契约。"""

    @property
    def lines(self) -> tuple[TableLine, ...]: ...

    @property
    def fields(self) -> tuple[TableField, ...]: ...


# 所有距离随输入或候选table尺度变化，不按样本名称、固定照片坐标调参。
MIN_CANDIDATE_SEGMENT_PIXELS = 40
MIN_SUPPORT_SEGMENT_PIXELS = 18
COLLINEAR_DISTANCE_PIXELS = 8.0
COLLINEAR_ANGLE_DEGREES = 2.0
EDGE_COVERAGE_MIN = 0.55
TABLE_SIDE_MIN_PIXELS = 120
SUPPORT_DISTANCE_RATIO = 0.018
LINE_SUPPORT_MIN = 0.55
MEAN_SUPPORT_MIN = 0.8
FORBIDDEN_SUPPORT_MAX = 0.6
LINE_SAMPLE_COUNT = 21
MAX_HORIZONTAL_LINES = 22
MAX_VERTICAL_LINES = 12
DISTINCT_TABLE_RATIO = 0.08
AMBIGUITY_SCORE_MARGIN = 0.03


@dataclass(frozen=True)
class LineEvidence:
    """共线片段拟合的直线及有像素证据的投影范围。"""

    equation: np.ndarray
    endpoints: np.ndarray
    horizontal: bool
    span: float
    segments: np.ndarray


@dataclass(frozen=True)
class TableMatch:
    """table四角与逐线核验分数；不提供page/whole退化结果。"""

    corners: np.ndarray
    line_support: tuple[float, ...]
    score: float


DEFAULT_ASPECT_RANGE = (0.7, 1.8)


def detect_table(
    gray: np.ndarray,
    template: TableTemplate,
    *,
    aspect_range: tuple[float, float] = DEFAULT_ASPECT_RANGE,
) -> TableMatch:
    """检测任意轻度方向的线段，不用水平/竖直长核先破坏斜表格边。"""
    detected = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    segments = np.empty((0, 4), np.float32) if detected is None else detected[:, 0]
    return match_table_segments(
        segments,
        image_size=(gray.shape[1], gray.shape[0]),
        template=template,
        aspect_range=aspect_range,
    )


def match_table_segments(
    segments: np.ndarray,
    *,
    image_size: tuple[int, int],
    template: TableTemplate,
    aspect_range: tuple[float, float] = DEFAULT_ASPECT_RANGE,
) -> TableMatch:
    """对真实边的组合做模板结构验证；缺失或歧义时抛出受控业务异常。"""
    width, height = image_size
    if segments.ndim != 2 or segments.shape[1] != 4 or not np.isfinite(segments).all():
        raise JournalFrameNotFound("invalid table segments")
    lines = _merge_collinear_segments(segments)
    horizontal = sorted(
        (line for line in lines if line.horizontal), key=lambda line: line.span, reverse=True
    )[:MAX_HORIZONTAL_LINES]
    vertical = sorted(
        (line for line in lines if not line.horizontal), key=lambda line: line.span, reverse=True
    )[:MAX_VERTICAL_LINES]
    if len(horizontal) < 7 or len(vertical) < 3:
        raise JournalFrameNotFound("table grid missing")
    distance_map = _line_distance_map(segments, image_size)
    template_points, forbidden_points = _template_samples(template)
    accepted: list[TableMatch] = []
    for first, second in combinations(horizontal, 2):
        for third, fourth in combinations(vertical, 2):
            corners = _candidate_corners(first, second, third, fourth, image_size, aspect_range)
            if corners is None:
                continue
            match = _verify_candidate(
                corners, distance_map, template_points, forbidden_points, segments
            )
            if match is not None:
                accepted.append(match)
    if not accepted:
        raise JournalFrameNotFound("no candidate matches table structure")
    accepted.sort(key=lambda match: match.score, reverse=True)
    best = accepted[0]
    table_width = float(np.linalg.norm(best.corners[1] - best.corners[0]))
    for alternative in accepted[1:]:
        if best.score - alternative.score > AMBIGUITY_SCORE_MARGIN:
            break
        separation = float(np.max(np.linalg.norm(alternative.corners - best.corners, axis=1)))
        if separation > DISTINCT_TABLE_RATIO * table_width:
            raise JournalFrameNotFound("ambiguous table candidates")
    return best


def _fit_line(points: np.ndarray, *, horizontal: bool) -> LineEvidence:
    vx, vy, x, y = cv2.fitLine(points.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
    direction = np.array([vx, vy], dtype=float)
    origin = np.array([x, y], dtype=float)
    positions = (points - origin) @ direction
    endpoints = np.array(
        [origin + positions.min() * direction, origin + positions.max() * direction]
    )
    equation = np.array([-vy, vx, vy * x - vx * y], dtype=float)
    return LineEvidence(
        equation,
        endpoints,
        horizontal,
        float(positions.max() - positions.min()),
        points.reshape(-1, 2, 2),
    )


def _merge_collinear_segments(segments: np.ndarray) -> list[LineEvidence]:
    lengths = np.linalg.norm(segments[:, 2:] - segments[:, :2], axis=1)
    groups: list[tuple[LineEvidence, list[np.ndarray]]] = []
    distance_tolerance = COLLINEAR_DISTANCE_PIXELS
    angle_cosine = np.cos(np.deg2rad(COLLINEAR_ANGLE_DEGREES))
    for index in np.argsort(-lengths):
        if lengths[index] < MIN_CANDIDATE_SEGMENT_PIXELS:
            continue
        points = segments[index].reshape(2, 2).astype(float)
        delta = points[1] - points[0]
        horizontal = abs(delta[0]) >= 2 * abs(delta[1])
        if not horizontal and abs(delta[1]) < 2 * abs(delta[0]):
            continue
        line = _fit_line(points, horizontal=horizontal)
        for group_index, (existing, members) in enumerate(groups):
            if existing.horizontal != horizontal:
                continue
            if abs(float(existing.equation[:2] @ line.equation[:2])) < angle_cosine:
                continue
            distance = np.abs(points @ existing.equation[:2] + existing.equation[2])
            if float(distance.max()) > distance_tolerance:
                continue
            members.append(points)
            groups[group_index] = (
                _fit_line(np.concatenate(members), horizontal=horizontal),
                members,
            )
            break
        else:
            groups.append((line, [points]))
    return _join_edge_fragments([line for line, _ in groups], distance_tolerance)


def _edge_position(line: LineEvidence, along: float) -> float:
    a, b, c = line.equation
    return float(-(a * along + c) / b if line.horizontal else -(b * along + c) / a)


def _join_edge_fragments(lines: list[LineEvidence], tolerance: float) -> list[LineEvidence]:
    """连接同一边上小幅弯曲的片段；保留各段方向，求角点时不用整体直线外推。"""
    joined = list(lines)
    changed = True
    while changed:
        changed = False
        for first_index, first in enumerate(joined):
            axis = 0 if first.horizontal else 1
            first_range = sorted(first.endpoints[:, axis])
            for second_index in range(first_index + 1, len(joined)):
                second = joined[second_index]
                if first.horizontal != second.horizontal:
                    continue
                if abs(float(first.equation[:2] @ second.equation[:2])) < np.cos(np.deg2rad(8)):
                    continue
                second_range = sorted(second.endpoints[:, axis])
                start, end = (
                    max(first_range[0], second_range[0]),
                    min(first_range[1], second_range[1]),
                )
                if start - end > 10 * tolerance:
                    continue
                along = float((start + end) / 2)
                if (
                    abs(_edge_position(first, along) - _edge_position(second, along))
                    > 1.5 * tolerance
                ):
                    continue
                members = np.concatenate((first.segments, second.segments))
                joined[first_index] = _fit_line(members.reshape(-1, 2), horizontal=first.horizontal)
                del joined[second_index]
                changed = True
                break
            if changed:
                break
    return joined


def _nearest_segment_equation(line: LineEvidence, point: np.ndarray) -> np.ndarray:
    starts, ends = line.segments[:, 0], line.segments[:, 1]
    directions = ends - starts
    fractions = np.sum((point - starts) * directions, axis=1) / np.sum(directions**2, axis=1)
    nearest = starts + np.clip(fractions, 0, 1)[:, None] * directions
    segment = line.segments[int(np.argmin(np.linalg.norm(nearest - point, axis=1)))]
    return _fit_line(segment, horizontal=line.horizontal).equation


def _crossing(first: LineEvidence, second: LineEvidence) -> np.ndarray | None:
    homogeneous = np.cross(first.equation, second.equation)
    if abs(homogeneous[2]) < 1e-8:
        return None
    approximate = homogeneous[:2] / homogeneous[2]
    local = np.cross(
        _nearest_segment_equation(first, approximate),
        _nearest_segment_equation(second, approximate),
    )
    return None if abs(local[2]) < 1e-8 else local[:2] / local[2]


def _edge_coverage(first: np.ndarray, second: np.ndarray, line: LineEvidence) -> float:
    delta = second - first
    length = float(np.linalg.norm(delta))
    if length <= 0:
        return 0.0
    positions = (line.endpoints - first) @ (delta / length)
    return max(0.0, min(length, float(positions.max())) - max(0.0, float(positions.min()))) / length


def _candidate_corners(
    first: LineEvidence,
    second: LineEvidence,
    third: LineEvidence,
    fourth: LineEvidence,
    image_size: tuple[int, int],
    aspect_range: tuple[float, float],
) -> np.ndarray | None:
    center_x, center_y = image_size[0] / 2, image_size[1] / 2
    top, bottom = sorted((first, second), key=lambda line: _edge_position(line, center_x))
    left, right = sorted((third, fourth), key=lambda line: _edge_position(line, center_y))
    crossings = [
        _crossing(top, left),
        _crossing(top, right),
        _crossing(bottom, right),
        _crossing(bottom, left),
    ]
    if any(point is None for point in crossings):
        return None
    corners = np.asarray(crossings, dtype=np.float32)
    width, height = image_size
    if (
        (corners < -2).any()
        or (corners[:, 0] > width + 2).any()
        or (corners[:, 1] > height + 2).any()
    ):
        return None
    if not cv2.isContourConvex(corners.reshape(-1, 1, 2)):
        return None
    edges = np.roll(corners, -1, axis=0) - corners
    lengths = np.linalg.norm(edges, axis=1)
    if lengths.min() < TABLE_SIDE_MIN_PIXELS:
        return None
    aspect = float((lengths[1] + lengths[3]) / (lengths[0] + lengths[2]))
    if not aspect_range[0] <= aspect <= aspect_range[1]:
        return None
    for index, line in enumerate((top, right, bottom, left)):
        if _edge_coverage(corners[index], corners[(index + 1) % 4], line) < EDGE_COVERAGE_MIN:
            return None
    return corners


def _line_distance_map(segments: np.ndarray, image_size: tuple[int, int]) -> np.ndarray:
    width, height = image_size
    mask = np.zeros((height, width), np.uint8)
    minimum_length = MIN_SUPPORT_SEGMENT_PIXELS  # 保留短竖线的碎段，不按整图比例过滤。
    for segment in segments:
        points = segment.reshape(2, 2)
        if np.linalg.norm(points[1] - points[0]) >= minimum_length:
            cv2.line(
                mask,
                tuple(np.rint(points[0]).astype(int)),
                tuple(np.rint(points[1]).astype(int)),
                255,
                1,
            )
    return cv2.distanceTransform(255 - mask, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def _template_samples(template: TableTemplate) -> tuple[np.ndarray, np.ndarray]:
    positions = np.linspace(0.035, 0.965, LINE_SAMPLE_COUNT)
    positive, forbidden = [], []
    for line in template.lines:
        if not -0.002 <= line.position <= 1.002 or line.start < -0.002 or line.end > 1.002:
            continue
        along = line.start + positions * (line.end - line.start)
        points = np.column_stack((along, np.full_like(along, line.position)))
        if line.axis == "vertical":
            points = points[:, ::-1]
            for field in template.fields:
                u, v, width, height = field.rect_in_table
                if not field.inside_table or not u + 0.002 < line.position < u + width - 0.002:
                    continue
                if line.start < v + height - 0.002 and line.end > v + 0.002:
                    continue
                # 每个合并值格分别核验缺席，包含第一行，不用下半表平均值代替。
                outside = np.linspace(v, v + height, LINE_SAMPLE_COUNT)
                forbidden.append(np.column_stack((np.full_like(outside, line.position), outside)))
        positive.append(points)
    return np.asarray(positive, np.float32), np.asarray(forbidden, np.float32)


def _sample_distance(
    points: np.ndarray, matrix: np.ndarray, distance_map: np.ndarray
) -> np.ndarray:
    transformed = cv2.perspectiveTransform(points.reshape(1, -1, 2), matrix)[0]
    positions = np.rint(transformed).astype(int)
    height, width = distance_map.shape
    return distance_map[
        np.clip(positions[:, 1], 0, height - 1), np.clip(positions[:, 0], 0, width - 1)
    ].reshape(points.shape[:2])


def _verify_candidate(
    corners: np.ndarray,
    distance_map: np.ndarray,
    template_points: np.ndarray,
    forbidden_points: np.ndarray,
    segments: np.ndarray,
) -> TableMatch | None:
    unit = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(unit, corners)
    table_side = float(np.min(np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)))
    tolerance = max(2.5, SUPPORT_DISTANCE_RATIO * table_side)
    distances = _sample_distance(template_points, matrix, distance_map)
    support = np.mean(distances <= tolerance, axis=1)
    if support.min() < LINE_SUPPORT_MIN or support.mean() < MEAN_SUPPORT_MIN:
        return None
    if forbidden_points.size:
        projected = cv2.perspectiveTransform(forbidden_points.reshape(1, -1, 2), matrix)[0]
        for boundary in projected.reshape(forbidden_points.shape):
            if (
                _boundary_segment_coverage(boundary[0], boundary[-1], segments, tolerance)
                > FORBIDDEN_SUPPORT_MAX
            ):
                return None
    score = float(np.mean(np.exp(-0.5 * (distances / tolerance) ** 2)))
    return TableMatch(corners, tuple(float(value) for value in support), score)


def _boundary_segment_coverage(
    start: np.ndarray, end: np.ndarray, segments: np.ndarray, tolerance: float
) -> float:
    """按真实平行线段的投影并集判断额外边界，距离容差不扩张线段端点。"""
    direction = end - start
    length = float(np.linalg.norm(direction))
    direction = direction / length
    normal = np.array([-direction[1], direction[0]])
    starts, ends = segments[:, :2], segments[:, 2:]
    vectors = ends - starts
    lengths = np.linalg.norm(vectors, axis=1)
    valid = lengths >= MIN_SUPPORT_SEGMENT_PIXELS
    parallel = np.abs(vectors @ direction) >= lengths * np.cos(np.deg2rad(12))
    nearby = (
        np.maximum(np.abs((starts - start) @ normal), np.abs((ends - start) @ normal)) <= tolerance
    )
    selected = segments[valid & parallel & nearby].reshape(-1, 2, 2)
    if not len(selected):
        return 0.0
    projected = (selected - start) @ direction
    intervals = sorted(
        (max(0.0, float(pair.min())), min(length, float(pair.max()))) for pair in projected
    )
    covered, previous_end = 0.0, 0.0
    for lower, upper in intervals:
        covered += max(0.0, upper - max(lower, previous_end))
        previous_end = max(previous_end, upper)
    return covered / length
