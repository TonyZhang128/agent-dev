"""分部分项划分表(xlsx)→ 业务库 MongoDB wbsTrees(一个合同段一整棵树)
用法:uv run --locked python -m scripts.ocr.build_wbs "<分部分项.xlsx>" [合同段编号,默认 S210]  → 输出 JSON 到标准输出,由 Java 导入或 --save 写入 Mongo
层级:单位工程 → 分部工程 → 分项工程 → 子分项工程(合并单元格向下填充)
(由 v5 tools/build_wbs.js 移植,规则不变;v6 划分属业务库,不再生成前端 JS)"""

import json
import re
import sys

from scripts.ocr.common import clean
from scripts.ocr.xlsx_rows import book, rows, sheet

SKIP = ("封面", "说明", "Sheet1")


def parse(path, prefix="S210"):
    wb = book(path)
    is_code = lambda s: bool(re.match(rf"^{prefix}-[A-Z]+\d+", clean(s)))  # noqa: E731
    flat = lambda ws: [clean(c) for r in rows(ws) for c in r if clean(c)]  # noqa: E731
    cover, note = flat(sheet(wb, "封面")), flat(sheet(wb, "说明"))
    m = re.search(r"本项目划分为[^。]*", next((s for s in note if "本项目划分为" in s), ""))
    project = {
        "name": cover[0] if cover else prefix,
        "builder": "",
        "supervisor": "",
        "summary": m.group(0) if m else "",
        "date": next((s for s in cover if re.search(r"年.*月$", s)), ""),
    }
    units, by_code = [], {}
    for sn in wb.sheetnames:
        if sn.strip() in SKIP:
            continue
        rs = rows(wb[sn])
        hi = next((i for i, r in enumerate(rs) if "分部工程" in [clean(c) for c in r]), -1)
        if hi < 0:
            continue
        for s in (clean(c) for r in rs[:hi] for c in r):
            if re.match(r"^施工单位[:：]", s):
                project["builder"] = re.sub(r"^施工单位[:：]", "", s)
            if re.match(r"^监理单位[:：]", s):
                project["supervisor"] = re.sub(r"^监理单位[:：]", "", s)
        head = [clean(c) for c in rs[hi]]
        flag_cols = [(n, head.index(n)) for n in ("资料", "评定", "交工", "开工") if n in head]
        unit = part = item = None
        for raw in rs[hi + 1 :]:
            r = [clean(c) for c in raw] + [""] * 8
            if not any(r):
                continue
            a, b = r[0], r[1]
            u_code = a if is_code(a) else b if is_code(b) else ""
            u_name = b if is_code(a) else a
            if u_code:
                if u_code not in by_code:
                    by_code[u_code] = {
                        "code": u_code,
                        "title": u_name or u_code,
                        "sheets": [],
                        "children": [],
                    }
                    units.append(by_code[u_code])
                unit = by_code[u_code]
                if u_name and unit["title"] == u_code:
                    unit["title"] = u_name
            if not unit:
                continue
            if sn not in unit["sheets"]:
                unit["sheets"].append(sn)
            p_name, p_code = r[2], r[3]
            if p_code and is_code(p_code):
                part = next((x for x in unit["children"] if x["code"] == p_code), None)
                if not part:
                    part = {"code": p_code, "title": p_name or p_code, "children": []}
                    unit["children"].append(part)
                item = None
            if not part:
                continue
            i_name, i_code = r[4], r[5]
            if i_name or i_code:
                code = i_code or (item["code"] if item else "")
                item = next(
                    (
                        x
                        for x in part["children"]
                        if x["code"] == code and x["title"] == (i_name or x["title"])
                    ),
                    None,
                )
                if not item:
                    item = {"code": code, "title": i_name or code, "children": []}
                    part["children"].append(item)
                std = next(
                    (c for i, c in enumerate(r) if i > 6 and re.match(r"^\d+(\.\d+)+(-\d+)?$", c)),
                    None,
                )
                if std:
                    item["std"] = std
                for n, i in flag_cols:
                    if r[i] == "√":
                        item.setdefault("flags", {})[n] = True
            if not item:
                continue
            sub = r[6]
            if sub and not any(x["title"] == sub for x in item["children"]):
                s = {"title": sub}
                fl = [n for n, i in flag_cols if r[i] == "√"]
                if fl:
                    s["flags"] = fl
                item["children"].append(s)
    for u in units:  # 去掉单项且与分项同名的子分项
        for p in u["children"]:
            for it in p["children"]:
                if len(it["children"]) == 1 and it["children"][0]["title"] == it["title"]:
                    it.setdefault("flags", {})
                    it["children"] = []
                if "flags" in it and not it["flags"]:
                    del it["flags"]
    count = {"units": len(units), "parts": 0, "items": 0, "subs": 0}
    for u in units:
        for p in u["children"]:
            count["parts"] += 1
            for it in p["children"]:
                count["items"] += 1
                count["subs"] += len(it["children"])
    return {"project": project, "count": count, "units": units}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(
        json.dumps(
            parse(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "S210"), ensure_ascii=False
        )
    )
