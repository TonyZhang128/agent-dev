"""从指定 PDF 离线生成监理日记模板，并可输出字段覆盖图。"""

import argparse
from pathlib import Path

import pymupdf

from app.ocr.journal.template import JournalTemplate, table_to_pdf_bounds
from app.ocr.journal.template_builder import build_template

PREVIEW_SCALE = 2


def render_overlay(pdf: Path, template: JournalTemplate, output: Path) -> None:
    """绿色表示值区域，红色表示标签区域；只保存预览，不写回源 PDF。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf) as document:
        page = document[0]
        page.remove_rotation()
        for field in template.fields:
            value_bounds = table_to_pdf_bounds(field.rect_in_table, template.source_table_bounds)
            label_bounds = table_to_pdf_bounds(
                field.label_rect_in_table, template.source_table_bounds
            )
            page.draw_rect(value_bounds, color=(0, 0.65, 0), width=0.8)
            page.draw_rect(label_bounds, color=(0.9, 0.1, 0.1), width=0.5)
            page.insert_text(
                (value_bounds[0] + 2, value_bounds[1] + 10),
                field.key,
                fontsize=8,
                color=(0, 0.45, 0),
            )
        page.get_pixmap(matrix=pymupdf.Matrix(PREVIEW_SCALE, PREVIEW_SCALE), alpha=False).save(
            output
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overlay", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.pdf.resolve() == arguments.output.resolve():
        parser.error("模板输出不得覆盖源 PDF")
    template = build_template(arguments.pdf)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(template.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if arguments.overlay:
        render_overlay(arguments.pdf, template, arguments.overlay)
    print(f"已生成 {len(template.fields)} 个字段：{arguments.output}")


if __name__ == "__main__":
    main()
