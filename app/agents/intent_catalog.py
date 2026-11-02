"""业务意图目录的只读运行时视图；不读取 JSON 文件。"""

from app.schemas.agents import BusinessIntentOption
from app.schemas.intent_catalog_generated import (
    ACTION_NAMES,
    ACTIONS_BY_PAGE,
    PAGE_BY_ACTION,
    PAGE_CODES,
    PAGE_NAMES,
)


def action_belongs_to_page(page: str, action: str) -> bool:
    return PAGE_BY_ACTION.get(action) == page


def page_name(page: str) -> str:
    return PAGE_NAMES[page]


def options_for_page(page: str) -> list[BusinessIntentOption]:
    return [
        BusinessIntentOption(page=page, action=action, name=ACTION_NAMES[action])
        for action in ACTIONS_BY_PAGE[page]
    ]


def catalog_payload() -> dict:
    """发送给模型的紧凑目录；只包含导航所需的 code 和 name。"""
    return {
        "pages": [
            {
                "page": page,
                "name": PAGE_NAMES[page],
                "actions": [
                    {"action": action, "name": ACTION_NAMES[action]}
                    for action in ACTIONS_BY_PAGE[page]
                ],
            }
            for page in PAGE_CODES
        ]
    }
