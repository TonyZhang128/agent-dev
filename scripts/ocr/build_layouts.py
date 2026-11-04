"""模板库:第一册 / 第二册各表版面 → templates/layouts/{book1,jb12}.json
用法:uv run --locked python -m scripts.ocr.build_layouts
用 PDF 文字层(PyMuPDF)找每张表的栏目标签,换算成填写区域(页面百分比,左上原点)。
(由 v5 tools/build_jb_layout.js / build_book1_layout.js 移植,算法不变)
核对:第二册与 v5 输出 100% 一致;第一册 95.4% 一致(PyMuPDF 与 pdf.js 文字切分略有差异,
识别到 ≥5 栏目的表由 61 张增至 91 张)。现行 templates/layouts/book1.json 仍是 v5 已人工核对的版本,重新生成后需逐表核对再替换。"""

import re

from app.ocr.labels import B1, JB, r3
from app.ocr.resources import forms
from scripts.ocr.common import TEMPLATES, asset, page_items, today, write_json


def jb_layout(pdf):
    items = [
        dict(t, s=re.sub(r"\s+", "", t["s"])) for t in page_items(pdf) if len(t["s"].strip()) > 1
    ]
    out = {"header": [], "key": []}
    for rx, field, box, beh in JB:
        hits = sorted([t for t in items if re.search(rx, t["s"])], key=lambda t: t["x"])
        if not hits:
            continue
        x, y, w, h = box(hits[0]["x"], hits[0]["y"] - 0.013)
        out["header"].append(
            {
                "field": field,
                "rect": [r3(x), r3(y), w, h],
                "behavior": beh or ("CALCULATED" if field == "fld_conclusion" else "INPUT"),
            }
        )
    seen = set()  # △ 关键项目:实测表中以 △ 开头的行,合格率列在右侧
    for t in sorted(
        [t for t in items if t["s"].startswith("△") and 0.4 < t["y"] < 0.75], key=lambda t: t["y"]
    ):
        name = re.sub(r"[^一-龥A-Za-z0-9]", "", re.sub(r"[(（].*$", "", t["s"][1:]))
        if name and name not in seen:
            seen.add(name)
            out["key"].append({"name": name, "rect": [0.855, r3(t["y"] - 0.028), 0.065, 0.044]})
    return out


def book1_layout(pdf):
    items = [
        {
            "s": re.sub(r"[：:]$", "", re.sub(r"\s+", "", t["s"])),
            "x": t["x"],
            "y": t["y"] - 0.013,
            "w": t["w"],
        }
        for t in page_items(pdf)
        if len(t["s"].strip()) > 1
    ]
    items = sorted([t for t in items if 0.03 < t["y"] < 0.93], key=lambda t: (t["y"], t["x"]))
    out, used = [], set()
    for rx, field, box, beh, nth in B1:
        if any(o["field"] == field for o in out):
            continue
        hits = [t for t in items if re.search(rx, t["s"]) and id(t) not in used]
        t = (
            (hits[nth] if len(hits) > nth else None)
            if nth is not None
            else (hits[0] if hits else None)
        )
        if not t:
            continue
        used.add(id(t))
        x, y, w, h = box(t)
        out.append(
            {
                "field": field,
                "rect": [r3(min(x, 0.9)), r3(y), r3(min(w, 0.95 - x)), h],
                "behavior": beh or "INPUT",
                "label": t["s"][:16],
            }
        )
    return out


def run(kind):
    is_jb = kind == "jb12"
    codes = [
        c
        for c, f in forms().items()
        if (c.startswith("JB12-") if is_jb else (f.get("book") or "").startswith("第一册"))
        and f.get("pdf")
    ]
    res, miss = {}, 0
    for c in codes:
        p = asset(forms()[c]["pdf"][0])
        if not p.exists():
            miss += 1
            continue
        try:
            res[c] = jb_layout(p) if is_jb else book1_layout(p)
        except Exception:  # noqa: BLE001 —— 个别页损坏不影响整册
            miss += 1
    full = sum(1 for v in res.values() if (len(v["header"]) >= 8 if is_jb else len(v) >= 5))
    write_json(
        TEMPLATES / "layouts" / f"{kind}.json",
        {
            "_meta": {
                "generated": today(),
                "by": "scripts/ocr/build_layouts.py",
                "forms": len(res),
                "full": full,
            },
            "forms": res,
        },
    )
    print(f"{kind}: {len(res)} 张(栏目齐全 {full},缺 PDF {miss})")


if __name__ == "__main__":
    run("jb12")
    run("book1")
