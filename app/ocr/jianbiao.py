"""现场简表识别 → 按配置平台的关系填新表(最基本的「轮廓 + 定位」):
  1. 轮廓:照片灰度 → 自适应二值 → 找面积最大的四边形 = 简表外框(找不到就整张照片当外框)
  2. 定位:外框四角透视校正成标准尺寸(宽 1000,高 = 1000 × 简表 aspect),简表格子坐标(layouts/jianbiao.json,外框内比例)直接裁格子
  3. 取值:每个格子单独 OCR,去掉格子里印的栏目名,数字栏只留数字、日期栏归一成 yyyy-mm-dd
  4. 串联:识别出的字段(与目标表同名 fld_*)+ 项目资料带入的字段(BOUND)→ 配置平台公式(@{fld} 表达式,与管理端 engine.jsx 同一套函数)
           → 引用(COPY 复制 / TEMPLATE 拼接)→ 目标表每个锚点的值
  5. 填表:目标表空白表样 PDF 上按锚点坐标(页面比例)写字,另存到数据池同一分项的 资料/ 下
结果是草稿,由业务端 / App 人工核对后确认。"""

import math
import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from app.ocr import grid
from app.ocr.form_ocr import date_value, layout_of, ocr, read_image
from app.ocr.resources import asset, forms, get_resources, resource_cache

FONT = Path(
    "C:/Windows/Fonts/simhei.ttf"
)  # 填表用黑体;Docker(Linux)里没有就用 PyMuPDF 自带的 china-s
W = 1000


@resource_cache(maxsize=1)
def layouts() -> dict:
    return get_resources().load("layouts/jianbiao.json")["forms"]


def jianbiao_of(target: str) -> tuple[str, dict] | tuple[None, None]:
    """目标表号 → (简表号, 简表版面);没有对应简表返回 (None, None)"""
    for code, f in layouts().items():
        if f["target"] == target or code == target:
            return code, f
    return None, None


# ───────── 1. 轮廓:找外框 ─────────


def _order(pts: np.ndarray) -> np.ndarray:
    """四个角排成 左上、右上、右下、左下"""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32
    )


def find_frame(img) -> tuple[np.ndarray, str]:
    """面积最大、占照片 ≥ 20% 的四边形;返回 (四角, how)"""
    h, w = img.shape[:2]
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 10)
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))  # 补上手机拍照断开的框线
    cnts, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(c) < 0.2 * w * h:
            break
        q = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(q) == 4 and cv2.isContourConvex(q):
            return _order(q.reshape(4, 2).astype(np.float32)), "contour"
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32), "whole"


def find_table(img) -> tuple[np.ndarray, str]:
    """先找纸(照片里最大的四边形),校正后在纸里再找表格外框(粗黑框):格子坐标是相对表格外框的。
    返回照片上表格外框的四角;纸里找不到外框就用纸的四角。"""
    paper, how = find_frame(img)
    pw = round(np.linalg.norm(paper[1] - paper[0]))
    ph = round(np.linalg.norm(paper[3] - paper[0]))
    if pw < 50 or ph < 50:
        return paper, how
    M = cv2.getPerspectiveTransform(
        paper, np.array([[0, 0], [pw - 1, 0], [pw - 1, ph - 1], [0, ph - 1]], np.float32)
    )
    flat = cv2.warpPerspective(img, M, (pw, ph))
    m = max(4, round(min(pw, ph) * 0.01))  # 去掉纸边一圈,纸边本身也是一个四边形
    inner, ihow = find_frame(flat[m : ph - m, m : pw - m])
    if ihow != "contour":
        return paper, how
    back = cv2.perspectiveTransform((inner + m).reshape(1, 4, 2), np.linalg.inv(M)).reshape(4, 2)
    return back.astype(np.float32), how + "+table"


# ───────── 2. 定位:透视校正 + 按格子裁 ─────────


def warp(img, quad: np.ndarray, aspect: float):
    H = round(W * aspect)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (W, H))


def _dedup(boxes: list[dict]) -> list[dict]:
    """OCR 偶尔把同一个字再单独认一遍(「97.1」后面又跟一个「1」,框压在「97.1」的框里):被大框盖住大半的小框去掉"""

    def inside(a, b):
        ax0, ay0, ax1, ay1 = a["box"]
        bx0, by0, bx1, by1 = b["box"]
        iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
        return iw * ih > 0.5 * (ax1 - ax0) * (ay1 - ay0)

    area = lambda b: (b["box"][2] - b["box"][0]) * (b["box"][3] - b["box"][1])  # noqa: E731
    return [
        a
        for a in boxes
        if not any(b is not a and area(b) > area(a) and inside(a, b) for b in boxes)
    ]


