"""模板库:第二册用表目录 + 分项 / 子分项候选用表 → templates/forms/jl_forms.json
用法:uv run --locked python -m scripts.ocr.build_forms "<岷江二桥主桥_监理用表完整映射.xlsx>" ["<第2册 施工监理用表.pdf>"]
(由 v5 tools/build_forms.js 移植,规则不变)"""

import re
import sys
from pathlib import Path

from scripts.ocr.common import ASSET, TEMPLATES, clean, today, write_json
from scripts.ocr.jl_pdf import parse_forms
from scripts.ocr.xlsx_rows import book, records, sheet

PDF = ASSET / "pdf/四川省公路工程施工监理统一用表-第二册/施工监理用表-第2册.pdf"
COLS = {
    "code": "表格编号",
    "name": "监理用表名称（PDF原文）",
    "work": "对应监理工程名称",
    "type": "匹配类型",
    "conf": "置信度",
    "why": "匹配说明/适用条件",
    "report": "配套强度/其他试验报告（原文）",
}


def lst(s):
    """单元格里的编号列表(1. 钢筋安装 / 2. 钢筋网)→ ['钢筋安装', '钢筋网']"""
    lines = re.split(r"\r?\n", "" if s is None else str(s))
    return [x for x in (clean(re.sub(r"^\d+\.\s*", "", ln)) for ln in lines) if x]


def main(xlsx, pdf=PDF):
    wb = book(xlsx)

    def rows_of(n):
        return records(sheet(wb, n))

    catalog = {
        f["id"]: {
            "code": f["code"],
            "orig": f.get("orig", ""),
            "name": f["name"],
            "page": f["page"],
            "pages": f["pages"],
            "signs": f["signs"],
            "cat": f["cat"],
            "issue": f.get("issue", ""),
        }
        for f in parse_forms(Path(pdf))
    }
    notes_extra = []
    for r in rows_of("PDF桥梁用表目录"):
        code = clean(r.get("抽检表编号"))
        if not code:
            continue
        if code not in catalog:
            notes_extra.append(
                {
                    "key": f"映射目录 / {code}",
                    "text": f"映射表列出的 {code}「{clean(r.get('抽检表名称（原文）'))}」在第2册表页中不存在,已忽略",
                }
            )
            continue
        rep = str(r.get("配套试验报告（原文）") or "")
        catalog[code].update(
            {
                "work": clean(r.get("监理工程名称（原文）")),
                "kind": clean(r.get("表格类型（原文）")),
                "nameMap": clean(r.get("抽检表名称（原文）")),
                "report": "" if "未另列" in rep else re.sub(r"（PDF第\d+页）", "", clean(rep)),
                "issue": ";".join(
                    x for x in (catalog[code]["issue"], clean(r.get("PDF疑点"))) if x
                ),
            }
        )

    def forms(r):
        k = {n: lst(r.get(c)) for n, c in COLS.items()}

        def g(n, i):
            return k[n][i] if i < len(k[n]) else ""

        return [
            {
                "code": code,
                "name": g("name", i) or catalog.get(code, {}).get("name", ""),
                "work": g("work", i),
                "type": g("type", i),
                "conf": g("conf", i),
                "why": g("why", i),
                "report": ""
                if re.search(r"未另列|本工程条目未另列", g("report", i))
                else g("report", i),
                "page": catalog.get(code, {}).get("page"),
            }
            for i, code in enumerate(k["code"])
        ]

    items = {
        f"{clean(r.get('分项工程编码（原文）'))}|{clean(r.get('分项工程（原文）'))}": {
            "mid": clean(r.get("映射ID")),
            "part": clean(r.get("分部工程（原文）")),
            "forms": forms(r),
            "note": clean(r.get("原表疑点/备注")),
        }
        for r in rows_of("分项映射75")
    }
    subs = {}
    for r in rows_of("子分项映射438"):
        key = f"{clean(r.get('原分项编码'))}|{clean(r.get('分项工程（原文）'))}|{clean(r.get('子分项工程（原文）'))}"
        subs.setdefault(
            key,
            {
                "mid": clean(r.get("映射ID")),
                "row": r.get("Excel原行号"),
                "forms": forms(r),
                "note": clean(r.get("原备注/疑点")),
            },
        )
    notes = (
        [
            {"key": clean(r.get("项目")), "text": clean(r.get("内容"))}
            for r in rows_of("说明与待核对")
            if clean(r.get("项目"))
        ]
        + notes_extra
        + [
            {"key": f"PDF第{c['page']}页 / {i}", "text": c["issue"]}
            for i, c in catalog.items()
            if c["orig"]
        ]
    )
    write_json(
        TEMPLATES / "forms/jl_forms.json",
        {
            "_meta": {
                "generated": today(),
                "by": "scripts/ocr/build_forms.py",
                "note": "第二册用表目录 + 分项 / 子分项候选用表",
            },
            "pdf": "pdf/施工监理用表-第2册.pdf",
            "catalog": catalog,
            "items": items,
            "subs": subs,
            "notes": notes,
        },
    )
    print("catalog", len(catalog), "items", len(items), "subs", len(subs), "notes", len(notes))


if __name__ == "__main__":
    main(*sys.argv[1:])
