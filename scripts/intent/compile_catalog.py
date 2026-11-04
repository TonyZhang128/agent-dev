"""从业务功能 JSON 生成意图枚举；`--check` 用于 CI 漂移检查。"""

from __future__ import annotations

import argparse

from scripts.intent.catalog import GENERATED_PATH, load_and_render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成业务意图枚举。")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只比较生成结果与已提交文件，不写入。",
    )
    args = parser.parse_args(argv)

    rendered, version = load_and_render()
    if args.check:
        current = GENERATED_PATH.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "生成文件已过期：请运行 "
                "`uv run --locked python -m scripts.intent.compile_catalog` 后提交。"
            )
            return 1
        print(f"业务意图目录一致，版本 {version}。")
        return 0

    GENERATED_PATH.write_text(rendered, encoding="utf-8")
    print(f"已生成 {GENERATED_PATH.relative_to(GENERATED_PATH.parents[2])}，版本 {version}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
