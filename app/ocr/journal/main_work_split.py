"""完整mainWork先按关键词提取，不足时由Agent生成三部分；不保留单元ID分类旧路径。"""

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.errors import MainWorkSplitError
from app.ocr.journal.models import FieldReading
from app.schemas.ocr import MainWorkRequest, MainWorkValues

logger = logging.getLogger(__name__)
MAX_SPLIT_CHARACTERS = 4000

type MainWorkField = Literal["construction", "witness", "patrol"]
type MainWorkGenerator = Callable[[MainWorkRequest], Awaitable[MainWorkValues]]

_FIELD_NAMES: tuple[MainWorkField, ...] = ("construction", "witness", "patrol")
_HEADING = re.compile(r"(?:主要)?施工情况|旁站情况|巡视情况")
_NUMBERING = re.compile(r"(?:[（(]?[一二三四五六七八九十\d]+[)）.、])?")
_BOUNDARIES = "\n。；;：:！？!?"
_TRIM_PUNCTUATION = " \t\r\n：:、，,；;"
_OUTER_LABELS = ("当日主要监理工作情况", "主要监理工作情况")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SIGNED_NUMBER = re.compile(r"[-+]\s*\d+(?:\.\d+)?")
_COMPARISON = re.compile(r"(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)")
_CHAINAGE = re.compile(r"[Kk]\s*\d+\s*\+\s*\d+(?:\.\d+)?")
_TIME_RANGE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*(?:[~～—–-]|至|到)\s*(\d{1,2})\s*:\s*(\d{2})")
_PERCENT_RANGE = re.compile(r"(\d+(?:\.\d+)?)%\s*(?:[~～—–-]|至|到)\s*(\d+(?:\.\d+)?)%")
_UNIT = r"%?[A-Za-z°μ]+|%|立方米|平方米|千克|毫米|厘米|公里|分钟|小时|米|吨|克|层|点|次|天"
_MEASUREMENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?(" + _UNIT + r")")
_RANGE_PREFIX = re.compile(r"\d+(?:\.\d+)?\s*(?:" + _UNIT + r")?$")
# 仅拼合有明确单位依据的排版断行，保留大小写，不把相邻英文正文拼成单位。
_JOINABLE_UNITS = (
    "MPa",
    "mPa",
    "kPa",
    "GPa",
    "mm",
    "cm",
    "km",
    "kN",
    "kg",
    "mg",
    "min",
    "ms",
    "μm",
    "°C",
)
_NEGATION = re.compile(r"没有|未见|未|无|不")
_CONCLUSIONS = ("完成", "合格", "符合", "达标", "通过")
_PLACEHOLDERS = frozenset(
    {"unknown", "null", "none", "n/a", "无法判断", "无法识别", "无法分类", "未识别"}
)


@dataclass(frozen=True)
class Heading:
    """合并原文中的可靠关键词位置；不为普通短行预判类别。"""

    field: MainWorkField
    start: int
    end: int


@dataclass(frozen=True)
class SplitOutcome:
    """请求内保留策略和完整来源，不进入HTTP响应。"""

    values: MainWorkValues
    strategy: Literal["empty", "rules", "agent"]
    source_text: str


def merge_main_work(readings: Sequence[FieldReading]) -> str:
    """合并已排好阅读顺序的OCR片段；有问题的片段索引不能导致丢原文。"""
    reading = next((item for item in readings if item.layout.key == "main_work"), None)
    if reading is None:
        return ""
    source = reading.value.strip()
    if not source:
        return ""
    fragments = reading.segments
    if fragments and "".join(fragment.text for fragment in fragments) == source:
        return "\n".join(fragment.text for fragment in fragments if fragment.text).strip()
    return source


def _normalize_with_positions(text: str) -> tuple[str, list[int]]:
    letters, positions = [], []
    for offset, character in enumerate(text):
        for folded in unicodedata.normalize("NFKC", character):
            if not folded.isspace():
                letters.append(folded)
                positions.append(offset)
    return "".join(letters), positions


def _heading_boundaries(source: str) -> list[Heading]:
    normalized, positions = _normalize_with_positions(source)
    headings = []
    for match in _HEADING.finditer(normalized):
        start, end = positions[match.start()], positions[match.end() - 1] + 1
        # 允许标题与正文同框，但正文中提到“施工情况”等词不自动成为分界。
        boundary = max((source.rfind(mark, 0, start) for mark in _BOUNDARIES), default=-1) + 1
        prefix = unicodedata.normalize("NFKC", source[boundary:start]).strip()
        if not _NUMBERING.fullmatch(prefix):
            continue
        keyword = match.group()
        field: MainWorkField = (
            "construction" if "施工" in keyword else ("witness" if "旁站" in keyword else "patrol")
        )
        headings.append(Heading(field, boundary, end))
    return headings


def _has_business_content(text: str) -> bool:
    normalized, _ = _normalize_with_positions(_without_headings(text))
    cleaned = _HEADING.sub("", normalized)
    for label in _OUTER_LABELS:
        cleaned = cleaned.replace(label, "")
    return any(character.isalnum() for character in cleaned)


def _without_headings(text: str) -> str:
    """只删除可靠关键词及其标题序号，不能把1、2号墩等业务编号当元数据。"""
    for heading in reversed(_heading_boundaries(text)):
        text = text[: heading.start] + text[heading.end :]
    return text


