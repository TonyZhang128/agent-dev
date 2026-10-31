"""PDF / Excel 一致性检查:给表样上每个可填格子写一个唯一标记,经 compute(与业务端保存同一条路)出 PDF + Excel,再核对
  1. PDF:每个标记都写在它自己的格子坐标里(按文字层取格子内的字)
  2. Excel:每个标记恰好写进一个单元格,没有两个格子写到同一个单元格(互相覆盖 = 丢数据),没有覆盖印好的栏目名;
     Excel 表样本身比 PDF 少的格子(fill_xlsx 判为无处可写、跳过的)单独列为 noCell,不算错
  3. 位置:同一行的格子在 Excel 里也在同一行、从左到右列号递增;上下两行的格子在 Excel 里行号不倒挂
用法:uv run --locked python -m scripts.ocr.check_pdf_excel [表号…](不带 = 第二册全部有 Excel 表样的表)  结果写 verification/ocr/pdf_excel.json"""

import json
import re
import sys
import tempfile
from pathlib import Path

import openpyxl
import pymupdf

from app.ocr import grid, jianbiao
from app.ocr.resources import forms
from scripts.ocr.common import ROOT


def check(code: str, tmp: Path) -> dict:
    cells = [c for c in grid.sheet(code) if c["kind"] == "grid"]
    if not cells:
        return {"code": code, "skip": "表样没有可填空格子"}
    values = {c["field"]: f"T{i:03d}" for i, c in enumerate(cells)}
    out = jianbiao.compute(code, {}, values, tmp / f"{code}.pdf")
    if not out.get("xlsx"):
        return {"code": code, "skip": "没有 Excel 表样"}
    res = {
        "code": code,
        "cells": len(cells),
        "pdfMiss": [],
        "xlsxMiss": [],
        "collide": [],
        "order": [],
    }
    # 1. PDF
    with pymupdf.open(out["pdf"]) as doc:
        pg = doc[0]
        W, H = pg.rect.width, pg.rect.height
        for c in cells:
            r = c["rect"]
            box = pymupdf.Rect(
                r["x"] * W - 1, r["y"] * H - 1, (r["x"] + r["w"]) * W + 1, (r["y"] + r["h"]) * H + 1
            )
            if values[c["field"]] not in re.sub(r"\s", "", pg.get_textbox(box)):
                res["pdfMiss"].append(c["field"])
    # 2. Excel
    ws = openpyxl.load_workbook(out["xlsx"]).active
    where = {}
    for row in ws.iter_rows():
        for x in row:
            for tok in re.findall(r"T\d{3}", str(x.value or "")):
                where.setdefault(tok, []).append((x.row, x.column, str(x.value)))
    skipped = set(out["xlsxSkipped"])
    for c in cells:
        tok = values[c["field"]]
        hit = where.get(tok, [])
        if not hit and c["field"] in skipped:
            res.setdefault("noCell", []).append(
                c["field"]
            )  # Excel 表样没有对应格子:不写,PDF 上有(已知差异,单独列出)
        elif not hit:
            res["xlsxMiss"].append(c["field"])
        elif re.sub(r"T\d{3}", "", hit[0][2]).strip():
            res.setdefault("overwrite", []).append(f"{c['field']}→{hit[0][2][:20]}")
    by_cell = {}
    for tok, hits in where.items():
        for r, col, _ in hits:
            by_cell.setdefault((r, col), []).append(tok)
    res["collide"] = [f"R{r}C{col}:{'/'.join(t)}" for (r, col), t in by_cell.items() if len(t) > 1]
    # 3. 位置顺序
    pos = {
        c["field"]: where[values[c["field"]]][0][:2] for c in cells if where.get(values[c["field"]])
    }
    for a in cells:
        for b in cells:
            if a is b or a["field"] not in pos or b["field"] not in pos:
                continue
            ra, rb = a["rect"], b["rect"]
            same_row = abs(ra["y"] - rb["y"]) < 0.004
            if (
                same_row
                and ra["x"] < rb["x"]
                and pos[a["field"]][1] >= pos[b["field"]][1]
                and pos[a["field"]][0] == pos[b["field"]][0]
            ):
                res["order"].append(f"{a['field']}/{b['field']} 列倒挂")
            if ra["y"] + ra["h"] <= rb["y"] + 0.001 and pos[a["field"]][0] > pos[b["field"]][0]:
                res["order"].append(f"{a['field']}/{b['field']} 行倒挂")
    res["ok"] = not (
        res["pdfMiss"] or res["xlsxMiss"] or res["collide"] or res["order"] or res.get("overwrite")
    )
    return res


def main():
    codes = sys.argv[1:] or [
        c
        for c, f in forms().items()
        if c.startswith("JB12-") and (f.get("excel") or {}).get("path")
    ]
    tmp = Path(tempfile.mkdtemp(prefix="pdfxlsx_"))
    out = [check(c, tmp) for c in codes]
    done = [r for r in out if "skip" not in r]
    bad = [r for r in done if not r["ok"]]
    dst = ROOT / "verification" / "ocr" / "pdf_excel.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"检查 {len(done)} 张表(跳过 {len(out) - len(done)}),通过 {len(done) - len(bad)},有问题 {len(bad)};明细 {dst}"
    )
    gap = [r for r in done if r.get("noCell")]
    print(
        f"Excel 表样比 PDF 少格子(这些格只写 PDF,不乱写到别处){len(gap)} 张:",
        "、".join(f"{r['code']}({len(r['noCell'])} 格)" for r in gap),
    )
    for r in bad[:30]:
        print(
            " ",
            r["code"],
            {
                k: (v[:4] if isinstance(v, list) else v)
                for k, v in r.items()
                if k not in ("code", "ok", "cells") and v
            },
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
