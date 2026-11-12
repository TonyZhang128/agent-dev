"""比较 OpenAPI 契约与当前应用实现，检测未经批准的接口漂移。

只比较，不写入任何契约文件。存在正式契约时以正式契约为准；否则检查待确认草案，
并在输出中明确提示该契约尚未获得用户批准。
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

from scripts.docs.openapi_contract import (
    DRAFT_PATH,
    OFFICIAL_PATH,
    approved_journal_differences,
    build_contract,
)


def _normalized(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 OpenAPI 契约与当前实现是否一致。")
    parser.add_argument(
        "--contract",
        type=Path,
        help="要检查的契约文件；默认优先 interfaces/openapi/fastapi.openapi.json，"
        "不存在时使用 interfaces/drafts/fastapi.openapi.json。",
    )
    parser.add_argument(
        "--diff-lines",
        type=int,
        default=80,
        help="不一致时最多输出的 diff 行数，默认 80。",
    )
    args = parser.parse_args(argv)

    implementation = build_contract()
    approved_differences = approved_journal_differences(implementation)
    if approved_differences:
        for difference in approved_differences:
            print(difference)
        print("正式监理日记子契约漂移；禁止用实现覆盖已批准定义。")
        return 1

    if args.contract:
        contract_path = args.contract.resolve()
    elif OFFICIAL_PATH.is_file():
        contract_path = OFFICIAL_PATH
    else:
        contract_path = DRAFT_PATH

    if not contract_path.is_file():
        print(f"契约文件不存在：{contract_path}")
        print("请先运行：uv run --locked python -m scripts.docs.export_openapi")
        return 1

    expected = _normalized(implementation)
    actual = _normalized(_load(contract_path))
    if actual == expected:
        status = "正式契约" if contract_path == OFFICIAL_PATH.resolve() else "待确认草案"
        print(f"契约一致：{contract_path}（{status}）")
        if contract_path != OFFICIAL_PATH.resolve():
            print(
                "监理日记三个操作已通过正式子契约校验；完整草案的其他待确认部分仍不能作为变更授权。"
            )
        return 0

    print(f"契约与实现不一致：{contract_path}")
    print("禁止自动覆盖正式契约；请先审查差异，再决定修实现还是按审批流程变更契约。")
    diff = list(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"{contract_path}（契约）",
            tofile="当前应用实现（scripts.docs.openapi_contract）",
            lineterm="",
        )
    )
    limit = max(args.diff_lines, 0)
    for line in diff[:limit]:
        print(line)
    if len(diff) > limit:
        print(f"…… 其余 {len(diff) - limit} 行差异已省略，可调大 --diff-lines 查看。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