def extract_by_keywords(source: str) -> MainWorkValues | None:
    """完整可靠的三个关键词才直接提取；少标题或有未覆盖前文交给Agent。"""
    if not _has_business_content(source):
        return MainWorkValues(construction=None, witness=None, patrol=None)
    headings = _heading_boundaries(source)
    if {heading.field for heading in headings} != set(_FIELD_NAMES):
        return None
    if _has_business_content(source[: headings[0].start]):
        return None
    bodies: dict[MainWorkField, list[str]] = {field: [] for field in _FIELD_NAMES}
    for index, heading in enumerate(headings):
        stop = headings[index + 1].start if index + 1 < len(headings) else len(source)
        body = source[heading.end : stop].strip(_TRIM_PUNCTUATION)
        if body:
            bodies[heading.field].append(body)
    return MainWorkValues(
        construction="\n".join(bodies["construction"]) or None,
        witness="\n".join(bodies["witness"]) or None,
        patrol="\n".join(bodies["patrol"]) or None,
    )


def _fact_text(text: str) -> str:
    """只统一比较符号和排版，标题编号不作为工程数量。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _without_headings(normalized).replace("−", "-")
    for unit in _JOINABLE_UNITS:
        spelling = r"\s*".join(re.escape(character) for character in unit)
        normalized = re.sub(
            r"(\d+(?:\.\d+)?)\s*" + spelling + r"(?![A-Za-zμ])",
            lambda match, unit=unit: match.group(1) + unit,
            normalized,
        )
    for equivalent, symbol in (
        ("不低于", ">="),
        ("不少于", ">="),
        ("大于等于", ">="),
        ("不高于", "<="),
        ("不超过", "<="),
        ("小于等于", "<="),
        ("≥", ">="),
        ("≤", "<="),
    ):
        normalized = normalized.replace(equivalent, symbol)
    return normalized


def validate_generated_values(source: str, values: MainWorkValues) -> None:
    """拦截可机械确认的数据改动；不把数字检查等同于全部事实已正确。"""
    content = "\n".join(
        text for text in (values.construction, values.witness, values.patrol) if text
    )
    if _has_business_content(source) and not content.strip():
        raise MainWorkSplitError("empty_generated_content")
    for text in (values.construction, values.witness, values.patrol):
        normalized = (text or "").strip(" \t\r\n。.!！?？").lower()
        if normalized in _PLACEHOLDERS and normalized not in source.lower():
            raise MainWorkSplitError("placeholder_generated_content")
    before, after = _fact_text(source), _fact_text(content)
    if Counter(_NUMBER.findall(before)) != Counter(_NUMBER.findall(after)):
        raise MainWorkSplitError("numeric_facts_changed")
    if _signed_numbers(before) != _signed_numbers(after):
        raise MainWorkSplitError("signed_facts_changed")
    if Counter(_COMPARISON.findall(before)) != Counter(_COMPARISON.findall(after)):
        raise MainWorkSplitError("comparison_facts_changed")
    if Counter(re.sub(r"\s", "", token).upper() for token in _CHAINAGE.findall(before)) != Counter(
        re.sub(r"\s", "", token).upper() for token in _CHAINAGE.findall(after)
    ):
        raise MainWorkSplitError("chainage_facts_changed")
    if Counter(_TIME_RANGE.findall(before)) != Counter(_TIME_RANGE.findall(after)):
        raise MainWorkSplitError("time_range_changed")
    if Counter(_PERCENT_RANGE.findall(before)) != Counter(_PERCENT_RANGE.findall(after)):
        raise MainWorkSplitError("percentage_range_changed")
    if Counter(_MEASUREMENT.findall(before)) != Counter(_MEASUREMENT.findall(after)):
        raise MainWorkSplitError("measurement_facts_changed")
    if len(_NEGATION.findall(before)) != len(_NEGATION.findall(after)):
        raise MainWorkSplitError("negation_changed")
    if any(term in after and term not in before for term in _CONCLUSIONS):
        raise MainWorkSplitError("new_conclusion")


def _signed_numbers(text: str) -> Counter[str]:
    """符号前跳过排版空白；桩号加号和数值区间连字符不误作正负号。"""
    signed: Counter[str] = Counter()
    for match in _SIGNED_NUMBER.finditer(text):
        prefix = text[: match.start()].rstrip()
        if prefix and _RANGE_PREFIX.search(prefix):
            continue
        signed[re.sub(r"\s", "", match.group())] += 1
    return signed


async def split_main_work(
    readings: Sequence[FieldReading], generator: MainWorkGenerator | None = None
) -> SplitOutcome:
    """先规则、后全文生成；无效结果明确失败，不复制整段或补写事实。"""
    source = merge_main_work(readings)
    if not _has_business_content(source):
        return SplitOutcome(
            MainWorkValues(construction=None, witness=None, patrol=None), "empty", source
        )
    extracted = extract_by_keywords(source)
    if extracted is not None:
        validate_generated_values(source, extracted)
        return SplitOutcome(extracted, "rules", source)
    if len(source) > MAX_SPLIT_CHARACTERS:
        raise MainWorkSplitError("main_work_too_long")
    if generator is None:
        raise MainWorkSplitError("main_work_generator_missing")
    try:
        generated = await generator(MainWorkRequest(main_work=source))
    except Exception as exc:  # noqa: BLE001 —— 语言模型边界；不记录业务原文或上游正文
        logger.warning("mainWork生成调用失败（%s）", type(exc).__name__)
        raise MainWorkSplitError("main_work_generation_failed") from exc
    try:
        validate_generated_values(source, generated)
    except MainWorkSplitError as exc:
        logger.warning("mainWork生成结果未通过数据校验（%s）", str(exc))
        raise
    return SplitOutcome(generated, "agent", source)
