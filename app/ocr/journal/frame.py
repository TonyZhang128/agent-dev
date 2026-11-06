"""在原图上定位表格外框，并用一次单应变换把整页校正到固定画布。

和旧的"先找纸、再在纸里找表、再把坐标映射回原图"不同，这里直接对照片
做横竖线提取：线区域的最大内轮廓就是表格，取不到时再用四条边框线拟合，
最后才退回整张照片。最终图像只从原图采样一次。
"""

import cv2
import numpy as np

from app.ocr.journal.spec import (
    CANVAS_MAX_SIDE,
    CANVAS_MAX_WIDTH,
    CANVAS_MIN_WIDTH,
    MIN_QUAD_AREA_RATIO,
    PAGE_ASPECT,
    TABLE_LINE_DENSITY,
    TABLE_RECT,
)
from app.ocr.journal.types import LocationKind, PageLocation, Photo


def locate(photo: Photo) -> PageLocation:
    """照片 → 校正页面；返回画布、原图坐标四角和定位方式。"""
    quad, kind = _find_table_quad(photo)
    width, height = _canvas_size(quad, kind)
    destination = _destination(kind, width, height)
    matrix = cv2.getPerspectiveTransform(quad, destination)
    sheet = cv2.warpPerspective(
        photo.bgr,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderValue=(255, 255, 255),
    )
    original_quad = quad if photo.scale == 1.0 else quad / photo.scale
    return PageLocation(
        sheet=sheet,
        quad=np.asarray(original_quad, np.float32),
        kind=kind,
        how=_how(kind),
        width=width,
        height=height,
        matrix=matrix,
    )


