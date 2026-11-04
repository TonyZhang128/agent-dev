"""业务目录是唯一数据源，生成结果和内容哈希必须保持同步。"""

import json

import pytest
from pydantic import ValidationError

from app.schemas.intent_catalog_generated import ACTION_CODES, ACTIONS_BY_PAGE
from scripts.intent.catalog import (
    CATALOG_PATH,
    GENERATED_PATH,
    IntentCatalog,
    catalog_version,
    load_and_render,
    load_catalog,
)


def test_catalog_matches_generated_module():
    rendered, version = load_and_render()
    assert GENERATED_PATH.read_text(encoding="utf-8") == rendered
    assert version in rendered


def test_catalog_codes_are_derived_from_json():
    catalog, _ = load_catalog()
    assert tuple(catalog.page_codes) == tuple(ACTIONS_BY_PAGE)
    assert tuple(catalog.action_codes) == ACTION_CODES
    assert set(catalog.action_codes) == {
        action for actions in catalog.actions_by_page.values() for action in actions
    }


def test_catalog_counts_and_hierarchy():
    catalog, _ = load_catalog()
    assert len(catalog.pages) == 6
    assert len(catalog.action_codes) == 31
    assert catalog.actions_by_page["supervision_diary"] == (
        "fill_supervision_log",
        "fill_monthly_report",
        "assign_monthly_report",
        "view_supervision_log",
        "fill_inspection_record",
        "fill_standby_record",
        "fill_environmental_log",
        "fill_safety_log",
        "approve_log",
    )
    assert catalog.page_by_action["view_wbs"] == "business_management"


def test_catalog_version_is_content_hash_and_ignores_formatting():
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    pretty = json.loads(json.dumps(data, ensure_ascii=False, indent=2))
    assert catalog_version(data) == catalog_version(pretty)
    changed = json.loads(json.dumps(data))
    changed["pages"][0]["name"] = "changed"
    assert catalog_version(data) != catalog_version(changed)


@pytest.mark.parametrize(
    "payload",
    [
        {"pages": []},
        {
            "pages": [
                {
                    "id": 1,
                    "code": "page_a",
                    "name": "A",
                    "actions": [{"id": 2, "code": "act", "name": "动作"}],
                },
                {
                    "id": 3,
                    "code": "page_a",
                    "name": "A2",
                    "actions": [{"id": 4, "code": "act2", "name": "动作2"}],
                },
            ]
        },
        {
            "pages": [
                {
                    "id": 1,
                    "code": "page_a",
                    "name": "A",
                    "actions": [{"id": 2, "code": "act", "name": "动作"}],
                },
                {
                    "id": 3,
                    "code": "page_b",
                    "name": "B",
                    "actions": [{"id": 4, "code": "act", "name": "动作2"}],
                },
            ]
        },
        {
            "pages": [
                {
                    "id": 1,
                    "code": "page_a",
                    "name": "A",
                    "actions": [{"id": 2, "code": "chat", "name": "动作"}],
                }
            ]
        },
        {
            "pages": [
                {
                    "id": 1,
                    "code": "page_a",
                    "name": "A",
                    "actions": [{"id": 1, "code": "act", "name": "动作"}],
                }
            ]
        },
    ],
    ids=["empty", "duplicate-page", "duplicate-action", "reserved", "duplicate-id"],
)
def test_catalog_rejects_invalid_data(payload):
    with pytest.raises(ValidationError):
        IntentCatalog.model_validate(payload)
