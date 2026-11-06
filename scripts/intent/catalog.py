"""业务意图目录的构建期校验、版本计算和枚举生成。

本模块只在构建和测试阶段读取 JSON；应用运行时只导入生成后的常量，
不会在导入或请求时读取 `app/resources`。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from app.schemas.base import StrictModel

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "app/resources/intent/business_pages.json"
GENERATED_PATH = ROOT / "app/schemas/intent_catalog_generated.py"

Code = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"
    ),
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
RESERVED_CODES = {"chat", "unknown"}


class CatalogAction(StrictModel):
    id: int = Field(ge=1)
    code: Code
    name: Name


class CatalogPage(StrictModel):
    id: int = Field(ge=1)
    code: Code
    name: Name
    actions: list[CatalogAction] = Field(min_length=1)


class IntentCatalog(StrictModel):
    pages: list[CatalogPage] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> IntentCatalog:
        pages = self.pages
        page_codes = [page.code for page in pages]
        action_codes = [action.code for page in pages for action in page.actions]
        ids = [page.id for page in pages] + [action.id for page in pages for action in page.actions]
        if len(page_codes) != len(set(page_codes)):
            raise ValueError("page codes must be unique")
        if len(action_codes) != len(set(action_codes)):
            raise ValueError("action codes must be unique")
        if len(ids) != len(set(ids)):
            raise ValueError("ids must be unique across pages and actions")
        overlap = set(page_codes) & set(action_codes)
        if overlap:
            raise ValueError(f"page and action codes must not collide: {sorted(overlap)}")
        reserved = RESERVED_CODES & (set(page_codes) | set(action_codes))
        if reserved:
            raise ValueError(f"reserved codes are not allowed: {sorted(reserved)}")
        return self

    @property
    def page_codes(self) -> tuple[str, ...]:
        return tuple(page.code for page in self.pages)

    @property
    def action_codes(self) -> tuple[str, ...]:
        return tuple(action.code for page in self.pages for action in page.actions)

    @property
    def page_names(self) -> dict[str, str]:
        return {page.code: page.name for page in self.pages}

    @property
    def action_names(self) -> dict[str, str]:
        return {action.code: action.name for page in self.pages for action in page.actions}

    @property
    def actions_by_page(self) -> dict[str, tuple[str, ...]]:
        return {page.code: tuple(action.code for action in page.actions) for page in self.pages}

    @property
    def page_by_action(self) -> dict[str, str]:
        return {action.code: page.code for page in self.pages for action in page.actions}


def _canonical_payload(data: dict) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def catalog_version(data: dict) -> str:
    """内容哈希；仅空格/键顺序变化不应改变版本。"""
    return hashlib.sha256(_canonical_payload(data)).hexdigest()[:16]


def load_catalog(path: Path = CATALOG_PATH) -> tuple[IntentCatalog, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("intent catalog must be a JSON object")
    return IntentCatalog.model_validate(data), catalog_version(data)


def _string_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _tuple_lines(values: Sequence[str], indent: int) -> str:
    if not values:
        return "()"
    inner = " " * (indent + 4)
    closing = " " * indent
    body = "\n".join(f"{inner}{_string_literal(value)}," for value in values)
    return f"(\n{body}\n{closing})"


def _dict_of_strings_lines(mapping: Mapping[str, str], indent: int) -> str:
    if not mapping:
        return "{}"
    inner = " " * (indent + 4)
    closing = " " * indent
    body = "\n".join(
        f"{inner}{_string_literal(key)}: {_string_literal(value)},"
        for key, value in mapping.items()
    )
    return "{\n" + body + f"\n{closing}}}"


def _dict_of_tuples_lines(mapping: Mapping[str, Sequence[str]], indent: int) -> str:
    if not mapping:
        return "{}"
    inner = " " * (indent + 4)
    closing = " " * indent
    body = "\n".join(
        f"{inner}{_string_literal(key)}: {_tuple_lines(value, indent + 4)},"
        for key, value in mapping.items()
    )
    return "{\n" + body + f"\n{closing}}}"


def _literal_lines(name: str, values: Sequence[str]) -> str:
    body = "\n".join(f"    {_string_literal(value)}," for value in values)
    return f"{name} = Literal[\n{body}\n]"


def render_generated(catalog: IntentCatalog, version: str) -> str:
    page_codes = catalog.page_codes
    action_codes = catalog.action_codes
    parts = [
        '"""由 scripts.intent.compile_catalog 生成，请勿手改。"""',
        "",
        "from typing import Literal",
        "",
        f"CATALOG_VERSION = {_string_literal(version)}",
        "",
        _literal_lines("BusinessPageLabel", page_codes),
        "",
        _literal_lines("BusinessActionLabel", action_codes),
        "",
        f"PAGE_CODES: tuple[BusinessPageLabel, ...] = {_tuple_lines(page_codes, 0)}",
        "",
        f"ACTION_CODES: tuple[BusinessActionLabel, ...] = {_tuple_lines(action_codes, 0)}",
        "",
        f"PAGE_NAMES: dict[str, str] = {_dict_of_strings_lines(catalog.page_names, 0)}",
        "",
        f"ACTION_NAMES: dict[str, str] = {_dict_of_strings_lines(catalog.action_names, 0)}",
        "",
        "ACTIONS_BY_PAGE: dict[str, tuple[BusinessActionLabel, ...]] = "
        f"{_dict_of_tuples_lines(catalog.actions_by_page, 0)}",
        "",
        "PAGE_BY_ACTION: dict[str, BusinessPageLabel] = "
        f"{_dict_of_strings_lines(catalog.page_by_action, 0)}",
        "",
    ]
    return "\n".join(parts)


def load_and_render(path: Path = CATALOG_PATH) -> tuple[str, str]:
    catalog, version = load_catalog(path)
    return render_generated(catalog, version), version
