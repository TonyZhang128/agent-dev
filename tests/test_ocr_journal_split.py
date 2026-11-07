"""mainWork 拆分的纯规则、校验与组装测试；不调用模型、不读取照片。"""

import asyncio

import pytest

from app.ocr.journal import split
from app.ocr.journal.spec import FIELD_SPECS
from app.ocr.journal.types import FieldReading, TextSegment
from app.schemas.ocr import (
    MainWorkAssignment,
    MainWorkCategory,
    MainWorkSplitPlan,
)


def units_for(*texts: str):
    """把若干 OCR 文字框拼成 source_text，并按框边界构造位置片段。"""
    source = "".join(texts)
    segments = []
    offset = 0
    for text in texts:
        segments.append(TextSegment(text=text, start=offset, end=offset + len(text)))
        offset += len(text)
    return source, split.build_units(source, tuple(segments))


def plan_for(units, mapping: dict[str, str]) -> MainWorkSplitPlan:
    return MainWorkSplitPlan(
        assignments=[
            MainWorkAssignment(
                unit_id=unit.unit_id, category=MainWorkCategory(mapping[unit.unit_id])
            )
            for unit in units
        ]
    )


def readings(value: str, segments: tuple[TextSegment, ...] = ()) -> list[FieldReading]:
    return [
        FieldReading(
            spec=FIELD_SPECS[8],
            boxes=(),
            value=value,
            conf=0.9,
            segments=segments,
        )
    ]


def test_standard_headings_split_into_three_original_values():
    source, units = units_for(
        "主要施工情况",
        "K3+280段路基填筑。",
        "旁站情况",
        "旁站路基碾压。",
        "巡视情况",
        "巡视挡土墙砌筑。",
    )

    assignments = split.rule_assignments(units)

    assert assignments is not None
    values = split.assemble(units, assignments)
    assert values.construction == "主要施工情况K3+280段路基填筑。"
    assert values.witness == "旁站情况旁站路基碾压。"
    assert values.patrol == "巡视情况巡视挡土墙砌筑。"


def test_missing_categories_are_null_and_heading_only_sections_are_null():
    _source, units = units_for("主要施工情况", "K3+280段路基填筑。", "旁站情况")

    assignments = split.rule_assignments(units)

    assert assignments is not None
    values = split.assemble(units, assignments)
    assert values.construction == "主要施工情况K3+280段路基填筑。"
    assert values.witness is None
    assert values.patrol is None


def test_headings_may_appear_out_of_order():
    _source, units = units_for(
        "巡视情况",
        "巡视挡土墙砌筑。",
        "主要施工情况",
        "K3+280段路基填筑。",
    )

    assignments = split.rule_assignments(units)
    values = split.assemble(units, assignments)

    assert values.patrol == "巡视情况巡视挡土墙砌筑。"
    assert values.construction == "主要施工情况K3+280段路基填筑。"
    assert values.witness is None


def test_repeated_heading_keeps_original_order():
    _source, units = units_for(
        "主要施工情况",
        "第一段填筑。",
        "旁站情况",
        "旁站碾压。",
        "主要施工情况",
        "第二段填筑。",
    )

    assignments = split.rule_assignments(units)
    values = split.assemble(units, assignments)

    assert values.construction == "主要施工情况第一段填筑。主要施工情况第二段填筑。"
    assert values.witness == "旁站情况旁站碾压。"


@pytest.mark.parametrize(
    "heading",
    ["1. 主要施工情况", "一、旁站情况", "（1）巡视情况", "主要施工情况：", "旁站 情况"],
)
def test_numbered_and_punctuated_headings_are_recognised(heading):
    _source, units = units_for(heading, "原文正文。")

    assignments = split.rule_assignments(units)

    assert assignments is not None
    assert len(assignments) == len(units)


def test_heading_glued_to_body_with_colon_is_split_from_body():
    _source, units = units_for("旁站情况：旁站路基碾压。")

    assert [unit.is_heading for unit in units] == [True, False]
    assert units[0].text == "旁站情况："
    values = split.assemble(units, split.rule_assignments(units))
    assert values.witness == "旁站情况：旁站路基碾压。"


def test_markers_are_used_when_no_reliable_heading_exists():
    _source, units = units_for(
        "主要施工情况K3+280段路基填筑。",
        "旁站记录路基碾压。",
        "巡视检查挡土墙。",
    )

    assignments = split.rule_assignments(units)

    assert assignments is not None
    values = split.assemble(units, assignments)
    assert values.construction == "主要施工情况K3+280段路基填筑。"
    assert values.witness == "旁站记录路基碾压。"
    assert values.patrol == "巡视检查挡土墙。"


def test_heading_alias_inside_a_sentence_is_not_a_heading():
    _source, units = units_for("记录旁站情况后继续检查。")

    assert split.rule_assignments(units) is None


def test_mixed_sentence_without_heading_or_marker_cannot_be_rule_split():
    _source, units = units_for("对K3+280段进行了旁站和巡视。")

    assert split.rule_assignments(units) is None


def test_leading_body_before_first_heading_is_not_silently_dropped():
    _source, units = units_for("K3+280段路基填筑。", "主要施工情况", "第二段填筑。")

    assert split.rule_assignments(units) is None


def test_container_label_is_structural_and_not_written_to_fields():
    _source, units = units_for(
        "当日主要监理工作情况",
        "主要施工情况",
        "K3+280段路基填筑。",
    )

    assignments = split.rule_assignments(units)

    assert assignments is not None
    values = split.assemble(units, assignments)
    assert values.construction == "主要施工情况K3+280段路基填筑。"


