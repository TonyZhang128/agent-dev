"""模板库:第二册抽检表审批规则 → templates/approval/jb12_rules.json
用法:uv run --locked python -m scripts.ocr.build_approval "<222张监理表审批流程.xlsx>" ["<第2册.pdf>"]
以表本身为准:表清单 / 编号 / 表名 / 签字栏取自第2册 PDF;流程环节 = 签字栏(抽检人 → 发起,审核人 → 审核);
环节岗位取自审批流程 Excel(按表号 + 表名精确匹配,再按工程分类);Excel 未填的分类按规则推定(inferred)。
(由 v5 tools/build_approval.js 移植,规则不变)"""

import re
import sys
from pathlib import Path

from scripts.ocr.build_forms import PDF
from scripts.ocr.common import TEMPLATES, clean, today, write_json
from scripts.ocr.jl_pdf import parse_forms
from scripts.ocr.xlsx_rows import book, rows

INFER = {"声屏障工程": "绿化工程"}  # 声屏障属环保工程 → 环保专业监理工程师


def person(s):
    t = re.sub(r"\s+", "", "" if s is None else str(s))
    if not t:
        return None
    m = re.match(r"^(.*?)[（(](\d+)[)）]$", t)
    return {"role": m.group(1), "code": m.group(2)} if m else {"role": t, "code": ""}


def norm(s):
    return re.sub(r"_续页$", "", re.sub(r"表表$", "表", re.sub(r"[（）()\s]", "", clean(s))))


def main(xlsx, pdf=PDF):
    rs = rows(book(xlsx).worksheets[0], fill_merged=True)
    head = [clean(h) for h in rs[0]]

    def col(n):
        return next(i for i, h in enumerate(head) if n in h)

    c_cat, c_form, c_from, c_to = col("工程分类"), col("表格编号"), col("审批发起人"), col("审核人")
    xl, cat_people = [], {}
    for i, r in enumerate(rs[1:]):
        m = re.match(r"^(JB12-[\d.\-]+)[_\s]*(.*)$", clean(r[c_form]))
        if not m:
            continue
        cat, frm, to = clean(r[c_cat]), person(r[c_from]), person(r[c_to])
        xl.append(
            {
                "row": i + 2,
                "code": m.group(1),
                "name": m.group(2),
                "cat": cat,
                "from": frm,
                "to": to,
            }
        )
        if frm and to and cat not in cat_people:
            cat_people[cat] = {"from": frm, "to": to}
    forms, issues, used = {}, [], set()
    for f in parse_forms(Path(pdf)):
        cand = [x for x in xl if x["code"] == (f.get("orig") or f["code"])]
        hit = next(
            (x for x in cand if norm(x["name"]) == norm(f["name"])),
            cand[0] if len(cand) == 1 else None,
        )
        if hit:
            used.add(hit["row"])
        cat = f["cat"] or (hit or {}).get("cat", "")
        if hit and hit["from"] and hit["to"]:
            people = {"from": hit["from"], "to": hit["to"], "src": "excel"}
        elif cat in cat_people:
            people = {**cat_people[cat], "src": "excel-cat"}
        else:
            people = None
        if not people and INFER.get(cat) in cat_people:
            people = {**cat_people[INFER[cat]], "src": "inferred"}
            issues.append(
                {
                    "id": f["id"],
                    "text": f"{f['id']}「{f['name']}」:审批 Excel 未填「{cat}」审批人,"
                    f"按表签字栏推定 抽检人={people['from']['role']}、审核人={people['to']['role']}",
                }
            )
        flow = []
        for fld in f["signs"]:
            p = (people or {}).get("from" if fld == "抽检人" else "to") or {}
            flow.append(
                {
                    "step": "发起" if fld == "抽检人" else "审核",
                    "field": fld,
                    "role": p.get("role", "待定"),
                    "code": p.get("code", ""),
                    "src": (people or {}).get("src", "none"),
                }
            )
        if not hit:
            issues.append(
                {
                    "id": f["id"],
                    "text": f"{f['id']}「{f['name']}」在审批 Excel 中无对应行{',按分类沿用' if people else ''}",
                }
            )
        if f.get("issue"):
            issues.append({"id": f["id"], "text": f["issue"]})
        forms[f["id"]] = {
            "code": f["code"],
            "orig": f.get("orig", ""),
            "name": f["name"],
            "cat": cat,
            "page": f["page"],
            "pages": f["pages"],
            "flow": flow,
            "excelRow": (hit or {}).get("row"),
        }
    codes = {(f["orig"] or f["code"]) for f in forms.values()}
    used |= {
        x["row"] for x in xl if x["row"] not in used and "续页" in x["name"] and x["code"] in codes
    }  # 续页行并入同编号表
    issues += [
        {
            "id": x["code"],
            "text": f"审批 Excel 第 {x['row']} 行 {x['code']}「{x['name']}」未匹配到第2册表页",
        }
        for x in xl
        if x["row"] not in used
    ]
    write_json(
        TEMPLATES / "approval/jb12_rules.json",
        {
            "_meta": {
                "generated": today(),
                "by": "scripts/ocr/build_approval.py",
                "note": "第二册抽检表审批规则(岗位)",
            },
            "forms": forms,
            "cats": {k: [v["from"], v["to"]] for k, v in cat_people.items()},
            "issues": issues,
        },
    )
    print(len(forms), "forms,", len(issues), "issues")


if __name__ == "__main__":
    main(*sys.argv[1:])
