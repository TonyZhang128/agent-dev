"""第二册抽检表的现场简表版面 → templates/layouts/jianbiao.json(已有的人工版面不动,只补没有的)
用法:uv run --locked python -m scripts.ocr.build_jianbiao JB12-8.5.2 JB12-8.3.1-4 …(不带参数 = 第二册全部)
简表 = 一张纸一个外框,只留现场要手写的格子:
  表头  工程部位 | 抽检日期;抽检人 | 合同段
  实测  每个检查项目一行:项目名 + 最多 5 个实测值(格子字段 = 目标表上该项目第一行实测格的格子键 g*,见 app/core/grid.py)
识别出的值按同名字段写回目标表同一格,与人工在业务端表上填的是同一套字段。"""

import json
import re
import sys

from app.ocr import grid
from app.ocr.resources import forms
from scripts.ocr.common import TEMPLATES, today, write_json

HEAD = [
    ("fld_location", "工程部位", 0.62, None),
    ("fld_sample_date", "抽检日期", 0.38, "date"),
    ("fld_sampler", "抽检人", 0.62, None),
    ("fld_contract_sec", "合同段", 0.38, None),
]
MAX_ITEMS, MAX_VALS = 5, 5


def _name(t: str) -> str:
    """检查项目名:去掉 △、单位和规定值(印在表上的完整文字另存 spec)"""
    t = re.sub(r"[△□☐]", "", t)
    return re.split(r"[（(±≥≤+]|\d", t)[0][:8] or t[:8]


def items(code: str) -> list[tuple[str, list[str], str]]:
    """[(项目名, [实测格子键…], 表上印的完整文字)]:实测区里左侧印了项目名、右侧有 ≥3 个空格子的行"""
    cells = grid.cells(code)
    empty = [c for c in cells if not c["text"]]
    out, used = [], set()
    for lab in cells:
        r = lab["rect"]
        if (
            not lab["text"]
            or r["x"] > 0.4
            or not (0.3 < r["y"] < 0.85)
            or re.search(r"外观|基本|检查结论|处理意见|审核|抽检项目$", lab["text"])
        ):
            continue
        y0 = r["y"]
        row = sorted(
            [
                c
                for c in empty
                if abs(c["rect"]["y"] - y0) < 0.006
                and c["rect"]["x"] > 0.45
                and c["rect"]["x"] < 0.85
                and c["key"] not in used
            ],
            key=lambda c: c["rect"]["x"],
        )
        if len(row) < 3:
            continue
        vals = [c["key"] for c in row[:MAX_VALS]]
        used.update(vals)
        name = _name(lab["text"])
        if name and not any(o[0] == name for o in out):
            out.append((name, vals, lab["text"]))
        if len(out) >= MAX_ITEMS:
            break
    return out


def layout(code: str) -> dict | None:
    its = items(code)
    if not its:
        return None
    n = len(its)
    head_h, row_h = 0.12, 0.16
    total = 2 * head_h + n * row_h
    k = 1 / total  # 各行高度按比例缩放到外框 0~1
    cells, y = [], 0.0
    for i in range(0, 4, 2):
        x = 0.0
        for field, label, w, typ in HEAD[i : i + 2]:
            c = {
                "field": field,
                "label": label,
                "rect": [round(x, 3), round(y, 3), w, round(head_h * k, 3)],
            }
            if typ:
                c["type"] = typ
            cells.append(c)
            x += w
        y += head_h * k
    vw = 0.78 / MAX_VALS
    for name, vals, spec in its:
        h = round(row_h * k, 3)
        cells.append(
            {
                "field": "",
                "label": name,
                "rect": [0.0, round(y, 3), 0.22, h],
                "print": True,
                "spec": spec,
            }
        )
        for j, key in enumerate(vals):
            cells.append(
                {
                    "field": key,
                    "label": str(j + 1),
                    "rect": [round(0.22 + j * vw, 3), round(y, 3), round(vw, 3), h],
                    "type": "number",
                    "item": name,
                }
            )
        y += row_h * k
    name = (forms().get(code) or {}).get("name", code).replace("抽检记录表", "")
    return {
        "name": name + "抽检简表",
        "target": code,
        "aspect": round(0.72 * total / 0.88, 3),  # 与土方路基简表同一行高(2 行表头 + 4 行 = .72)
        "title": name + "抽检简表",
        "auto": True,
        "cells": [c for c in cells if c["field"] or c.get("print")],
    }


def run(codes: list[str]):
    path = TEMPLATES / "layouts" / "jianbiao.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    have = {f["target"] for f in doc["forms"].values() if not f.get("auto")}  # 自动生成的可重算
    added = []
    for code in codes or [c for c in forms() if c.startswith("JB12-")]:
        if code in have:
            continue
        lay = layout(code)
        if lay:
            doc["forms"]["JB-" + code] = lay
            added.append(
                f"{code}({len([c for c in lay['cells'] if c.get('item') and c['label'] == '1'])} 项)"
            )
    doc["_meta"]["auto"] = (
        f"{today()} scripts/build_jianbiao.py 按表样格子生成(auto = true),人工版面不覆盖"
    )
    write_json(path, doc)
    print("新增简表:", "、".join(added) or "无")


if __name__ == "__main__":
    run(sys.argv[1:])
