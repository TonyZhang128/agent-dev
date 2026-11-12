"""以完整 OCR 栏目生成业务日记；不再提供关键词提取或规则直接输出。"""

import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Awaitable, Callable

from app.errors import JournalGenerationError
from app.schemas.ocr import (
    JournalCommon,
    JournalData,
    JournalFields,
    JournalPatrol,
    JournalProcessRequest,
    JournalResponse,
    JournalResponseData,
    JournalTextRequest,
    JournalWitness,
    JournalWork,
    JournalWorkValues,
)

logger = logging.getLogger(__name__)
# 沿用既有模型输入保护，不截断后生成。
MAX_JOURNAL_CHARACTERS = 4000

type JournalGenerator = Callable[[JournalTextRequest], Awaitable[JournalWorkValues]]

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
# 只忽略行首列表序号，不识别业务标题；“1、2号墩”和小数不能被当成序号。
_LIST_PREFIX = re.compile(r"(?m)^[ \t]*\d+[、.][ \t]*(?=[^\d\s])")
_SIGNED_NUMBER = re.compile(r"[-+]\s*\d+(?:\.\d+)?")
_COMPARISON = re.compile(r"(>=|<=|>|<|=)\s*(\d+(?:\.\d+)?)")
_CHAINAGE = re.compile(r"[Kk]\s*\d+\s*\+\s*\d+(?:\.\d+)?")
_TIME_RANGE = re.compile(r"(\d{1,2})\s*:\s*(\d{2})\s*(?:[~～—–-]|至|到)\s*(\d{1,2})\s*:\s*(\d{2})")
_PERCENT_RANGE = re.compile(r"(\d+(?:\.\d+)?)%\s*(?:[~～—–-]|至|到)\s*(\d+(?:\.\d+)?)%")
_UNIT = r"%?[A-Za-z°μ]+|%|立方米|平方米|千克|毫米|厘米|公里|分钟|小时|米|吨|克|层|点|次|天|组|件|处|台|人|遍"
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


def _fact_text(text: str) -> str:
    """只统一比较符号和排版，标题编号不作为工程数量。"""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("−", "-")
    normalized = _LIST_PREFIX.sub("", normalized)
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


def _signed_numbers(text: str) -> Counter[str]:
    """符号前跳过排版空白；桩号加号和数值区间连字符不误作正负号。"""
    signed: Counter[str] = Counter()
    for match in _SIGNED_NUMBER.finditer(text):
        prefix = text[: match.start()].rstrip()
        if prefix and _RANGE_PREFIX.search(prefix):
            continue
        signed[re.sub(r"\s", "", match.group())] += 1
    return signed


def empty_work() -> JournalWorkValues:
    """保持两个业务对象和全部子键，缺失信息显式为空。"""
    return JournalWorkValues(
        construction=None,
        patrol=JournalPatrol(
            inspectionScope=None,
            mainConstruction=None,
            qualitySafetyEnvironment=None,
            problemsAndActions=None,
        ),
        witness=JournalWitness(
            supervisionProject=None,
            constructionProcess=None,
            supervisionWork=None,
            mainDataRecords=None,
            problemsAndResults=None,
        ),
    )


def generated_text(work: JournalWorkValues) -> str:
    """只收集模型生成字段，禁止将原文回显混入事实检查。"""
    fields = [
        work.construction,
        *work.patrol.model_dump().values(),
        *work.witness.model_dump().values(),
    ]
    return "\n".join(text for text in fields if isinstance(text, str) and text)


def validate_work(source: str, work: JournalWorkValues) -> None:
    """核对可机械识别的关键数据；语义正确性仍需业务样本独立验收。"""
    content = generated_text(work)
    for text in content.splitlines():
        normalized = text.strip(" \t\r\n。.!！?？").lower()
        if normalized in _PLACEHOLDERS and normalized not in source.lower():
            raise JournalGenerationError("placeholder_generated_content")
    before, after = _fact_text(source), _fact_text(content)
    checks = (
        (_NUMBER, "numeric_facts_changed"),
        (_COMPARISON, "comparison_facts_changed"),
        (_TIME_RANGE, "time_range_changed"),
        (_PERCENT_RANGE, "percentage_range_changed"),
    )
    for pattern, reason in checks:
        if set(pattern.findall(before)) != set(pattern.findall(after)):
            raise JournalGenerationError(reason)
    # 桩号单独核对；“K6+210处”中的“处”是位置后缀，不是新增 210 处工程量。
    if set(_MEASUREMENT.findall(_CHAINAGE.sub("", before))) != set(
        _MEASUREMENT.findall(_CHAINAGE.sub("", after))
    ):
        raise JournalGenerationError("measurement_facts_changed")
    if set(_signed_numbers(before)) != set(_signed_numbers(after)):
        raise JournalGenerationError("signed_facts_changed")
    if {re.sub(r"\s", "", token).upper() for token in _CHAINAGE.findall(before)} != {
        re.sub(r"\s", "", token).upper() for token in _CHAINAGE.findall(after)
    }:
        raise JournalGenerationError("chainage_facts_changed")
    if content and _NEGATION.search(before) and not _NEGATION.search(after):
        raise JournalGenerationError("negation_lost")
    if any(term in after and term not in before for term in _CONCLUSIONS):
        raise JournalGenerationError("new_conclusion")


async def generate_work(source: str, generator: JournalGenerator) -> JournalWorkValues:
    """非空白文本只通过 Agent 生成；模型异常转为受控错误，取消信号保留。"""
    if not source.strip():
        return empty_work()
    if len(source) > MAX_JOURNAL_CHARACTERS:
        raise JournalGenerationError("journal_content_too_long")
    try:
        work = await generator(JournalTextRequest(content=source))
    except Exception as exc:  # noqa: BLE001 —— 模型边界，不记录原文或上游正文
        logger.warning("监理日记生成调用失败（%s）", type(exc).__name__)
        raise JournalGenerationError("journal_generation_failed") from exc
    validate_work(source, work)
    return work


async def generate_journal(
    recognition: JournalProcessRequest, generator: JournalGenerator
) -> JournalResponse:
    """按已校验栏目映射业务字段；只将工作原文传入 Agent，不修改输入。"""
    columns = {field.key: field.text for field in recognition.fields}
    source = columns["main_work"] or ""
    work = await generate_work(source, generator)
    common = JournalCommon(
        projectName=columns["project"],
        documentNo=columns["number"],
        supervisionOrg=columns["supervision_org"],
        recorderName=columns["recorder"],
        recorderPosition=columns["position"],
        weather=columns["weather"],
        logDate=columns["date"],
        reviewerName=columns["reviewer"],
    )
    fields = JournalFields(
        mainWork=JournalWork(content=source, **work.model_dump()),
        issues=columns["issues"],
        nextDayPlan=columns["next_day_plan"],
    )
    return JournalResponse(
        code=200,
        message="success",
        data=JournalResponseData(jsonData=JournalData(common=common, fields=fields)),
    )
