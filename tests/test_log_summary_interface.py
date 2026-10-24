"""Keep the supplied system input and published response contract consistent."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import LogSummary, LogSummaryRequest
from tests.helpers import request_payload

ROOT = Path(__file__).parents[1]
INTERFACE = ROOT / "interfaces/log_summary"


def test_data_contains_only_the_supplied_system_input():
    content = json.loads((ROOT / "data/log_summary.json").read_text(encoding="utf-8"))
    assert content == {
        "项目编号": "20240721LDZSM",
        "项目名称": "泸定至石棉高速公路工程项目",
        "表格类型": "JB12-4.2.2",
        "表格名称": "土方路基抽检记录表",
        "开工类型": None,
        "监理单位标段": "JL2",
        "监理单位名称": "四川公路工程咨询监理有限公司",
        "施工单位标段": "TJ9",
        "施工单位名称": "四川省交通建设集团有限责任公司",
        "抽检人": "任伟",
        "计划开始日期": "2024年10月25日",
        "分部工程": {"工程名称": "土方路基", "前桩号": "K86+300", "后桩号": "K86+660"},
        "fields": [
            {
                "key": "△压实度(%)",
                "norm": "△压实度(%)",
                "specified": "满足设计要求",
                "measured": [95.2, 94.8, 96.1],
                "pass_rate": 100,
            },
            {
                "key": "△弯沉（0.01mm）",
                "norm": "△弯沉(0.01mm)",
                "specified": "≤设计验收弯沉值",
                "measured": [0.1, 0.2, 0.3],
                "pass_rate": None,
            },
            {
                "key": "宽 度（mm）",
                "norm": "宽度(mm)",
                "specified": "满足设计要求",
                "measured": [1000, 1005, 1010],
                "pass_rate": None,
            },
        ],
    }
    assert LogSummaryRequest(**request_payload({"content": content})).content == content


def test_published_response_schema_matches_the_producer():
    schema = json.loads((INTERFACE / "response.schema.json").read_text(encoding="utf-8"))
    assert schema == LogSummary.model_json_schema()
    assert set(schema["properties"]) == {
        "title",
        "date",
        "summary",
        "completed_items",
        "pending_items",
        "issues",
    }
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "unexpected"},
        {"summary": ""},
        {"date": 20241025},
        {"completed_items": None},
        {"pending_items": "待确认"},
        {"issues": [""]},
    ],
)
def test_fixed_response_rejects_incompatible_fields(change):
    example = json.loads((INTERFACE / "response.example.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        LogSummary.model_validate(example | change)


def test_response_example_is_valid_and_does_not_invent_a_date_or_status():
    example = json.loads((INTERFACE / "response.example.json").read_text(encoding="utf-8"))
    result = LogSummary.model_validate(example)
    assert result.date is None
    assert result.completed_items == result.pending_items == result.issues == []
    assert "泸定至石棉高速公路工程项目" in result.summary
    assert "0.1、0.2、0.3（单位0.01mm）" in result.summary