def _cell_value(boxes: list[dict], label: str, typ: str) -> tuple[str, float]:
    """格子里认出的字 → 值:去掉印的栏目名;数字栏只取数字"""
    boxes = _dedup(boxes)
    lab = re.sub(r"\s", "", label)
    # 印的栏目名在格子左上角(小字、单独一个框),整框就是栏目名(或它的后半截:裁格子时头一两个字可能被裁掉)的去掉
    boxes = [
        b
        for b in boxes
        if not (
            lab
            and re.sub(r"\s", "", b["s"])
            and lab.endswith(re.sub(r"\s", "", b["s"]))
            and (len(re.sub(r"\s", "", b["s"])) >= 2 or lab.isdigit())
        )
    ]
    boxes = sorted(boxes, key=lambda b: (round(b["box"][1] / 12), b["box"][0]))
    text = re.sub(r"\s", "", " ".join(b["s"] for b in boxes))
    # 栏目名和填的字 OCR 连成一个框时:按「栏目名的后缀」去掉;印刷字被认错一个字(处理→里)时按后 2 个字去
    for k in range(len(lab)):
        if len(lab) - k >= 2 and text.startswith(lab[k:]):
            text = text[len(lab) - k :]
            break
    else:
        i = text.find(lab[-2:]) if len(lab) >= 3 else -1
        if 0 <= i <= 2:
            text = text[i + 2 :]
    text = re.sub(r"^[:：_＿]+", "", text)
    conf = round(sum(b["conf"] for b in boxes) / len(boxes), 3) if boxes else 0.0
    if typ == "number":
        text = re.sub(r"[一—－–](?=\d)", "-", text)  # 手写的负号常被认成「一」
        m = re.findall(r"-?\d+(?:\.\d+)?", text)
        return (m[-1] if m else ""), conf  # 格子左上角印的点号(1~5)在前,手写的数在后
    if typ == "date":
        return date_value(text), conf
    return text, conf


def _erase_lines(crop):
    """格子边上残留的框线(校正有一两个像素偏差时会裁进来)涂白,免得被认成「1」或「一」:
    横线 = 宽度过半的横向连续黑段,竖线 = 高度过半的竖向连续黑段"""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 21, 12)
    h, w = bw.shape
    lines = cv2.morphologyEx(
        bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, w // 2), 1))
    )
    lines |= cv2.morphologyEx(
        bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, h // 2)))
    )
    out = crop.copy()
    out[cv2.dilate(lines, np.ones((3, 3), np.uint8)) > 0] = 255
    return out


def read_cells(sheet, cells: list[dict]) -> tuple[dict, list[dict]]:
    """每个格子单独 OCR(往里收 4%,避开框线)"""
    H = sheet.shape[0]
    values, detail = {}, []
    for c in cells:
        if not c.get("field"):  # 简表上印好的检查项目名,不识别
            continue
        x, y, w, h = c["rect"]
        x0, y0 = int((x + w * 0.04) * W), int((y + h * 0.04) * H)
        x1, y1 = int((x + w * 0.96) * W), int((y + h * 0.96) * H)
        crop = sheet[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop = _erase_lines(crop)
        crop = cv2.copyMakeBorder(
            crop, 16, 16, 16, 16, cv2.BORDER_CONSTANT, value=(255, 255, 255)
        )  # OCR 对贴边的字不敏感
        val, conf = _cell_value(ocr(crop), c.get("label", ""), c.get("type", ""))
        if val:
            values[c["field"]] = val
        detail.append(
            {
                "field": c["field"],
                "label": c.get("label", ""),
                "value": val,
                "conf": conf,
                "rect": [x0, y0, x1, y1],
            }
        )
    return values, detail


# ───────── 4. 串联:配置平台公式 + 引用(与 admin/src/config/engine.jsx 同一套) ─────────


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


# ───────── 5. 填表:空白表样 PDF 上写字 ─────────


def _date_marks(pg) -> list:
    """表样上看得见的「年」「月」「日」逐字位置。有的表样叠着一层隐藏文字(扫描件的 OCR 层,渲染方式 3 = 不显示),
    位置和印的字差好几个点,按它写会压字,所以只取显示出来的字(get_texttrace type ≠ 3)"""
    out = []
    for t in pg.get_texttrace():
        if t["type"] == 3:
            continue
        for ch in t["chars"]:
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
    f = forms().get(target) or {}
    if not f.get("pdf"):
        raise ValueError(f"模板库没有 {target} 的表样 PDF")
    with pymupdf.open(asset(f["pdf"][0])) as doc:
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


# ───────── 整条流程 ─────────


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


def run(photo: Path, target: str, cfg: dict, bound: dict, out_pdf: Path | None) -> dict:
    """现场简表照片:轮廓定位 → 格子识别 → compute(简表上手写的优先于项目资料带入的)"""
    code, lay = jianbiao_of(target)
    if not lay:
        raise ValueError(f"模板库没有 {target} 的简表版面(layouts/jianbiao.json)")
    img = read_image(photo)
    quad, how = find_table(img)
    sheet = warp(img, quad, lay["aspect"])
    got, detail = read_cells(sheet, lay["cells"])
    out = compute(target, cfg, {**bound, **got}, out_pdf)
    if out_pdf:
        cv2.imencode(".jpg", sheet)[1].tofile(
            str(out_pdf.with_suffix(".warp.jpg"))
        )  # 校正后的简表,便于人工核对定位
    return {
        "jianbiao": code,
        "jianbiaoName": lay["name"],
        "frame": {"how": how, "quad": quad.round().astype(int).tolist()},
        "recognized": got,
        "detail": detail,
        **out,
    }
