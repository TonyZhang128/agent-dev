"""业务生成的关键数据保护、原文合并与取消语义。"""

import asyncio
from dataclasses import replace

import pytest

from app.errors import JournalGenerationError
from app.ocr.journal.generation import empty_work, generate_work, validate_work
from app.ocr.journal.models import FieldLayout, FieldReading, ValueSegment
from app.ocr.journal.output import merge_main_work


def readings(*blocks: str) -> list[FieldReading]:
    source = "".join(blocks)
    segments = []
    offset = 0
    for block in blocks:
        segments.append(ValueSegment(block, offset, offset + len(block)))
        offset += len(block)
    return [
        FieldReading(
            FieldLayout("main_work", "当日主要监理工作情况", (0, 0, 1, 1)),
            (),
            source,
            0.9,
            segments=tuple(segments),
        )
    ]


def work_with(text):
    work = empty_work()
    work.construction = text
    return work


@pytest.mark.parametrize(
    "source, changed",
    [
        ("高差-2m。", "高差2m。"),
        ("要求≥96%。", "要求96%。"),
        ("要求≤96%。", "要求≥96%。"),
        ("旁站8:30~16:30。", "旁站16:30~8:30。"),
        ("压实度95.8%～97.1%。", "压实度97.1%～95.8%。"),
        ("样品10mg。", "样品10g。"),
        ("长度10米。", "长度10厘米。"),
        ("强度10MPa。", "强度10mPa。"),
        ("K1+100填筑8层。", "K1+200填筑8层。"),
        ("K1+100填筑8层。", "K1+100填筑9层。"),
        ("K1+100填筑8层。", "K1+100填筑8米。"),
        ("K1+100填筑8层。", "K1+100已完成填筑8层。"),
        ("未进行旁站。", "进行了旁站。"),
        ("1、2号墩浇筑。", "2号墩浇筑。"),
        ("取样2组，每组3件。", "取样3组，每组2件。"),
    ],
)
def test_generation_rejects_changed_key_facts(source, changed):
    with pytest.raises(JournalGenerationError):
        validate_work(source, work_with(changed))


@pytest.mark.parametrize(
    "source, generated",
    [
        ("压实度95%-97%。", "压实度95%至97%。"),
        ("距离2米-3米。", "距离2米至3米。"),
        ("旁站08:\n30至16:30。", "旁站08:30至16:30。"),
        ("铺筑厚度20m\nm。", "铺筑厚度20mm。"),
        ("K3+280至K3+560段，高差-2m。", "K3 + 280 至 K3 + 560 段，高差 -2 m。"),
        ("检查1、2号墩。", "1、2号墩检查。"),
    ],
)
def test_generation_allows_equivalent_formatting(source, generated):
    validate_work(source, work_with(generated))


def test_repeated_location_and_rephrased_negation_are_allowed():
    work = work_with("K1+100填筑8层。")
    work.patrol.inspectionScope = "对K1+100进行巡视。"
    work.patrol.problemsAndActions = "没有发现松散和积水。"
    validate_work("K1+100填筑8层。巡视未见松散，未见积水。", work)


@pytest.mark.parametrize(
    "source, generated",
    [
        ("1、施工情况\n2、旁站情况\n3、巡视情况", None),
        ("1、施工情况：K3+280段路基填筑。", "K3+280段路基填筑。"),
    ],
)
def test_list_numbering_does_not_become_business_data(source, generated):
    validate_work(source, work_with(generated))


def test_location_suffix_is_not_a_new_measurement():
    validate_work("K6+210涵洞台背回填。", work_with("K6+210处进行涵洞台背回填。"))


@pytest.mark.parametrize("placeholder", ["unknown", "null", "无法判断"])
def test_placeholder_cannot_replace_content(placeholder):
    with pytest.raises(JournalGenerationError):
        validate_work("现场检查。", work_with(placeholder))


@pytest.mark.asyncio
async def test_model_failures_are_controlled_but_cancellation_propagates():
    async def fail(request):
        raise RuntimeError("private upstream body")

    with pytest.raises(JournalGenerationError) as captured:
        await generate_work("现场检查。", fail)
    assert "private" not in str(captured.value)

    async def cancel(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await generate_work("现场检查。", cancel)


def test_merging_ocr_segments_preserves_full_source():
    source = readings("K3+280左侧浆", "砌挡土墙。")
    assert merge_main_work(source) == "K3+280左侧浆\n砌挡土墙。"
    source[0] = replace(source[0], segments=())
    assert merge_main_work(source) == "K3+280左侧浆砌挡土墙。"
