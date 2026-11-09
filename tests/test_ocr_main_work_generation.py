"""合并原文、关键词规则及全文生成兜底；不以单元ID分类替代新行为。"""

import asyncio

import pytest

from app.errors import MainWorkSplitError
from app.ocr.journal import main_work_split as split
from app.ocr.journal.models import FieldLayout, FieldReading, ValueSegment
from app.schemas.ocr import MainWorkValues


@pytest.mark.asyncio
@pytest.mark.parametrize("placeholder", ["unknown", "null", "无法判断"])
async def test_generation_cannot_present_placeholder_as_completed_content(placeholder):
    async def generate(request):
        return MainWorkValues(construction=placeholder, witness=None, patrol=None)

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings("检查现场无问题。"), generate)


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


async def unexpected_generator(request):
    raise AssertionError("完整关键词应由规则完成")


@pytest.mark.asyncio
async def test_keywords_extract_body_without_titles_or_model():
    outcome = await split.split_main_work(
        readings(
            "主要施工情况K1+100段填筑8层。", "旁站情况：旁站碾压，抽检4点。", "巡视情况：未见松散。"
        ),
        unexpected_generator,
    )
    assert outcome.strategy == "rules"
    assert outcome.values == MainWorkValues(
        construction="K1+100段填筑8层。", witness="旁站碾压，抽检4点。", patrol="未见松散。"
    )


@pytest.mark.asyncio
async def test_short_body_and_split_keyword_do_not_block_rules():
    outcome = await split.split_main_work(
        readings("施工情况", "验收合格", "旁站情况", "未进行旁站。", "巡", "视情况", "检查排水。"),
        unexpected_generator,
    )
    assert outcome.values.construction == "验收合格"
    assert outcome.values.patrol == "检查排水。"


@pytest.mark.asyncio
async def test_reordered_repeated_sections_keep_every_record():
    outcome = await split.split_main_work(
        readings(
            "巡视情况：检查A段。",
            "施工情况：填筑B段。",
            "旁站情况：旁站C段。",
            "巡视情况：检查D段。",
        ),
        unexpected_generator,
    )
    assert outcome.values.patrol == "检查A段。\n检查D段。"


@pytest.mark.asyncio
async def test_heading_numbering_is_not_business_data():
    outcome = await split.split_main_work(
        readings(
            "一、施工情况",
            "旁站以外的施工记录。",
            "2.旁站情况",
            "未进行旁站。",
            "（三）巡视情况",
            "检查合格。",
        ),
        unexpected_generator,
    )
    assert outcome.values.construction == "旁站以外的施工记录。"
    assert outcome.values.patrol == "检查合格。"
    empty = await split.split_main_work(
        readings("1.施工情况", "二、旁站情况", "3.巡视情况"), unexpected_generator
    )
    assert empty.values == MainWorkValues(construction=None, witness=None, patrol=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source, changed",
    [
        ("高差-2m。", "高差2m。"),
        ("要求≥96%。", "要求96%。"),
        ("要求≤96%。", "要求≥96%。"),
    ],
)
async def test_generation_preserves_sign_and_comparison(source, changed):
    async def generate(request):
        return MainWorkValues(construction=changed, witness=None, patrol=None)

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings(source), generate)


@pytest.mark.asyncio
async def test_generation_may_add_spacing_around_key_data():
    async def generate(request):
        return MainWorkValues(
            construction="K3 + 280 至 K3 + 560 段，高差 -2 m。", witness=None, patrol=None
        )

    outcome = await split.split_main_work(readings("K3+280至K3+560段，高差-2m。"), generate)
    assert outcome.values.construction == "K3 + 280 至 K3 + 560 段，高差 -2 m。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source, changed",
    [
        ("旁站8:30~16:30。", "旁站16:30~8:30。"),
        ("压实度95.8%～97.1%。", "压实度97.1%～95.8%。"),
    ],
)
async def test_generation_cannot_reverse_time_or_percentage_range(source, changed):
    async def generate(request):
        return MainWorkValues(construction=None, witness=changed, patrol=None)

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings(source), generate)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source, changed",
    [
        ("样品10mg。", "样品10g。"),
        ("长度10米。", "长度10厘米。"),
        ("强度10MPa。", "强度10mPa。"),
    ],
)
async def test_generation_cannot_change_unlisted_unit_or_unit_case(source, changed):
    async def generate(request):
        return MainWorkValues(construction=changed, witness=None, patrol=None)

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings(source), generate)


def test_pier_identifier_is_not_removed_as_list_numbering():
    with pytest.raises(MainWorkSplitError, match="numeric_facts_changed"):
        split.validate_generated_values(
            "1、2号墩浇筑。", MainWorkValues(construction="2号墩浇筑。", witness=None, patrol=None)
        )
    split.validate_generated_values(
        "检查1、2号墩。", MainWorkValues(construction="1、2号墩检查。", witness=None, patrol=None)
    )


