"""第二册监理抽检用表:按 PDF 逐页解析出「表本身」的信息(build_forms / build_approval / build_files 共用)
  - 只认含「抽检人 / 审核人」签字栏的表页(跳过目录、填报规定页)
  - 编号取表头「编 号:」(容忍「JB12-8.10.5- 2」这类断行空格)
  - 无编号、无签字栏的页作为上一张表的续页
  - 原表编号重复时按规律重新编号(子号顺延 / 章内下一个空节号),原编号记在 orig
(由 v5 tools/lib_jl_pdf.js 移植;文字层改用 PyMuPDF,不再依赖 pdftotext)"""

import re

from scripts.ocr.common import clean, layout_text

CH_CAT = {
    4: "路基工程",
    5: "路基工程",
    6: "路基工程",
    7: "路面工程",
    8: "桥梁工程",
    9: "桥梁工程",
    10: "隧道工程",
    11: "交通安全工程",
    12: "绿化工程",
    13: "声屏障工程",
}


def parse_forms(pdf):
    forms = []
    for i, pg in enumerate(layout_text(pdf)):
        flat = re.sub(r"[ \t]+", " ", pg)
        signs = [s for s in ("抽检人", "审核人") if s in flat]
        m = re.search(r"编\s*号\s*[：:]?\s*(JB12-\s*\d+(?:\.\d+)+(?:-\s*\d+)?)", flat)
        prev = forms[-1] if forms else None
        if not m:
            # 续页:无编号,紧跟上一张表页(签字栏可能落在续页,如交通标线);下一章的「填报规定」页不算续页
            if prev and clean(pg) and prev["pages"][-1] == i and "填报规定" not in flat:
                prev["pages"].append(i + 1)
                prev["signs"] += [x for x in signs if x not in prev["signs"]]
            continue
        if not signs:
            continue
        code = re.sub(r"\s+", "", m.group(1))
        nm = re.search(r"([^\s_：:]{2,40}?(?:抽检记录表|记录表|试验报告))", flat)
        ch = int(re.match(r"^JB12-(\d+)\.", code).group(1))
        forms.append(
            {
                "code": code,
                "name": re.sub(r"表表$", "表", nm.group(1) if nm else ""),
                "page": i + 1,
                "pages": [i + 1],
                "signs": signs,
                "cat": CH_CAT.get(ch, ""),
            }
        )
    # 重复编号 → 按规律重新编号(原编号保留在 orig)
    used = {f["code"] for f in forms}
    groups = {}
    for f in forms:
        groups.setdefault(f["code"], []).append(f)
    for code, g in groups.items():
        if len(g) < 2:
            continue
        sub = re.match(r"^(.*-)(\d+)$", code)
        for k, f in enumerate(g):
            f["orig"] = code
            if k == 0:
                f["issue"] = f"原表编号 {code} 共 {len(g)} 张重复,本张保留原号"
                continue
            if sub:
                n = int(sub.group(2)) + k
                while sub.group(1) + str(n) in used:
                    n += 1
                nc = sub.group(1) + str(n)
            else:
                mm = re.match(r"^(JB12-\d+\.)(\d+)(\..*)$", code)
                n = int(mm.group(2)) + 1
                while f"{mm.group(1)}{n}{mm.group(3)}" in used:
                    n += 1
                nc = f"{mm.group(1)}{n}{mm.group(3)}"
            used.add(nc)
            f["code"] = nc
            f["issue"] = f"原表编号 {code} 重复,按规律重新编号为 {nc}"
    for f in forms:
        f["id"] = f["code"]
    return forms