def _find_table_quad(photo: Photo) -> tuple[np.ndarray, LocationKind]:
    height, width = photo.gray.shape
    binary = cv2.adaptiveThreshold(
        photo.gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        12,
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    horizontal = cv2.bitwise_or(
        _line_mask(binary, (max(20, width // 30), 1)),
        _line_mask(binary, (max(20, width // 12), 1)),
    )
    vertical = cv2.bitwise_or(
        _line_mask(binary, (1, max(20, height // 30))),
        _line_mask(binary, (1, max(20, height // 12))),
    )
    grid = cv2.dilate(cv2.bitwise_or(horizontal, vertical), np.ones((3, 3), np.uint8))

    candidates: list[np.ndarray] = []
    closed = cv2.morphologyEx(grid, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contour) < MIN_QUAD_AREA_RATIO * width * height:
            break
        quad = _quad_from_contour(contour, width, height)
        if quad is not None:
            candidates.append(quad)
    border = _quad_from_borders(horizontal, vertical, width, height)
    if border is not None:
        candidates.append(border)

    if not candidates:
        return _whole_quad(width, height), "whole"
    best = _choose_candidate(candidates, grid, width, height)
    kind = _candidate_kind(best, grid, width, height)
    return _order_points(best), kind


def _line_mask(binary: np.ndarray, kernel: tuple[int, int]) -> np.ndarray:
    return cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, kernel),
    )


def _quad_from_contour(contour: np.ndarray, width: int, height: int) -> np.ndarray | None:
    """线区域轮廓 → 四点；epsilon 从小到大试，避免旧实现固定阈值得到 9 个点就丢弃。"""
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    if perimeter <= 0:
        return None
    for epsilon in (0.01, 0.015, 0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) != 4:
            continue
        quad = _order_points(approx.reshape(4, 2).astype(np.float32))
        if _valid_quad(quad, width, height):
            return quad
    rect = cv2.minAreaRect(hull)
    quad = _order_points(cv2.boxPoints(rect).astype(np.float32))
    return quad if _valid_quad(quad, width, height) else None


def _quad_from_borders(
    horizontal: np.ndarray, vertical: np.ndarray, width: int, height: int
) -> np.ndarray | None:
    """四条最外边框线求交；轮廓断裂时作为补充候选。"""
    horizontal_segments = _segments(horizontal, width, height, horizontal=True)
    vertical_segments = _segments(vertical, width, height, horizontal=False)
    if not horizontal_segments or not vertical_segments:
        return None
    top = min(horizontal_segments, key=lambda s: s[1] + s[3])
    bottom = max(horizontal_segments, key=lambda s: s[1] + s[3])
    left = min(vertical_segments, key=lambda s: s[0] + s[2])
    right = max(vertical_segments, key=lambda s: s[0] + s[2])
    corners = (
        _intersection(top, left),
        _intersection(top, right),
        _intersection(bottom, right),
        _intersection(bottom, left),
    )
    if any(point is None for point in corners):
        return None
    quad = _order_points(np.array(corners, np.float32))
    return quad if _valid_quad(quad, width, height) else None


def _segments(
    mask: np.ndarray, width: int, height: int, *, horizontal: bool
) -> list[tuple[float, float, float, float]]:
    lines = cv2.HoughLinesP(
        mask,
        1,
        np.pi / 180,
        threshold=max(40, (width if horizontal else height) // 12),
        minLineLength=(width if horizontal else height) // 4,
        maxLineGap=(width if horizontal else height) // 40,
    )
    if lines is None:
        return []
    out = []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = abs(float(x2 - x1)), abs(float(y2 - y1))
        if horizontal:
            if dx < 0.4 * width or dy > 0.2 * dx:
                continue
        elif dy < 0.4 * height or dx > 0.2 * dy:
            continue
        out.append((float(x1), float(y1), float(x2), float(y2)))
    return out


def _intersection(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float] | None:
    x1, y1, x2, y2 = first
    x3, y3, x4, y4 = second
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-6:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return (
        (a * (x3 - x4) - (x1 - x2) * b) / denominator,
        (a * (y3 - y4) - (y1 - y2) * b) / denominator,
    )


def _choose_candidate(
    candidates: list[np.ndarray], grid: np.ndarray, width: int, height: int
) -> np.ndarray:
    """优先选长宽比和线密度都像表格的候选，避免把带表格的整页外框当成表格。"""
    inner = [quad for quad in candidates if _looks_like_table(quad, grid, width, height)]
    pool = inner or candidates
    return max(pool, key=lambda quad: _score(quad, grid, width, height))


def _score(quad: np.ndarray, grid: np.ndarray, width: int, height: int) -> float:
    density = _line_density(quad, grid)
    area = min(_area_ratio(quad, width, height), 1.0)
    table_aspect = _table_aspect()
    aspect = _aspect(quad)
    aspect_gap = abs(aspect - table_aspect) / max(table_aspect, 1e-6)
    center = quad.mean(axis=0)
    distance = float(
        np.hypot(
            (center[0] - width / 2) / max(width / 2, 1),
            (center[1] - height / 2) / max(height / 2, 1),
        )
    )
    return density * 50 + area + 0.5 / (1 + aspect_gap * 10) + 0.2 * (1 - min(distance, 2))


def _candidate_kind(quad: np.ndarray, grid: np.ndarray, width: int, height: int) -> LocationKind:
    return "table" if _looks_like_table(quad, grid, width, height) else "page"


def _looks_like_table(quad: np.ndarray, grid: np.ndarray, width: int, height: int) -> bool:
    """长宽比更接近表格、且内部有线或没有被页面外框包住时，按表格定位。"""
    aspect = _aspect(quad)
    table_aspect = _table_aspect()
    if abs(aspect - table_aspect) > abs(aspect - PAGE_ASPECT):
        return False
    area = _area_ratio(quad, width, height)
    return area < 0.85 or _line_density(quad, grid) >= TABLE_LINE_DENSITY / 2


def _valid_quad(quad: np.ndarray, width: int, height: int) -> bool:
    if quad.shape != (4, 2) or not np.isfinite(quad).all():
        return False
    if _area_ratio(quad, width, height) < MIN_QUAD_AREA_RATIO:
        return False
    contour = quad.reshape(-1, 1, 2).astype(np.int32)
    if not cv2.isContourConvex(contour):
        return False
    sides = [float(np.linalg.norm(quad[(index + 1) % 4] - quad[index])) for index in range(4)]
    return min(sides) >= 0.2 * min(width, height)


def _area_ratio(quad: np.ndarray, width: int, height: int) -> float:
    return abs(float(cv2.contourArea(quad.astype(np.float32)))) / max(width * height, 1)


def _aspect(quad: np.ndarray) -> float:
    top = float(np.linalg.norm(quad[1] - quad[0]))
    bottom = float(np.linalg.norm(quad[2] - quad[3]))
    left = float(np.linalg.norm(quad[3] - quad[0]))
    right = float(np.linalg.norm(quad[2] - quad[1]))
    horizontal = max((top + bottom) / 2, 1.0)
    vertical = max((left + right) / 2, 1.0)
    return vertical / horizontal


def _table_aspect() -> float:
    x0, y0, x1, y1 = TABLE_RECT
    return (y1 - y0) * PAGE_ASPECT / (x1 - x0)


def _line_density(quad: np.ndarray, grid: np.ndarray) -> float:
    height, width = grid.shape
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [quad.astype(np.int32)], 255)
    area = cv2.countNonZero(mask)
    if not area:
        return 0.0
    return cv2.countNonZero(cv2.bitwise_and(grid, mask)) / area


def _canvas_size(quad: np.ndarray, kind: LocationKind) -> tuple[int, int]:
    top = float(np.linalg.norm(quad[1] - quad[0]))
    bottom = float(np.linalg.norm(quad[2] - quad[3]))
    measured = (top + bottom) / 2
    table_width = TABLE_RECT[2] - TABLE_RECT[0]
    width = measured / table_width if kind == "table" else measured
    width = int(round(min(max(width, CANVAS_MIN_WIDTH), CANVAS_MAX_WIDTH)))
    height = int(round(width * PAGE_ASPECT))
    if max(width, height) > CANVAS_MAX_SIDE:
        scale = CANVAS_MAX_SIDE / max(width, height)
        width = max(1, int(round(width * scale)))
        height = max(1, int(round(height * scale)))
    return max(width, 1), max(height, 1)


def _destination(kind: LocationKind, width: int, height: int) -> np.ndarray:
    if kind != "table":
        return np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            np.float32,
        )
    x0, y0, x1, y1 = TABLE_RECT
    return np.array(
        [
            [x0 * width, y0 * height],
            [x1 * width, y0 * height],
            [x1 * width, y1 * height],
            [x0 * width, y1 * height],
        ],
        np.float32,
    )


def _order_points(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def _whole_quad(width: int, height: int) -> np.ndarray:
    return np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        np.float32,
    )


def _how(kind: LocationKind) -> str:
    return {"table": "contour+table", "page": "contour"}.get(kind, "whole")