@pytest.mark.asyncio
async def test_inline_numbered_headings_pass_rule_validation():
    outcome = await split.split_main_work(
        readings("1.施工情况：填筑。2.旁站情况：旁站。3.巡视情况：检查。"), unexpected_generator
    )
    assert outcome.strategy == "rules"
    assert outcome.values == MainWorkValues(
        construction="填筑。", witness="旁站。", patrol="检查。"
    )


@pytest.mark.parametrize(
    "source, generated",
    [
        ("压实度95%-97%。", "压实度95%至97%。"),
        ("距离2米-3米。", "距离2米至3米。"),
        ("旁站08:\n30至16:30。", "旁站08:30至16:30。"),
        ("铺筑厚度20m\nm。", "铺筑厚度20mm。"),
    ],
)
def test_equivalent_range_and_ocr_data_line_breaks_are_allowed(source, generated):
    split.validate_generated_values(
        source, MainWorkValues(construction=generated, witness=None, patrol=None)
    )


@pytest.mark.asyncio
async def test_model_length_guard_does_not_call_generator():
    calls = []

    async def generate(request):
        calls.append(request)
        return MainWorkValues(construction=request.main_work, witness=None, patrol=None)

    with pytest.raises(MainWorkSplitError, match="too_long"):
        await split.split_main_work(readings("正文" * split.MAX_SPLIT_CHARACTERS), generate)
    assert not calls


def test_business_mentions_are_not_keyword_headings():
    assert split.extract_by_keywords("核对施工情况，讨论旁站情况及巡视情况。") is None


@pytest.mark.asyncio
async def test_incomplete_rules_send_merged_full_text_to_generator():
    calls = []

    async def generate(request):
        calls.append(request.model_dump())
        return MainWorkValues(
            construction="K3+850左侧浆砌挡土墙。",
            witness="旁站碾压。",
            patrol="砂浆饱满，未见松散。",
        )

    outcome = await split.split_main_work(
        readings(
            "施工情况K3+850左侧浆",
            "砌挡土墙。",
            "旁站情况旁站碾压。",
            "《视情况",
            "砂浆饱满，未见松散。",
        ),
        generate,
    )
    assert len(calls) == 1
    assert set(calls[0]) == {"main_work"}
    assert "K3+850左侧浆\n砌挡土墙。" in calls[0]["main_work"]
    assert outcome.strategy == "agent"
    assert outcome.values.patrol == "砂浆饱满，未见松散。"


@pytest.mark.asyncio
async def test_uncovered_prefix_and_missing_category_go_to_generator():
    calls = []

    async def generate(request):
        calls.append(request.main_work)
        return MainWorkValues(construction="完成放样。路基填筑。", witness=None, patrol=None)

    outcome = await split.split_main_work(readings("完成放样。", "施工情况：路基填筑。"), generate)
    assert calls == ["完成放样。\n施工情况：路基填筑。"]
    assert outcome.values.witness is None and outcome.values.patrol is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "generated",
    [
        MainWorkValues(construction="K1+200填筑8层。", witness=None, patrol=None),
        MainWorkValues(construction="K1+100填筑9层。", witness=None, patrol=None),
        MainWorkValues(construction="K1+100填筑8米。", witness=None, patrol=None),
        MainWorkValues(construction="K1+100已完成填筑8层。", witness=None, patrol=None),
        MainWorkValues(construction=None, witness=None, patrol=None),
    ],
)
async def test_generation_cannot_change_key_data_or_invent_completion(generated):
    async def generate(request):
        return generated

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings("K1+100填筑8层。"), generate)


@pytest.mark.asyncio
async def test_generation_preserves_negation():
    async def generate(request):
        return MainWorkValues(construction=None, witness="进行了旁站。", patrol=None)

    with pytest.raises(MainWorkSplitError):
        await split.split_main_work(readings("未进行旁站。"), generate)


@pytest.mark.asyncio
async def test_generation_may_rephrase_without_summary_or_new_data():
    async def generate(request):
        return MainWorkValues(
            construction="K1+100段进行了8层路基填筑。", witness="未开展旁站。", patrol=None
        )

    outcome = await split.split_main_work(
        readings("K1+100段路基填筑8层。", "未进行旁站。"), generate
    )
    assert outcome.values.construction == "K1+100段进行了8层路基填筑。"


@pytest.mark.asyncio
async def test_empty_main_work_and_heading_only_content_do_not_call_model():
    for source in (readings(""), readings("施工情况", "旁站情况", "巡视情况")):
        outcome = await split.split_main_work(source, unexpected_generator)
        assert outcome.values == MainWorkValues(construction=None, witness=None, patrol=None)


@pytest.mark.asyncio
async def test_model_failure_is_explicit_and_cancellation_is_not_swallowed():
    async def fail(request):
        raise RuntimeError("private upstream body")

    with pytest.raises(MainWorkSplitError) as captured:
        await split.split_main_work(readings("检查现场情况。"), fail)
    assert "private" not in str(captured.value)

    async def cancel(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await split.split_main_work(readings("检查现场情况。"), cancel)
