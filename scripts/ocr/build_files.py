"""模板库:表号 → 规范表样页索引 → templates/forms/files.json
用法:uv run --locked python -m scripts.ocr.build_files
以已拆分的单页文件为准(第 N 页 ↔ _N.pdf ↔ SheetN):
  第二册     pdf/四川省公路工程施工监理统一用表-第二册/施工监理用表-第2册_N.pdf      excel/施工监理用表-第2册(1)/SheetN.xlsx
  第一册     pdf/四川省公路工程施工监理统一用表-第一册/第一册 总则(1-8共139页)_N.pdf   表号由 review/第一册总则_全文.txt 解析(tools/lib_book1.js 同规则)
  JTG G10    pdf/JTG G10-2016 公路工程施工监理规范/…_N.pdf      附录 B/C/D 格式表 → 对应资料的标准表样
  目录名与拆页文件名前缀分开(2026-10-29 资料目录改名):目录 / 前缀对照见模板库 library/pdf_dirs.json
只收依据(模板库);各项目的实填件、施工图在 projects/<公路>/,不进本索引。
(由 v5 tools/build_files.js 移植;v5 的「分项工程开工、交工程序用表」实填册属泸定至石棉一期业务库,不再收进模板)"""

import re

from scripts.ocr.common import ADMIN, TEMPLATES, asset, page_lines, today, write_json
from scripts.ocr.jl_pdf import parse_forms

B1 = "第一册 总则（1-8共139页）"  # 拆页文件名前缀(也是 book 名)
B2 = "施工监理用表-第2册"
G10 = "JTG G10-2016 公路工程施工监理规范"
DIR = {
    B1: "四川省公路工程施工监理统一用表-第一册",
    B2: "四川省公路工程施工监理统一用表-第二册",
    G10: G10,
}  # 前缀 → 所在目录
EVAL_PAGES = {
    81: ("BDPD", "建设项目（合同段）工程质量检验评定表"),
    82: ("DWPD", "单位工程质量检验评定表"),
    83: ("FBPD", "分部工程质量检验评定表"),
    84: ("PD-EVAL", "分项工程质量检验评定表"),
    85: ("JSPF", "建设项目工程质量检验评分表"),
    86: ("JL-BDPF", "合同段工程质量检验评分表"),
    87: ("JL-DWPD", "单位工程质量检验评定表(监理)"),
    88: ("JL-FBPD", "分部工程质量检验评定表(监理)"),
    89: ("JL-WG", "分部工程外观检查记录表"),
    90: ("JL-ZLJ", "分部质量保证资料检查记录表"),
    91: ("JL-FXHZ", "分项工程质量检验数据汇总表"),
}
NAMES = {
    "JLB14": "监理月报(封面)",
    "JLB14-1": "监理月报 · 本月大事记",
    "JLB14-2": "监理月报 · 附表",
    "JLB14-3": "监理人员月度考勤表",
    "TJ1": "检查通用记录表",
    "TJ6": "工程照片",
    "TJ14": "现场网格员日常工作记录表(工地安全日志)",
    "CJ7": "四等水准测量记录表",
    "CJ10": "路基路面纵断高程横坡度宽度检测记录表",
}
MARKS = [
    (1, "目录"),
    (2, "总说明"),
    (10, "单位、分部、分项工程划分规则"),
    (17, "监理程序用表"),
    (81, "质量评定用表"),
    (92, "通用记录表"),
    (108, "测量记录表"),
    (122, "试验检测统计判定表"),
]
G10_TOC = [
    (1, "封面"),
    (3, "公告"),
    (4, "前言"),
    (6, "目次"),
    (8, "1 总则"),
    (9, "2 术语"),
    (11, "3 基本规定"),
    (13, "4 施工准备阶段监理"),
    (16, "5 施工阶段监理"),
    (21, "6 验收与缺陷责任期阶段监理"),
    (22, "7 合同事项管理"),
    (24, "8 监理工地会议"),
    (26, "9 监理资料"),
    (28, "附录A 监理旁站项目"),
    (29, "附录B 监理记录"),
    (33, "附录C 分项工程(中间)交工证书"),
    (34, "附录D 监理指令单"),
    (35, "本规范用词用语说明"),
    (36, "条文说明"),
]
G10_FORMS = [
    (
        "JL-LOG",
        "监理日志",
        "附录B.4 · 第9.2.6条:应按附录B.4格式填写,经驻地监理工程师或总监审核",
        r"B\.4[\s\S]*监\s*理\s*日\s*志",
        False,
    ),
    ("JL-XS", "巡视记录", "附录B.1 · 第5.1.3条:主要工程每天不少于1次", r"B\.1\s*巡视记录", False),
    ("JL-PZ", "旁站记录", "附录B.2 · 第5.1.4条:附录A所列旁站项目", r"B\.2\s*旁站记录", False),
    ("JL-CJ", "抽检记录", "附录B.3 · 第5.2.4条", r"B\.3[\s\S]*抽检\s*记录", False),
    (
        "JLB35",
        "分项工程(中间)交工证书",
        "附录C · 第5.2.6条:评定合格的签发",
        r"附录C\s*分项工程",
        True,
    ),
    ("JL-ZL", "监理指令单", "附录D · 第5.2.7条", r"附录D\s*监理指令单", False),
]


