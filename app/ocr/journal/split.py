"""mainWork 原文拆分：文字单元、可靠标题、规则回退、结果校验与字段组装。

只做“把原文分配到三个字段”，不生成、不纠错、不润色。模型只返回单元 ID 的
类别；字段值一律由本模块从 source_text 原样截取。
"""

import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.errors import MainWorkSplitError
from app.ocr.journal.types import FieldReading, TextSegment
from app.schemas.ocr import (
    MainWorkCategory,
    MainWorkSplitPlan,
    MainWorkSplitRequest,
    MainWorkUnit,
    MainWorkValues,
)

logger = logging.getLogger(__name__)

# 初始值；超过上限不截断，直接跳过模型改用标题规则，规则失败则返回受控 502。
MAX_SPLIT_CHARACTERS = 4000

STRONG_BOUNDARIES = "。；;！？!?"
HEADING_SEPARATORS = "：:、，,"
HEADING_ALIASES: tuple[tuple[str, MainWorkCategory], ...] = tuple(
    sorted(
        {
            "主要施工情况": MainWorkCategory.construction,
            "施工情况": MainWorkCategory.construction,
            "施工": MainWorkCategory.construction,
            "旁站情况": MainWorkCategory.witness,
            "旁站记录": MainWorkCategory.witness,
            "旁站": MainWorkCategory.witness,
            "巡视情况": MainWorkCategory.patrol,
            "巡视记录": MainWorkCategory.patrol,
            "巡视": MainWorkCategory.patrol,
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)
CONTAINER_LABELS = ("当日主要监理工作情况", "主要监理工作情况")

_FIELD_CATEGORIES = (
    MainWorkCategory.construction,
    MainWorkCategory.witness,
    MainWorkCategory.patrol,
)
_NUMBERING = re.compile(r"^(?:\d+[.、)）]|[一二三四五六七八九十]+[、.]|[（(]\d+[)）])")
_TRAILING_PUNCTUATION = "：:、，,。；;！？!?"

Planner = Callable[[MainWorkSplitRequest], Awaitable[MainWorkSplitPlan]]

Piece = tuple[str, int, bool, MainWorkCategory | None]


@dataclass(frozen=True)
class SplitOutcome:
    """拆分结果与请求内诊断信息；诊断字段不进入 HTTP 响应。"""

    values: MainWorkValues
    strategy: Literal["empty", "llm", "rules"]
    source_text: str
    units: tuple[MainWorkUnit, ...]
    unknown_count: int


def is_meaningful(text: str) -> bool:
    """纯标点/空白单元没有业务含义，不应单独产生 unknown。"""
    return any(char.isalnum() for char in text)


def build_units(source_text: str, segments: Sequence[TextSegment] = ()) -> tuple[MainWorkUnit, ...]:
    """把 source_text 切成单元；拼接后必须能完整还原 source_text。"""
    if not source_text:
        return ()
    pieces = _pieces(source_text, tuple(segments))
    if "".join(piece[0] for piece in pieces) != source_text:
        # 位置片段不可信时退化为整段，避免丢弃或重复原文。
        pieces = _pieces(source_text, ())
    merged = _merge_punctuation(pieces)
    return tuple(
        MainWorkUnit(
            unit_id=f"u{index}",
            text=text,
            start=start,
            end=start + len(text),
            is_heading=heading,
            heading_category=category,
        )
        for index, (text, start, heading, category) in enumerate(merged, 1)
    )


def rule_assignments(
    units: Sequence[MainWorkUnit],
) -> dict[str, MainWorkCategory] | None:
    """按可靠标题或单元开头强标记分配；无法完整覆盖时返回 None。"""
    headings = [
        (index, unit)
        for index, unit in enumerate(units)
        if unit.is_heading and unit.heading_category is not None
    ]
    if not headings:
        return _marker_assignments(units)

    for unit in units[: headings[0][0]]:
        if not _is_container(unit.text):
            # 首个可靠标题前的有效正文无法确定归属；不静默塞进 construction。
            return None

    assignments: dict[str, MainWorkCategory] = {}
    for position, (index, unit) in enumerate(headings):
        category = unit.heading_category
        if category is None:
            return None
        stop = headings[position + 1][0] if position + 1 < len(headings) else len(units)
        for item in units[index:stop]:
            assignments[item.unit_id] = category
    return assignments


def validate_plan(
    units: Sequence[MainWorkUnit], plan: MainWorkSplitPlan
) -> dict[str, MainWorkCategory] | None:
    """校验模型计划；任何不完整、越界、标题不一致或有效 unknown 都整体拒绝。"""
    known = {unit.unit_id for unit in units}
    assignments: dict[str, MainWorkCategory] = {}
    for item in plan.assignments:
        if item.unit_id not in known or item.unit_id in assignments:
            return None
        assignments[item.unit_id] = item.category
    if set(assignments) != known:
        return None

    heading_category: MainWorkCategory | None = None
    for unit in units:
        category = assignments[unit.unit_id]
        if unit.is_heading and unit.heading_category is not None:
            if category != unit.heading_category:
                return None
            heading_category = unit.heading_category
        elif heading_category is not None and category != heading_category:
            return None

    if any(_is_effective_unknown(unit, assignments[unit.unit_id]) for unit in units):
        return None
    return assignments


def assemble(
    units: Sequence[MainWorkUnit], assignments: dict[str, MainWorkCategory]
) -> MainWorkValues:
    """按原文顺序拼接同类单元；只有标题的类别返回 null。"""
    grouped: dict[MainWorkCategory, list[MainWorkUnit]] = {
        category: [] for category in _FIELD_CATEGORIES
    }
    for unit in units:
        category = assignments.get(unit.unit_id)
        if category is not None and category in grouped:
            grouped[category].append(unit)

    def value(category: MainWorkCategory) -> str | None:
        items = grouped[category]
        if not any(not item.is_heading for item in items):
            return None
        return "".join(item.text for item in items)

    return MainWorkValues(
        construction=value(MainWorkCategory.construction),
        witness=value(MainWorkCategory.witness),
        patrol=value(MainWorkCategory.patrol),
    )


async def split_main_work(
    readings: Sequence[FieldReading], planner: Planner | None = None
) -> SplitOutcome:
    """模型为主、规则兜底；两者都无法可靠完成时抛出 MainWorkSplitError。"""
    reading = next((item for item in readings if item.spec.key == "mainWork"), None)
    source_text = reading.value if reading is not None else ""
    if not source_text.strip():
        return SplitOutcome(MainWorkValues(), "empty", source_text, (), 0)

    segments = reading.segments if reading is not None else ()
    units = build_units(source_text, segments)
    if planner is not None and len(source_text) <= MAX_SPLIT_CHARACTERS:
        plan = await _plan(planner, units)
        if plan is not None:
            assignments = validate_plan(units, plan)
            if assignments is not None:
                return _outcome(
                    values=assemble(units, assignments),
                    units=units,
                    assignments=assignments,
                    strategy="llm",
                    source_text=source_text,
                )
            logger.warning("mainWork 分类结果未通过校验，改用标题规则")

    assignments = rule_assignments(units)
    if assignments is None:
        raise MainWorkSplitError("mainWork cannot be split reliably")
    return _outcome(
        values=assemble(units, assignments),
        units=units,
        assignments=assignments,
        strategy="rules",
        source_text=source_text,
    )


async def _plan(planner: Planner, units: tuple[MainWorkUnit, ...]) -> MainWorkSplitPlan | None:
    try:
        return await planner(MainWorkSplitRequest(units=units))
    except Exception as exc:  # noqa: BLE001 —— 模型边界；失败整体转规则
        # 只记录异常类型，不记录原文、单元或上游错误正文。
        logger.warning("mainWork 分类模型调用失败，改用标题规则（%s）", type(exc).__name__)
        return None


def _outcome(
    *,
    values: MainWorkValues,
    units: tuple[MainWorkUnit, ...],
    assignments: dict[str, MainWorkCategory],
    strategy: Literal["llm", "rules"],
    source_text: str,
) -> SplitOutcome:
    unknown_count = sum(
        1 for category in assignments.values() if category is MainWorkCategory.unknown
    )
    return SplitOutcome(values, strategy, source_text, units, unknown_count)


def _pieces(source_text: str, segments: Sequence[TextSegment]) -> list[Piece]:
    candidates = tuple(segment for segment in segments if segment.text and segment.start >= 0)
    if not candidates or any(
        source_text[segment.start : segment.start + len(segment.text)] != segment.text
        for segment in candidates
    ):
        candidates = (TextSegment(text=source_text, start=0, end=len(source_text)),)

    pieces: list[Piece] = []
    for segment in candidates:
        text = segment.text
        heading = _heading(text)
        if heading is None:
            pieces.extend(_sentences(text, segment.start))
            continue
        category, length = heading
        pieces.append((text[:length], segment.start, True, category))
        pieces.extend(_sentences(text[length:], segment.start + length))
    return pieces


def _sentences(text: str, start: int) -> list[Piece]:
    """按强语句边界切分；分隔符归入前一个单元，不动逗号、小数点和时间。"""
    pieces: list[Piece] = []
    cursor = 0
    for index, char in enumerate(text):
        if char in STRONG_BOUNDARIES:
            pieces.append((text[cursor : index + 1], start + cursor, False, None))
            cursor = index + 1
    if cursor < len(text):
        pieces.append((text[cursor:], start + cursor, False, None))
    return pieces


def _merge_punctuation(pieces: Sequence[Piece]) -> list[Piece]:
    merged: list[Piece] = []
    pending: Piece | None = None
    for piece in pieces:
        text, start, heading, category = piece
        if not heading and not is_meaningful(text):
            if merged:
                previous = merged[-1]
                merged[-1] = (previous[0] + text, previous[1], previous[2], previous[3])
            else:
                pending = (
                    (text, start, False, None)
                    if pending is None
                    else (
                        pending[0] + text,
                        pending[1],
                        False,
                        None,
                    )
                )
            continue
        if pending is not None:
            text, start = pending[0] + text, pending[1]
            pending = None
        merged.append((text, start, heading, category))
    if pending is not None:
        if merged:
            previous = merged[-1]
            merged[-1] = (previous[0] + pending[0], previous[1], previous[2], previous[3])
        else:
            merged.append(pending)
    return merged


def _heading(text: str) -> tuple[MainWorkCategory, int] | None:
    """识别单元开头的可靠标题；返回类别与标题在原文中的结束位置。"""
    normalised, indices = _normalise(text)
    for alias, category in HEADING_ALIASES:
        if not normalised.startswith(alias):
            continue
        rest = normalised[len(alias) :]
        if not rest or all(_is_punctuation(char) for char in rest):
            return category, len(text)
        if rest[0] in HEADING_SEPARATORS:
            end = len(alias)
            while end < len(normalised) and normalised[end] in HEADING_SEPARATORS:
                end += 1
            return category, indices[end - 1] + 1
    return None


def _marker_assignments(
    units: Sequence[MainWorkUnit],
) -> dict[str, MainWorkCategory] | None:
    assignments: dict[str, MainWorkCategory] = {}
    for unit in units:
        category = _marker_category(unit.text)
        if category is None:
            if is_meaningful(unit.text) and not _is_container(unit.text):
                return None
            category = MainWorkCategory.unknown
        assignments[unit.unit_id] = category
    return assignments


def _marker_category(text: str) -> MainWorkCategory | None:
    normalised, _ = _normalise(text)
    for prefix, category in (
        ("旁站", MainWorkCategory.witness),
        ("巡视", MainWorkCategory.patrol),
        ("主要施工情况", MainWorkCategory.construction),
        ("施工情况", MainWorkCategory.construction),
    ):
        if normalised.startswith(prefix):
            return category
    return None


def _is_effective_unknown(unit: MainWorkUnit, category: MainWorkCategory) -> bool:
    return (
        category is MainWorkCategory.unknown
        and not unit.is_heading
        and is_meaningful(unit.text)
        and not _is_container(unit.text)
    )


def _is_container(text: str) -> bool:
    normalised, _ = _normalise(text)
    return normalised.rstrip(_TRAILING_PUNCTUATION) in CONTAINER_LABELS


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


def _normalise(text: str) -> tuple[str, list[int]]:
    """NFKC、去空白、去编号；同时记录归一字符到原文的下标。"""
    characters: list[str] = []
    indices: list[int] = []
    for index, char in enumerate(text):
        for folded in unicodedata.normalize("NFKC", char):
            if folded.isspace():
                continue
            characters.append(folded)
            indices.append(index)
    normalised = "".join(characters)
    match = _NUMBERING.match(normalised)
    if match:
        normalised = normalised[match.end() :]
        indices = indices[match.end() :]
    return normalised, indices
