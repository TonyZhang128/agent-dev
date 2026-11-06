"""按配置平台的关系填目标表：公式求值 → 锚点解析 → PDF / Excel 写字（与 OCR 识别无关）。

配置平台（admin）定义锚点（PDF_REGION / EXCEL_RANGE）、公式（@{fld} 表达式）和引用边
（TEMPLATE 拼接 / COPY 复制）；这里在与 admin/src/config/engine.jsx 同一套函数语义下：
  · evaluate      按依赖顺序求公式，单条出错只影响它自己
  · anchor_values 目标表每个锚点的值（TEMPLATE 引用 > COPY 引用 > 同名字段 > 版面栏 > 格子）
  · fill_pdf      空白表样 PDF 上按锚点坐标写字（「年月日」逐字对位、放不下缩字号）
  · compute       编排以上步骤，同一份值再经 grid.fill_xlsx 写表样 Excel
业务端人工改值后也走 compute；照片识别链路见 jianbiao.py，格子提取见 grid.py。
"""

import logging
import math
import re
from pathlib import Path

import pymupdf

from app.ocr.core.layouts import layout_of
from app.ocr.core.media import open_form_pdf, visible_chars
from app.ocr.core.resources import forms
from app.ocr.sheets import grid

FONT = Path(
    "C:/Windows/Fonts/simhei.ttf"
)  # 填表用黑体;Docker(Linux)里没有就用 PyMuPDF 自带的 china-s

logger = logging.getLogger(__name__)


# ───────── 公式求值（与 admin/src/config/engine.jsx 同一套） ─────────


def _nums(a):
    out = []
    for x in a:
        if isinstance(x, (list, tuple)):
            out += _nums(x)
        elif x not in ("", None):
            try:
                out.append(float(x))
            except (TypeError, ValueError):
                pass
    return out


def _round(x, d=0):
    if x is None:
        return None
    v = math.floor(x * 10**d + 0.5) / 10**d  # 与 JS Math.round 一致(.5 进位)
    return int(v) if d == 0 else v


def _rate(cmp):
    def f(std, *a):
        v = _nums(a)
        return (
            _round(len([x for x in v if cmp(x, float(std))]) / len(v) * 1000) / 10
            if v and std not in ("", None)
            else None
        )

    return f


FNS = {
    "AVG": lambda *a: (sum(_nums(a)) / len(_nums(a))) if _nums(a) else None,
    "SUM": lambda *a: sum(_nums(a)),
    "MIN": lambda *a: min(_nums(a)) if _nums(a) else None,
    "MAX": lambda *a: max(_nums(a)) if _nums(a) else None,
    "COUNT": lambda *a: len(_nums(a)),
    "ROUND": _round,
    "IF": lambda c, a, b: a if c else b,
    "PASS_RATE": _rate(lambda x, s: x >= s),
    "PASS_RATE_LE": _rate(lambda x, s: x <= s),
}
REF = re.compile(r"@\{([\w.]+)\}")


def _compile(expr: str):
    """@{fld} 表达式 → Python;只允许白名单函数、数字、字符串、运算符"""
    bare = REF.sub("0", re.sub(r'"[^"]*"', '""', expr))
    bad = [w for w in re.findall(r"[A-Za-z_]\w*", bare) if w not in FNS]
    if bad:
        raise ValueError(f"未知函数:{bad[0]}")
    py = REF.sub(lambda m: f"_v({m.group(1)!r})", expr).replace("&&", " and ").replace("||", " or ")
    py = re.sub(r"(?<![=!<>])!(?!=)", " not ", py)
    return compile(py, "<formula>", "eval")


def _num(v):
    try:
        return float(v) if v not in ("", None) else None
    except (TypeError, ValueError):
        return v


def evaluate(cfg: dict, inputs: dict) -> tuple[dict, dict]:
    """按依赖顺序算公式;返回 (values, errors)"""
    values, errors = dict(inputs), {}
    by = {f["target"]: f for f in cfg.get("formulas", [])}
    order, seen = [], set()

    def visit(k, stack=()):
        if k in seen or k not in by:
            return
        if k in stack:
            raise ValueError("公式循环引用:" + " → ".join(stack + (k,)))
        for r in REF.findall(by[k]["expr"]):
            visit(r, stack + (k,))
        seen.add(k)
        order.append(by[k])

    for k in by:
        visit(k)
    for f in order:
        try:
            values[f["target"]] = eval(
                _compile(f["expr"]),
                {"__builtins__": {}, **FNS, "_v": lambda k: _num(values.get(k))},
            )
        except Exception as e:  # noqa: BLE001 —— 单条公式出错只影响它自己
            logger.warning("公式计算失败：%s (%s)", f["target"], type(e).__name__)
            errors[f["target"]] = str(e)
            values[f["target"]] = None
    return values, errors


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else f"{v:g}"
    return str(v)


