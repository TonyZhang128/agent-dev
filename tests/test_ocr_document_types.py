"""文档处理的工作表边界与公共数值类型回归。"""

import openpyxl
import pytest
from openpyxl.chart import BarChart, Reference

from app.ocr.core.resources import OCRResourceError, OCRResources, use_resources
from app.ocr.sheets import grid
from tests.ocr_helpers import CODE, make_ocr_settings


def test_excel_template_rejects_active_chartsheet(tmp_path):
    settings = make_ocr_settings(tmp_path)
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append([1])
    chart = BarChart()
    chart.add_data(Reference(worksheet, min_col=1, min_row=1))
    chart_sheet = workbook.create_chartsheet("图表")
    chart_sheet.add_chart(chart)
    workbook.active = chart_sheet
    workbook.save(settings.asset_root / "excel/test.xlsx")
    workbook.close()

    with use_resources(OCRResources(settings)):
        with pytest.raises(OCRResourceError, match="活动页必须为普通工作表"):
            grid.fill_xlsx(CODE, [], {}, tmp_path / "output.xlsx")


def test_excel_anchor_in_merged_cell_writes_merge_origin(tmp_path):
    settings = make_ocr_settings(tmp_path)
    output = tmp_path / "output.xlsx"
    with use_resources(OCRResources(settings)):
        result = grid.fill_xlsx(
            CODE,
            [{"field": "fld_supervisor", "value": "测试公司"}],
            {"fld_supervisor": "B1"},
            output,
        )

    workbook = openpyxl.load_workbook(output)
    try:
        assert workbook.active["A1"].value == "监理单位：测试公司  编 号:TEST"
        assert workbook.active["B1"].value is None
        assert result.skipped == ()
    finally:
        workbook.close()
