"""导出待确认的 OpenAPI 草案。

正式契约位于 `interfaces/openapi/`，只能由用户在批准后人工提升；本脚本禁止
直接写入该目录，避免自动生成结果静默覆盖已确认契约。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.docs.openapi_contract import DRAFT_PATH, OFFICIAL_PATH, contract_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从当前 FastAPI 应用导出 OpenAPI 草案。")
    parser.add_argument(
        "--output",
        type=Path,
        default=DRAFT_PATH,
        help=f"输出路径；默认 {DRAFT_PATH.relative_to(DRAFT_PATH.parents[2])}。",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="只输出到标准输出，不写文件。",
    )
    args = parser.parse_args(argv)

    text = contract_json()
    if args.stdout:
        print(text, end="")
        return 0

    output = args.output.resolve()
    official_dir = OFFICIAL_PATH.parent.resolve()
    if output == OFFICIAL_PATH.resolve() or output.is_relative_to(official_dir):
        parser.error(
            "不得自动写入 interfaces/openapi/：正式契约需经用户批准后人工提升，"
            "请先导出到 interfaces/drafts/ 并提交确认。"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"已导出 OpenAPI 草案：{output}")
    print("状态：待用户确认；该文件不是正式契约。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
