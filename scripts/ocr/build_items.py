"""模板库:第二册 JB12 抽检记录表的关键项目(△)与结构主要尺寸 → templates/forms/form_items.json
用法:uv run --locked python -m scripts.ocr.build_items
每张表 → { key:[关键项目], main:[结构主要尺寸] }(表头「关键项目:」「结构主要尺寸:」两行,抽检必测)
(由 v5 tools/build_items.js 移植,规则不变)
核对:与 v5 输出 175/221 完全一致;其余差异多为 v5 的 pdf.js 文字层重复抽取造成的残字(如「断面尺可」「沥青含」),
PyMuPDF 版本更干净,个别表(如 JB12-5.6.2 的「铺碱厚度」)少一项。现行模板仍是 v5 版,重新生成后需逐表核对再替换。"""

import json
import re

from scripts.ocr.common import ASSET, TEMPLATES, page_lines, today, write_json

DIR = ASSET / "pdf/四川省公路工程施工监理统一用表-第二册"


def items(text, label):
    ls = [ln for ln in text.split("\n") if label in ln]
    if not ls:
        return []
    t = sorted((ln.split(label)[-1] for ln in ls), key=len, reverse=True)[
        0
    ]  # 取最长的一版(全角版通常完整)
    t = re.sub(r"[。]$", "", re.sub(r"^[:：]\s*", "", t))
    out = []
    for x in re.split(
        r"[、,，;；]|关?键项目|结?构主要尺寸|各构主要尺寸", t
    ):  # 半角版与全角版拼在一起时按残留的标签片段再切开
        x = re.sub(r"[:：]", "", re.sub(r"\s+", "", x)).strip()
        if (
            x
            and not re.match(r"^[/／]+$", x)
            and 2 <= len(x) <= 20
            and not re.match(r"^[\d.]+$", x)
            and x not in out
        ):
            out.append(x)
    return out


def main():
    cat = json.loads((TEMPLATES / "forms/jl_forms.json").read_text(encoding="utf-8"))["catalog"]
    out, empty = {}, []
    for f in cat.values():
        if not f["code"].startswith("JB12-"):
            continue
        text = ""
        for pg in f.get("pages") or [f["page"]]:
            p = DIR / f"施工监理用表-第2册_{pg}.pdf"
            if p.exists():
                text += page_lines(p) + "\n"
        key = items(text, "关键项目")
        main_ = [x for x in items(text, "结构主要尺寸") if x not in key]
        out[f["code"]] = {"key": key, "main": main_}
        if not key and not main_:
            empty.append(f["code"])
    write_json(
        TEMPLATES / "forms/form_items.json",
        {
            "_meta": {
                "generated": today(),
                "by": "scripts/ocr/build_items.py",
                "note": "JB12 关键项目(△)/ 结构主要尺寸",
            },
            "forms": out,
        },
    )
    print("forms", len(out), "empty", len(empty))


if __name__ == "__main__":
    main()
