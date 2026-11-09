"""独立 PDF 版面验证模板提取，不从生产坐标生成期望结果。"""

from pathlib import Path

import pymupdf
import pytest


def write_template(path: Path, *, missing_label: bool = False) -> None:
    """模拟 Word 导出的窄矩形线、合并格和中文多行标签。"""
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        for top in (180, 230, 275, 325, 510, 630, 725):
            page.draw_rect((65, top - 0.2, 535, top + 0.2), color=None, fill=(0, 0, 0))
        for left, top, bottom in (
            (65, 180, 725),
            (146, 180, 725),
            (535, 180, 725),
            (346, 230, 325),
            (442, 230, 325),
        ):
            page.draw_rect((left - 0.2, top, left + 0.2, bottom), color=None, fill=(0, 0, 0))
        page.draw_line((190, 128), (335, 128))
        labels = (
            (340, 125, "工程项目"),
            (435, 173, "编号："),
            (70, 210, "监理机构"),
            (70, 255, "记录人"),
            (350, 255, "天气"),
            (70, 305, "岗位"),
            (350, 305, "记录时间"),
            (470, 305, "年 月 日"),
            (70, 400, "当日主要监"),
            (70, 420, "理工作情况"),
            (70, 565, "发现的问题"),
            (70, 585, "及处理结果"),
            (70, 665, "次日工作计"),
            (70, 685, "划和管控重"),
            (70, 705, "点"),
            (415, 744, "审核人："),
        )
        for left, top, label in labels:
            if missing_label and label == "记录人":
                continue
            page.insert_text((left, top), label, fontname="china-s", fontsize=12)
        # 隐藏层有同名标签，不能形成第二个可见锚点。
        page.insert_text((180, 205), "记录人", fontname="china-s", fontsize=12, render_mode=3)
        document.save(path)


def test_build_template_extracts_cells_and_outside_fields(tmp_path):
    from app.ocr.journal.template_builder import build_template

    pdf = tmp_path / "journal.pdf"
    write_template(pdf)
    template = build_template(pdf)
    fields = {field.key: field for field in template.fields}

    assert template.source_page_size == (595, 842)
    assert template.source_table_bounds == pytest.approx((65, 180, 535, 725), abs=0.02)
    assert len(fields) == 11
    assert fields["recorder"].rect_in_table == pytest.approx(
        (81 / 470, 50 / 545, 200 / 470, 45 / 545), abs=0.0001
    )
    assert fields["weather"].rect_in_table == pytest.approx(
        (377 / 470, 50 / 545, 93 / 470, 45 / 545), abs=0.0001
    )
    assert fields["main_work"].rect_in_table == pytest.approx(
        (81 / 470, 145 / 545, 389 / 470, 185 / 545), abs=0.0001
    )
    assert fields["next_day_plan"].rect_in_table == pytest.approx(
        (81 / 470, 450 / 545, 389 / 470, 95 / 545), abs=0.0001
    )
    assert fields["project"].rect_in_table[0] == pytest.approx(125 / 470)
    assert fields["project"].rect_in_table[2] == pytest.approx(145 / 470)
    assert fields["project"].rect_in_table[1] < 0
    assert fields["reviewer"].rect_in_table[1] >= 1
    assert fields["number"].rect_in_table[0] == pytest.approx(
        fields["number"].label_rect_in_table[0] + fields["number"].label_rect_in_table[2]
    )
    assert len(template.source_sha256) == 64


def test_build_template_is_repeatable_and_rejects_missing_label(tmp_path):
    from app.ocr.journal.template_builder import build_template

    pdf = tmp_path / "journal.pdf"
    write_template(pdf)
    assert build_template(pdf).model_dump_json() == build_template(pdf).model_dump_json()
    broken = tmp_path / "missing.pdf"
    write_template(broken, missing_label=True)
    with pytest.raises(ValueError, match="记录人"):
        build_template(broken)


def test_template_rejects_duplicate_fields_and_inverted_regions(tmp_path):
    from pydantic import ValidationError

    from app.ocr.journal.template import JournalTemplate
    from app.ocr.journal.template_builder import build_template

    pdf = tmp_path / "journal.pdf"
    write_template(pdf)
    serialized = build_template(pdf).model_dump(mode="json")
    serialized["fields"][1] = serialized["fields"][0]
    with pytest.raises(ValidationError):
        JournalTemplate.model_validate(serialized)

    serialized = build_template(pdf).model_dump(mode="json")
    serialized["fields"][0]["rect_in_table"] = [0.1, 0.1, -0.1, 0.3]
    with pytest.raises(ValidationError):
        JournalTemplate.model_validate(serialized)


def test_template_geometry_does_not_change_with_pdf_page_margin(tmp_path):
    from app.ocr.journal.template_builder import build_template

    original = tmp_path / "original.pdf"
    shifted = tmp_path / "shifted.pdf"
    write_template(original)
    with pymupdf.open(original) as source, pymupdf.open() as destination:
        page = destination.new_page(width=800, height=1000)
        page.show_pdf_page(pymupdf.Rect(100, 70, 695, 912), source, 0)
        destination.save(shifted)
    before, after = build_template(original), build_template(shifted)
    assert before.source_page_size != after.source_page_size
    for first, second in zip(before.fields, after.fields, strict=True):
        assert first.rect_in_table == pytest.approx(second.rect_in_table, abs=1e-5)
        assert first.label_rect_in_table == pytest.approx(second.label_rect_in_table, abs=1e-5)
