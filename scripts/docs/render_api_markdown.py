"""把 OpenAPI 草案渲染为便于评审的 Markdown。

生成结果只是契约的只读视图，不是独立契约，也不手工维护。字段、示例和状态全部来自
`interfaces/drafts/fastapi.openapi.json`（正式契约存在时优先使用正式契约）。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.docs.openapi_contract import DRAFT_PATH, OFFICIAL_PATH

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "interfaces/API.md"


def contract_path() -> Path:
    return OFFICIAL_PATH if OFFICIAL_PATH.is_file() else DRAFT_PATH


def load_contract(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def resolve(spec: dict[str, Any], schema: Any) -> dict[str, Any]:
    seen: set[str] = set()
    while isinstance(schema, dict) and "$ref" in schema:
        reference = schema["$ref"]
        if reference in seen:
            return schema
        seen.add(reference)
        schema = spec["components"]["schemas"][reference.rsplit("/", 1)[-1]]
    return schema if isinstance(schema, dict) else {}


def ref_name(schema: Any) -> str:
    if isinstance(schema, dict) and "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    return ""


def cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def type_name(spec: dict[str, Any], schema: Any) -> str:
    name = ref_name(schema)
    if name:
        return f"`{name}`"
    resolved = resolve(spec, schema)
    if "const" in resolved:
        return f"const `{resolved['const']}`"
    if "enum" in resolved:
        values = "、".join(f"`{value}`" for value in resolved["enum"])
        return f"enum（{values}）"
    if "oneOf" in resolved:
        return " 或 ".join(type_name(spec, item) for item in resolved["oneOf"])
    if "anyOf" in resolved:
        return " 或 ".join(type_name(spec, item) for item in resolved["anyOf"])
    value_type = resolved.get("type")
    if isinstance(value_type, list):
        return " / ".join(str(item) for item in value_type)
    if value_type == "array":
        return f"array<{type_name(spec, resolved.get('items', {}))}>"
    return str(value_type or "any")


def constraints(spec: dict[str, Any], schema: Any) -> str:
    resolved = resolve(spec, schema)
    parts: list[str] = []
    for key, label in (
        ("minLength", "minLength"),
        ("maxLength", "maxLength"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("exclusiveMinimum", "exclusiveMinimum"),
        ("exclusiveMaximum", "exclusiveMaximum"),
        ("minItems", "minItems"),
        ("maxItems", "maxItems"),
    ):
        if key in resolved:
            parts.append(f"{label}={resolved[key]}")
    if "pattern" in resolved:
        parts.append(f"pattern=`{resolved['pattern']}`")
    return "，".join(parts)


def field_rows(spec: dict[str, Any], schema: Any) -> list[str]:
    resolved = resolve(spec, schema)
    if resolved.get("type") != "object" or not isinstance(resolved.get("properties"), dict):
        return []
    required = set(resolved.get("required", []))
    rows = []
    for name, prop in resolved["properties"].items():
        prop_resolved = resolve(spec, prop)
        default = (
            f"`{json.dumps(prop_resolved['default'], ensure_ascii=False)}`"
            if "default" in prop_resolved
            else ""
        )
        rows.append(
            "| "
            + " | ".join(
                cell(item)
                for item in (
                    f"`{name}`",
                    type_name(spec, prop),
                    "是" if name in required else "否",
                    default,
                    constraints(spec, prop),
                    prop_resolved.get("description", ""),
                )
            )
            + " |"
        )
    return rows


def field_table(spec: dict[str, Any], schema: Any, title: str = "") -> list[str]:
    rows = field_rows(spec, schema)
    if not rows:
        return []
    lines = []
    if title:
        lines.append(f"**{title}**")
        lines.append("")
    lines.extend(
        [
            "| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |",
            "| --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )
    return lines


def request_section(spec: dict[str, Any], operation: dict[str, Any]) -> list[str]:
    parameters = operation.get("parameters", [])
    lines: list[str] = []
    if parameters:
        lines.extend(
            [
                "**请求参数**",
                "",
                "| 位置 | 名称 | 类型 | 必填 | 约束 | 说明 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for parameter in parameters:
            lines.append(
                "| "
                + " | ".join(
                    cell(item)
                    for item in (
                        parameter.get("in", ""),
                        f"`{parameter.get('name', '')}`",
                        type_name(spec, parameter.get("schema", {})),
                        "是" if parameter.get("required") else "否",
                        constraints(spec, parameter.get("schema", {})),
                        parameter.get("description", ""),
                    )
                )
                + " |"
            )
        lines.append("")

    body = operation.get("requestBody")
    if not body:
        return lines
    content = body.get("content", {}).get("application/json", {})
    schema = content.get("schema", {})
    lines.extend(["**请求体**", ""])
    if content.get("example") is not None:
        lines.extend(
            [
                "```json",
                json.dumps(content["example"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(field_table(spec, schema, "请求字段"))
    name = ref_name(schema)
    if name:
        lines.append(f"Schema：`{name}`")
        lines.append("")
    return lines


def response_section(spec: dict[str, Any], operation: dict[str, Any]) -> list[str]:
    lines = ["**响应**", ""]
    for status in sorted(operation.get("responses", {}), key=lambda item: (len(item), item)):
        response = operation["responses"][status]
        lines.append(f"- `{status}`：{response.get('description', '')}")
    lines.append("")
    for status in sorted(operation.get("responses", {}), key=lambda item: (len(item), item)):
        response = operation["responses"][status]
        content = response.get("content", {})
        if not content:
            continue
        for media_type, media in content.items():
            if media_type != "application/json":
                lines.append(f"**{status} `{media_type}`**")
                lines.append("")
                continue
            if status != "200":
                # 非成功响应使用统一的 ErrorDetail/RequestError，字段在“通用错误响应”说明。
                continue
            lines.append(f"**{status} 响应体**")
            lines.append("")
            if media.get("example") is not None:
                lines.extend(
                    [
                        "```json",
                        json.dumps(media["example"], ensure_ascii=False, indent=2),
                        "```",
                        "",
                    ]
                )
            schema = media.get("schema", {})
            lines.extend(field_table(spec, schema, "响应字段"))
            name = ref_name(schema)
            if name:
                resolved = resolve(spec, schema)
                data = resolved.get("properties", {}).get("data")
                if data is not None:
                    lines.extend(field_table(spec, data, "`data` 字段"))
                lines.append(f"Schema：`{name}`")
                lines.append("")
    return lines


def endpoint_section(
    spec: dict[str, Any], index: int, path: str, method: str, operation: dict[str, Any]
) -> list[str]:
    lines = [
        f"### {index}. `{method.upper()} {path}`",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
        f"| 摘要 | {cell(operation.get('summary', ''))} |",
        f"| 契约状态 | `{operation.get('x-contract-status', '')}` |",
        f"| 来源 | {cell(operation.get('x-contract-source', ''))} |",
        f"| 副作用 | {cell(operation.get('x-side-effects', ''))} |",
        f"| 幂等/重试 | {cell(operation.get('x-idempotency', ''))} |",
        "",
        operation.get("description", ""),
        "",
    ]
    lines.extend(request_section(spec, operation))
    lines.extend(response_section(spec, operation))
    return lines


def schema_appendix(spec: dict[str, Any]) -> list[str]:
    lines = ["## Schema 附录", "", "以下是草案中引用的全部组件 Schema。", ""]
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        resolved = resolve(spec, schema)
        description = resolved.get("description", "")
        lines.extend([f"### `{name}`", ""])
        if description:
            lines.extend([description, ""])
        rows = field_rows(spec, schema)
        if rows:
            lines.extend(
                [
                    "| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |",
                    "| --- | --- | --- | --- | --- | --- |",
                    *rows,
                    "",
                ]
            )
        else:
            lines.extend([f"类型：{type_name(spec, schema)}", ""])
    return lines


def render(spec: dict[str, Any], source: Path) -> str:
    info = spec.get("info", {})
    try:
        source_label = source.relative_to(ROOT).as_posix()
    except ValueError:
        source_label = str(source)
    lines = [
        f"# {info.get('title', '接口文档')}",
        "",
        "> 本文件由 OpenAPI 契约自动生成，用于评审，不是独立契约，请勿手工编辑。",
        f"> 生成来源：`{source_label}`。",
        "> 权威字段以 OpenAPI 为准；正式契约批准前，本文件中的 `pending-review` 操作不能作为"
        "实现授权。",
        "",
        "## 基本信息",
        "",
        "| 项目 | 内容 |",
        "| --- | --- |",
        f"| 标题 | {cell(info.get('title', ''))} |",
        f"| OpenAPI 版本 | {cell(spec.get('openapi', ''))} |",
        f"| 接口版本 | `{cell(info.get('version', ''))}` |",
        f"| 契约版本 | `{cell(info.get('x-contract-version', ''))}` |",
        f"| 契约状态 | `{cell(info.get('x-contract-status', ''))}` |",
        f"| 服务地址 | {cell(', '.join(item.get('url', '') for item in spec.get('servers', [])))} |",
        "",
        info.get("description", ""),
        "",
        "## 通用错误响应",
        "",
        "`400`、`404`、`502`、`503`、`504` 使用 `ErrorDetail`；`422` 使用 `RequestError`。"
        "各接口只列状态码和含义，字段结构见下表，不重复展开。",
        "",
        *field_table(spec, {"$ref": "#/components/schemas/ErrorDetail"}, "`ErrorDetail`"),
        *field_table(spec, {"$ref": "#/components/schemas/RequestError"}, "`RequestError`"),
        "## 接口索引",
        "",
        "| # | 方法与路径 | 摘要 | 状态 |",
        "| --- | --- | --- | --- |",
    ]
    index = 0
    entries: list[tuple[str, str, dict[str, Any]]] = []
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            index += 1
            entries.append((path, method, operation))
            lines.append(
                f"| {index} | `{method.upper()} {path}` | {cell(operation.get('summary', ''))} | "
                f"`{operation.get('x-contract-status', '')}` |"
            )
    lines.extend(["", "## 接口详情", ""])
    for index, (path, method, operation) in enumerate(entries, start=1):
        lines.extend(endpoint_section(spec, index, path, method, operation))
    lines.extend(schema_appendix(spec))
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 OpenAPI 契约渲染为评审用 Markdown。")
    parser.add_argument("--contract", type=Path, default=contract_path())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    source = args.contract.resolve()
    if not source.is_file():
        print(f"契约文件不存在：{source}")
        return 1
    text = render(load_contract(source), source)
    if args.stdout:
        print(text, end="")
        return 0
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"已生成评审文档：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
