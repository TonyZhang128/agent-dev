"""从标准 PDF 构建字段模板；文字层、线条和语义绑定均可独立检查。"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.ocr.journal.template import (
    JournalTemplate,
    Rect,
    TemplateField,
    TemplateLine,
    bounds_to_table,
)

# Word PDF 的表格边常用窄矩形绘制；容差为 PDF pt，不依赖业务照片分辨率。
LINE_THICKNESS_MAX = 3.0
LINE_LENGTH_MIN = 12.0
LINE_MERGE_TOLERANCE = 1.0
TABLE_SPAN_RATIO = 0.9
OUTSIDE_TEXT_HEIGHT_MULTIPLIER = 2.0
LABELS = (
    ("project", "工程项目", ("公路工程项目", "项目名称")),
    ("number", "编号", ()),
    ("supervision_org", "监理机构", ("监理单位",)),
    ("recorder", "记录人", ()),
    ("weather", "天气", ("天气情况",)),
    ("position", "岗位", ()),
    ("date", "记录时间", ("日期",)),
    ("reviewer", "审核人", ()),
    ("main_work", "当日主要监理工作情况", ()),
    ("issues", "发现的问题及处理结果", ("发现的问题", "问题及处理情况")),
    ("next_day_plan", "次日工作计划和管控重点", ("次日工作计划",)),
)


@dataclass(frozen=True)
class PdfText:
    """一个可见文字片段，已排除空白字符对边界的干扰。"""

    text: str
    rect: Rect


def build_template(path: Path) -> JournalTemplate:
    """解析单页标准模板；缺少标签、值格或完整表格时抛 ValueError，不猜坐标。"""
    with pymupdf.open(path) as document:
        if len(document) != 1:
            raise ValueError("监理日记模板必须为单页 PDF")
        page = document[0]
        page.remove_rotation()
        lines = _extract_lines(page)
        table_rect, cells = _table_cells(lines)
        text_runs = _visible_text(page)
        fields = tuple(
            _build_field(key, label, aliases, cells, lines, text_runs, table_rect, page.rect)
            for key, label, aliases in LABELS
        )
        return JournalTemplate(
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_page_size=(page.rect.width, page.rect.height),
            source_table_bounds=table_rect,
            table_aspect=(table_rect[3] - table_rect[1]) / (table_rect[2] - table_rect[0]),
            lines=tuple(_normalize_line(line, table_rect) for line in lines),
            fields=fields,
        )


def _extract_lines(page: pymupdf.Page) -> list[TemplateLine]:
    candidates: list[TemplateLine] = []
    for drawing in page.get_drawings():
        if not drawing.get("fill_opacity", 1) and not drawing.get("stroke_opacity", 1):
            continue
        for item in drawing["items"]:
            if item[0] == "re":
                rect = item[1]
                if rect.height <= LINE_THICKNESS_MAX and rect.width >= LINE_LENGTH_MIN:
                    candidates.append(
                        TemplateLine(
                            axis="horizontal",
                            position=(rect.y0 + rect.y1) / 2,
                            start=rect.x0,
                            end=rect.x1,
                        )
                    )
                elif rect.width <= LINE_THICKNESS_MAX and rect.height >= LINE_LENGTH_MIN:
                    candidates.append(
                        TemplateLine(
                            axis="vertical",
                            position=(rect.x0 + rect.x1) / 2,
                            start=rect.y0,
                            end=rect.y1,
                        )
                    )
            elif item[0] == "l":
                first, second = item[1:3]
                if abs(first.y - second.y) <= LINE_MERGE_TOLERANCE:
                    candidates.append(
                        TemplateLine(
                            axis="horizontal",
                            position=(first.y + second.y) / 2,
                            start=min(first.x, second.x),
                            end=max(first.x, second.x),
                        )
                    )
                elif abs(first.x - second.x) <= LINE_MERGE_TOLERANCE:
                    candidates.append(
                        TemplateLine(
                            axis="vertical",
                            position=(first.x + second.x) / 2,
                            start=min(first.y, second.y),
                            end=max(first.y, second.y),
                        )
                    )
    merged: list[TemplateLine] = []
    for line in sorted(candidates, key=lambda edge: (edge.axis, edge.position, edge.start)):
        for index, existing in enumerate(merged):
            if (
                line.axis == existing.axis
                and abs(line.position - existing.position) <= LINE_MERGE_TOLERANCE
                and line.start <= existing.end + LINE_MERGE_TOLERANCE
                and line.end >= existing.start - LINE_MERGE_TOLERANCE
            ):
                merged[index] = existing.model_copy(
                    update={
                        "start": min(line.start, existing.start),
                        "end": max(line.end, existing.end),
                    }
                )
                break
        else:
            merged.append(line)
    return merged


def _table_cells(lines: list[TemplateLine]) -> tuple[Rect, list[Rect]]:
    horizontal = [line for line in lines if line.axis == "horizontal"]
    if not horizontal:
        raise ValueError("模板缺少完整表格横线")
    longest = max(line.end - line.start for line in horizontal)
    rows = sorted(
        (line for line in horizontal if line.end - line.start >= longest * TABLE_SPAN_RATIO),
        key=lambda line: line.position,
    )
    if len(rows) != 7:
        raise ValueError("监理日记模板应包含六个栏目行")
    left, right = rows[0].start, rows[0].end
    table_rect = (left, rows[0].position, right, rows[-1].position)
    cells: list[Rect] = []
    for top, bottom in zip(rows, rows[1:], strict=False):
        boundaries = sorted(
            line.position
            for line in lines
            if line.axis == "vertical"
            and line.start <= top.position + LINE_MERGE_TOLERANCE
            and line.end >= bottom.position - LINE_MERGE_TOLERANCE
        )
        if (
            len(boundaries) < 3
            or abs(boundaries[0] - left) > LINE_MERGE_TOLERANCE
            or abs(boundaries[-1] - right) > LINE_MERGE_TOLERANCE
        ):
            raise ValueError("模板缺少完整表格竖线")
        cells.extend(
            (x0, top.position, x1, bottom.position)
            for x0, x1 in zip(boundaries, boundaries[1:], strict=False)
        )
    table_rect = (
        min(cell[0] for cell in cells),
        rows[0].position,
        max(cell[2] for cell in cells),
        rows[-1].position,
    )
    return table_rect, cells


def _visible_text(page: pymupdf.Page) -> list[PdfText]:
    text_runs: list[PdfText] = []
    for span in page.get_texttrace():
        if span["type"] == 3 or span["opacity"] <= 0:
            continue
        characters = [char for char in span["chars"] if not chr(char[0]).isspace()]
        if not characters:
            continue
        rect = (
            min(char[3][0] for char in characters),
            min(char[3][1] for char in characters),
            max(char[3][2] for char in characters),
            max(char[3][3] for char in characters),
        )
        text_runs.append(PdfText("".join(chr(char[0]) for char in characters), rect))
    return sorted(text_runs, key=lambda run: (run.rect[1], run.rect[0]))


def _inside(inner: Rect, outer: Rect) -> bool:
    center_x, center_y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


def _union_rect(rectangles: list[Rect]) -> Rect:
    return (
        min(rect[0] for rect in rectangles),
        min(rect[1] for rect in rectangles),
        max(rect[2] for rect in rectangles),
        max(rect[3] for rect in rectangles),
    )


def _build_field(
    key: str,
    label: str,
    aliases: tuple[str, ...],
    cells: list[Rect],
    lines: list[TemplateLine],
    text_runs: list[PdfText],
    table: Rect,
    page: pymupdf.Rect,
) -> TemplateField:
    labels = (label, *aliases)
    if key in {"project", "number", "reviewer"}:
        matches = [
            run
            for run in text_runs
            if run.text.rstrip("：:") in labels and not _inside(run.rect, table)
        ]
        if len(matches) != 1:
            raise ValueError(f"模板标签缺失或不唯一：{label}")
        anchor = matches[0].rect
        value_rect = _outside_value(key, anchor, lines, table, page)
    else:
        label_cells = [
            (cell, [run for run in text_runs if _inside(run.rect, cell)]) for cell in cells
        ]
        matches = [
            (cell, runs)
            for cell, runs in label_cells
            if "".join(run.text for run in runs).rstrip("：:") in labels
        ]
        if len(matches) != 1:
            raise ValueError(f"模板标签缺失或不唯一：{label}")
        label_cell, runs = matches[0]
        anchor = _union_rect([run.rect for run in runs])
        adjacent = [
            cell
            for cell in cells
            if abs(cell[0] - label_cell[2]) <= LINE_MERGE_TOLERANCE
            and cell[1] == label_cell[1]
            and cell[3] == label_cell[3]
        ]
        if len(adjacent) != 1:
            raise ValueError(f"模板标签没有唯一右侧值格：{label}")
        value_rect = adjacent[0]
    return TemplateField(
        key=key,
        label=label,
        aliases=aliases,
        kind="date" if key == "date" else "text",
        label_rect_in_table=bounds_to_table(anchor, table),
        rect_in_table=bounds_to_table(value_rect, table),
        inside_table=key not in {"project", "number", "reviewer"},
    )


def _outside_value(
    key: str, anchor: Rect, lines: list[TemplateLine], table: Rect, page: pymupdf.Rect
) -> Rect:
    height = anchor[3] - anchor[1]
    if key == "project":
        underlines = [
            line
            for line in lines
            if line.axis == "horizontal"
            and line.position < table[1]
            and line.end <= anchor[0] + LINE_MERGE_TOLERANCE
            and abs(line.position - anchor[3]) <= height
        ]
        if len(underlines) != 1:
            raise ValueError("工程项目缺少唯一填写下划线")
        line = underlines[0]
        return (
            line.start,
            max(0, line.position - height * OUTSIDE_TEXT_HEIGHT_MULTIPLIER),
            line.end,
            line.position,
        )
    top = (
        max(table[3], anchor[1] - height / 2)
        if key == "reviewer"
        else max(0, anchor[1] - height / 2)
    )
    bottom = min(page.height, anchor[3] + height) if key == "reviewer" else table[1]
    return (anchor[2], top, table[2], bottom)


def _normalize_line(line: TemplateLine, table: Rect) -> TemplateLine:
    """PDF线段转为table归一化位置，保留表外下划线。"""
    left, top, right, bottom = table
    across_origin, across_extent, along_origin, along_extent = (
        (top, bottom - top, left, right - left)
        if line.axis == "horizontal"
        else (left, right - left, top, bottom - top)
    )
    return TemplateLine(
        axis=line.axis,
        position=(line.position - across_origin) / across_extent,
        start=(line.start - along_origin) / along_extent,
        end=(line.end - along_origin) / along_extent,
    )