def pages_of(dirname):
    d = asset(f"pdf/{DIR.get(dirname, dirname)}")
    return (
        sorted(int(m.group(1)) for f in d.iterdir() if (m := re.search(r"_(\d+)\.pdf$", f.name)))
        if d.exists()
        else []
    )


def parse_book1(txt):
    """第一册全文(=== 第 N 页 分隔)→ [{code, name, pages}](同 tools/lib_book1.js)"""
    parts = re.split(r"^=== 第 (\d+) 页$", txt, flags=re.M)
    forms = {}
    for i in range(1, len(parts), 2):
        n = int(parts[i])
        if n < 19:
            continue
        body = re.sub(r"(?<=\S) (?=\S)", "", parts[i + 1])
        lines = [s.strip() for s in body.split("\n") if s.strip()]
        if n in EVAL_PAGES:
            code, name = EVAL_PAGES[n]
        else:
            # 表号两侧按 ASCII 单词边界(Python 的 \b 会把汉字当单词字符,与 JS 不同)
            m = re.search(
                r"(?<![A-Za-z0-9_])(JLB\d+(?:-\d+)?|TJ\d+|CJ\d+|SP\d+)(?![A-Za-z0-9_])", body
            )
            if not m:
                continue
            code = m.group(1)
            name = next(
                (
                    s
                    for s in lines
                    if re.search(r"(表|单|书|令|纪要|日志|记录|清单)$", s)
                    and len(s) < 32
                    and not re.search(r"目录|项目$|^\d", s)
                    and code not in s
                ),
                "",
            )
            name = re.sub(r"^（|）$", "", name)
        if code in forms:
            forms[code]["pages"].append(n)
            continue
        forms[code] = {"code": code, "name": NAMES.get(code, name), "pages": [n]}
    return list(forms.values())


def exists(rel):
    return asset(rel).exists()


def main():
    forms = {}
    # 第二册:整册解析(续页、重复编号重编)
    for f in parse_forms(asset(f"pdf/{DIR[B2]}/{B2}.pdf")):
        pdf = [p for p in (f"pdf/{DIR[B2]}/{B2}_{n}.pdf" for n in f["pages"]) if exists(p)]
        per = [p for p in (f"excel/{B2}(1)/Sheet{n}.xlsx" for n in f["pages"]) if exists(p)]
        forms[f["code"]] = {
            "name": f["name"],
            "orig": f.get("orig") or None,
            "book": B2,
            "pages": f["pages"],
            "pdf": pdf or None,
            "excel": {"path": per[0], "files": per}
            if per
            else {"path": f"excel/{B2}.xlsx", "sheets": [f"Sheet{n}" for n in f["pages"]]}
            if exists(f"excel/{B2}.xlsx")
            else None,
        }
    # 第一册:以拆分目录 + 抽取文本为准;同号表以第一册为准,旧版存 old
    txt = ADMIN / "review/第一册总则_全文.txt"
    for f in parse_book1(txt.read_text(encoding="utf-8")) if txt.exists() else []:
        prev = forms.get(f["code"])
        pdf = [p for p in (f"pdf/{DIR[B1]}/{B1}_{n}.pdf" for n in f["pages"]) if exists(p)]
        forms[f["code"]] = {
            "name": f["name"],
            "book": B1,
            "pages": f["pages"],
            "pdf": pdf or None,
            "excel": (prev or {}).get("excel"),
            "old": {"book": prev["book"], "name": prev["name"], "pdf": prev["pdf"]}
            if prev
            else None,
        }
    forms = {k: {a: b for a, b in v.items() if b is not None} for k, v in forms.items()}
    # 规范:附录 B/C/D 格式表 → 对应资料的标准表样
    regs = {
        "book": G10,
        "dir": f"pdf/{DIR[G10]}",
        "pages": [],
        "marks": [{"at": p - 1, "label": t} for p, t in G10_TOC],
        "forms": {},
    }
    for n in pages_of(G10):
        file = f"pdf/{DIR[G10]}/{G10}_{n}.pdf"
        regs["pages"].append(file)
        cur = next((t for p, t in reversed(G10_TOC) if p <= n), "")
        if re.match(r"^附录[BCD]", cur):
            t = page_lines(asset(file))
            if re.search(r"编\s*号", t):
                for code, name, clause, rx, std in G10_FORMS:
                    if code not in regs["forms"] and re.search(rx, t):
                        regs["forms"][code] = {
                            "name": name,
                            "clause": clause,
                            "pdf": [file],
                            "page": n,
                            "std": std,
                        }
    book1 = {
        "book": B1,
        "pages": [f"pdf/{DIR[B1]}/{B1}_{n}.pdf" for n in pages_of(B1)],
        "marks": [{"at": p - 1, "label": t} for p, t in MARKS],
    }
    write_json(
        TEMPLATES / "forms/files.json",
        {
            "_meta": {
                "generated": today(),
                "by": "scripts/ocr/build_files.py",
                "note": "表号 → 规范表样页(第一册 / 第二册 / JTG G10-2016)",
            },
            "forms": forms,
            "files": [],
            "regs": regs,
            "book1": book1,
        },
    )
    print(
        f"{len(forms)} 张表(单页PDF {sum(1 for f in forms.values() if f.get('pdf'))});规范 {len(regs['pages'])} 页,格式表 {'/'.join(regs['forms'])}"
    )


if __name__ == "__main__":
    main()