def test_negation_and_duplicate_records_are_preserved():
    source, units = units_for("旁站情况", "未进行旁站。", "巡视情况", "巡视检查。", "巡视检查。")

    assignments = split.rule_assignments(units)
    values = split.assemble(units, assignments)

    assert values.witness == "旁站情况未进行旁站。"
    assert values.patrol == "巡视情况巡视检查。巡视检查。"
    assert "".join(unit.text for unit in units) == source


def test_numbers_units_chainage_and_time_ranges_are_not_split():
    source, units = units_for("主要施工情况", "K3+280段压实度95.5%，8:30-17:00完成。")

    body_units = [unit for unit in units if not unit.is_heading]
    assert len(body_units) == 1
    values = split.assemble(units, split.rule_assignments(units))
    assert values.construction == source


def test_punctuation_only_units_are_merged_into_their_neighbour():
    _source, units = units_for("主要施工情况", "。", "K3+280段路基填筑。")

    assert all(split.is_meaningful(unit.text) for unit in units)
    assert "".join(unit.text for unit in units) == "主要施工情况。K3+280段路基填筑。"


def test_units_always_reconstruct_source_text():
    source, units = units_for("旁站情况", "旁站路基碾压；", "K3+280。", "巡视情况", "巡视检查！")

    assert "".join(unit.text for unit in units) == source
    assert [unit.unit_id for unit in units] == [f"u{index}" for index in range(1, len(units) + 1)]


def test_missing_segments_fall_back_to_the_whole_source_text():
    units = split.build_units("主要施工情况K3+280段路基填筑。", ())

    assert len(units) == 1
    assert units[0].text == "主要施工情况K3+280段路基填筑。"


def test_validate_plan_accepts_a_complete_consistent_plan():
    _source, units = units_for("主要施工情况", "K3+280段路基填筑。")
    mapping = {unit.unit_id: "construction" for unit in units}

    assert split.validate_plan(units, plan_for(units, mapping)) is not None


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "invented"])
def test_validate_plan_rejects_incomplete_or_invented_ids(mutation):
    _source, units = units_for("主要施工情况", "K3+280段路基填筑。")
    assignments = [
        MainWorkAssignment(unit_id=unit.unit_id, category=MainWorkCategory.construction)
        for unit in units
    ]
    if mutation == "missing":
        assignments.pop()
    elif mutation == "duplicate":
        assignments.append(assignments[0])
    else:
        assignments.append(
            MainWorkAssignment(unit_id="u99", category=MainWorkCategory.construction)
        )

    assert split.validate_plan(units, MainWorkSplitPlan(assignments=assignments)) is None


def test_heading_range_must_match_the_heading_category():
    _source, units = units_for("主要施工情况", "K3+280段路基填筑。")
    plan = MainWorkSplitPlan(
        assignments=[
            MainWorkAssignment(unit_id="u1", category=MainWorkCategory.construction),
            MainWorkAssignment(unit_id="u2", category=MainWorkCategory.witness),
        ]
    )

    assert split.validate_plan(units, plan) is None


def test_effective_unknown_rejects_the_whole_plan_but_container_labels_do_not():
    _source, units = units_for("主要施工情况", "未说明对象。")
    unknown_plan = plan_for(units, {"u1": "construction", "u2": "unknown"})
    assert split.validate_plan(units, unknown_plan) is None

    _source, units = units_for("当日主要监理工作情况", "主要施工情况", "K3+280段路基填筑。")
    container_plan = plan_for(units, {"u1": "unknown", "u2": "construction", "u3": "construction"})
    assert split.validate_plan(units, container_plan) is not None


def test_unknown_categories_never_reach_the_values():
    _source, units = units_for("主要施工情况", "K3+280段路基填筑。")

    values = split.assemble(units, {unit.unit_id: MainWorkCategory.unknown for unit in units})

    assert values.construction is None
    assert values.witness is None
    assert values.patrol is None


@pytest.mark.asyncio
async def test_split_uses_the_model_plan_when_it_is_complete():
    calls = []

    async def planner(request):
        calls.append(request)
        return plan_for(request.units, {unit.unit_id: "patrol" for unit in request.units})

    outcome = await split.split_main_work(readings("巡视情况巡视检查。"), planner)

    assert outcome.strategy == "llm"
    assert outcome.values.patrol == "巡视情况巡视检查。"
    assert outcome.values.construction is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_split_falls_back_to_rules_when_the_model_fails():
    async def planner(request):
        raise TimeoutError

    outcome = await split.split_main_work(readings("巡视情况巡视检查。"), planner)

    assert outcome.strategy == "rules"
    assert outcome.values.patrol == "巡视情况巡视检查。"


@pytest.mark.asyncio
async def test_split_raises_a_controlled_error_when_rules_also_fail():
    async def planner(request):
        raise TimeoutError

    with pytest.raises(split.MainWorkSplitError):
        await split.split_main_work(readings("对K3+280段进行了旁站和巡视。"), planner)


@pytest.mark.asyncio
async def test_empty_main_work_never_calls_the_model():
    calls = []

    async def planner(request):
        calls.append(request)
        return plan_for(request.units, {})

    outcome = await split.split_main_work(readings("   "), planner)

    assert outcome.strategy == "empty"
    assert outcome.values == split.MainWorkValues()
    assert calls == []


@pytest.mark.asyncio
async def test_overlong_text_skips_the_model_and_uses_rules():
    calls = []
    text = "旁站情况：" + "填筑。" * (split.MAX_SPLIT_CHARACTERS // 3 + 1)

    async def planner(request):
        calls.append(request)
        return plan_for(request.units, {})

    outcome = await split.split_main_work(readings(text), planner)

    assert calls == []
    assert outcome.strategy == "rules"
    assert outcome.values.witness == text


@pytest.mark.asyncio
async def test_split_does_not_swallow_cancellation():
    async def planner(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await split.split_main_work(readings("巡视情况巡视检查。"), planner)