def anchor_values(cfg: dict, target: str, values: dict) -> list[dict]:
    """目标表每个 PDF 锚点该写的值:TEMPLATE 引用 > COPY 引用 > 同名字段(与配置平台预览 ref_flow.jsx 同一规则)"""
    anchors = {a["id"]: a for a in cfg.get("anchors", [])}
    fill = lambda t: REF.sub(lambda m: _fmt(values.get(m.group(1))) or "—", t)  # noqa: E731
    out = []
    for a in anchors.values():
        if a["doc"] != target or a.get("kind") != "PDF_REGION":
            continue
        tpl = next(
            (e for e in cfg.get("edges", []) if e["type"] == "TEMPLATE" and e["to"] == a["id"]),
            None,
        )
        cp = next(
            (e for e in cfg.get("edges", []) if e["type"] == "COPY" and e["to"] == a["id"]), None
        )
        if tpl:
            v, src = fill(tpl["template"]), "TEMPLATE " + tpl["id"]
        elif cp and cp["from"] in anchors and _fmt(values.get(anchors[cp["from"]]["field"])):
            v, src = _fmt(values.get(anchors[cp["from"]]["field"])), "COPY " + cp["id"]
        else:  # 引用的来源还没值(如当天监理日志没填)→ 用本表同名字段(简表上填的)
            v, src = _fmt(values.get(a["field"])), "field"
        out.append(
            {
                "anchor": a["id"],
                "field": a["field"],
                "behavior": a.get("behavior", "INPUT"),
                "rect": a["rect"],
                "value": v,
                "src": src,
            }
        )
    # 配置平台没框过的栏:按模板库表样坐标(layouts/jb12.json 表头字段)补上,简表上填了就写进去
    have = {c["field"] for c in out}
    for f in layout_of(target)[1]:
        if f["field"] not in have and _fmt(values.get(f["field"])):
            x, y, w, h = f["rect"]
            out.append(
                {
                    "anchor": "",
                    "field": f["field"],
                    "behavior": f.get("behavior", "INPUT"),
                    "rect": {"x": x, "y": y, "w": w, "h": h},
                    "value": _fmt(values.get(f["field"])),
                    "src": "layout",
                }
            )
    # 表样上其余格子(业务端在表上直接填的 g*,见 grid.py):有值就按格子坐标写
    have = {c["field"] for c in out}
    for k, rect in grid.grid_rects(target).items():
        if k not in have and _fmt(values.get(k)):
            out.append(
                {
                    "anchor": "",
                    "field": k,
                    "behavior": "INPUT",
                    "rect": rect,
                    "value": _fmt(values.get(k)),
                    "src": "grid",
                }
            )
    return out


# ───────── 填表：空白表样 PDF 上写字 ─────────


def _date_marks(pg) -> list:
    """表样上看得见的「年」「月」「日」逐字位置。有的表样叠着一层隐藏文字(扫描件的 OCR 层,渲染方式 3 = 不显示),
    位置和印的字差好几个点,按它写会压字,所以只取显示出来的字(visible_chars)"""
    out = []
    for ch in visible_chars(pg):
        c = chr(ch[0])
        if c in "年月日":
            out.append((c, pymupdf.Rect(ch[3])))
    return out


def _fill_date(pg, box, value: str, marks: list, font: dict) -> bool:
    """日期栏表样上印着「年 月 日」:年、月、日分别写在这三个字前面的空里(整串写会压在「年」前面、错位)。
    栏里没印「年月日」或值不是 yyyy-mm-dd 时返回 False,照常整串写"""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    if not m:
        return False
    # 同一行、栏左沿往右到栏右侧一个栏宽内的「年月日」(栏框常只框了「年」前面那段,印字在框外右侧)
    zone = pymupdf.Rect(
        box.x0, box.y0 - box.height * 0.5, box.x1 + max(box.width, 80), box.y1 + box.height * 0.5
    )
    hit = {}
    for c, r in sorted(marks, key=lambda t: t[1].x0):
        if c not in hit and zone.contains((r.tl + r.br) / 2):
            hit[c] = r
    if len(hit) < 3 or not (hit["年"].x0 < hit["月"].x0 < hit["日"].x0):
        return False
    parts = {"年": m.group(1), "月": str(int(m.group(2))), "日": str(int(m.group(3)))}
    left = {"年": box.x0, "月": hit["年"].x1, "日": hit["月"].x1}
    # 三段写在同一条基线上(文字层叠印两遍的表,两遍上下差两三个点,按各字取会高低不齐)
    base = max(r.y1 for r in hit.values()) - min(r.height for r in hit.values()) * 0.15
    size = min(9.5, min(r.height for r in hit.values()) * 0.95)
    for k in ("年", "月", "日"):
        r, text = hit[k], parts[k]
        gap = r.x0 - left[k] - 1
        # 月、日在空里居中;印得紧的表(空只有半个字宽)把这一段字号缩到放得下,不压印好的字
        fs = size
        while k != "年" and fs > 5.5 and pymupdf.get_text_length(text, fontsize=fs) > gap:
            fs *= 0.92
        tw = pymupdf.get_text_length(text, fontsize=fs)
        x = max(left[k] + 0.5, r.x0 - tw - 2) if k == "年" else left[k] + max(0.5, (gap - tw) / 2)
        pg.insert_text((x, base), text, fontsize=fs, color=(0, 0.2, 0.65), **font)
    return True


