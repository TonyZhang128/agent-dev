"""Excel 读取(openpyxl,唯一的 Excel 包):工作表 → 二维数组 / 表头字典;合并单元格向下、向右填充。
替代 v5 Node 版的 xlsx(SheetJS)sheet_to_json。"""

from openpyxl import load_workbook


def book(path):
    return load_workbook(path, data_only=True)


def rows(ws, fill_merged=False):
    """二维数组,空单元格为 '';fill_merged=True 时合并区每格都取左上角的值"""
    out = [["" if c is None else c for c in r] for r in ws.iter_rows(values_only=True)]
    if fill_merged:
        for m in ws.merged_cells.ranges:
            v = out[m.min_row - 1][m.min_col - 1] if m.min_row - 1 < len(out) else ""
            for r in range(m.min_row - 1, m.max_row):
                for c in range(m.min_col - 1, m.max_col):
                    if r < len(out) and c < len(out[r]) and out[r][c] in ("", None):
                        out[r][c] = v
    return out


def records(ws):
    """第一行为表头,其余行 → [{表头: 值}](同 SheetJS sheet_to_json 默认行为)"""
    rs = rows(ws)
    if not rs:
        return []
    head = [str(h).strip() if h not in ("", None) else f"__EMPTY_{i}" for i, h in enumerate(rs[0])]
    return [
        {h: (r[i] if i < len(r) else "") for i, h in enumerate(head)}
        for r in rs[1:]
        if any(x not in ("", None) for x in r)
    ]


def sheet(wb, name):
    """按去掉首尾空格的表名找工作表"""
    return next(wb[n] for n in wb.sheetnames if n.strip() == name)