def fill_pdf(target: str, cells: list[dict], out: Path) -> str:
    with open_form_pdf(target) as doc:
        if doc is None:
            raise ValueError(f"模板库没有 {target} 的表样 PDF")
        pg = doc[0]
        PW, PH = pg.rect.width, pg.rect.height
        font = (
            {"fontfile": str(FONT), "fontname": "hei"} if FONT.exists() else {"fontname": "china-s"}
        )
        marks = _date_marks(pg)
        for c in cells:
            if not c["value"]:
                continue
            r = c["rect"]
            box = pymupdf.Rect(
                r["x"] * PW, r["y"] * PH, (r["x"] + r["w"]) * PW, (r["y"] + r["h"]) * PH
            )
            if _fill_date(pg, box, c["value"], marks, font):
                continue
            size = min(9.5, box.height * 0.62)
            for _ in range(
                8
            ):  # 放不下就缩小字号;栏够高(两行以上)才竖向居中,矮栏贴上沿写,不压中间的分隔线
                lines = max(
                    1,
                    math.ceil(
                        pymupdf.get_text_length(c["value"], fontsize=size) / max(box.width, 1)
                    ),
                )
                pad = (
                    max(0.0, (box.height - lines * size * 1.25) / 2)
                    if box.height > 2 * size * 1.25
                    else 0.0
                )
                if (
                    pg.insert_textbox(
                        box + (2, pad, 0, 0),
                        c["value"],
                        fontsize=size,
                        color=(0, 0.2, 0.65),
                        align=0,
                        **font,
                    )
                    >= 0
                ):
                    break
                size *= 0.85
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.subset_fonts()  # 只嵌入用到的字(整套黑体约 5 MB)
        doc.save(out, garbage=3, deflate=True)
    return str(out)


# ───────── 编排 ─────────


def compute(
    target: str, cfg: dict, inputs: dict, out_pdf: Path | None, rects: dict | None = None
) -> dict:
    """按配置平台公式 / 引用算出目标表各栏,出填好的 PDF(识别后、人工改值后都走这里)。
    算出来的栏(CALCULATED 公式目标)以公式为准,传进来的旧值不算数。"""
    calc = {f["target"] for f in cfg.get("formulas", [])}
    values, errors = evaluate(cfg, {k: v for k, v in inputs.items() if k not in calc})
    cells = anchor_values(cfg, target, values)
    # 这一张表在业务端挪过 / 改过大小的栏(fill.rects:字段 → {x,y,w,h}):只影响这张表,写 PDF / Excel 都按挪后的位置
    for c in cells:
        r = (rects or {}).get(c["field"])
        if isinstance(r, dict) and all(isinstance(r.get(k), (int, float)) for k in "xywh"):
            c["rect"] = {k: float(r[k]) for k in "xywh"}
    pdf = fill_pdf(target, cells, out_pdf) if out_pdf else ""
    # 同一份值再写一份 Excel(第二册表样附带的 Sheet*.xlsx):配置平台指定了单元格的按单元格,其余按 PDF 上的位置换算
    xlsx = (
        grid.fill_xlsx(target, cells, grid.excel_anchors(cfg, target), out_pdf.with_suffix(".xlsx"))
        if out_pdf
        else grid.ExcelOutput()
    )
    return {
        "target": target,
        "targetName": (forms().get(target) or {}).get("name", ""),
        "values": {k: _fmt(v) for k, v in values.items() if v not in (None, "")},
        "errors": errors,
        "anchors": cells,
        "pdf": pdf,
        "xlsx": xlsx.path,
        "xlsxSkipped": list(xlsx.skipped),
    }
