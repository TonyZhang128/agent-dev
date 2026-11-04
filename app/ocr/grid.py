"""表样全部格子:空白表样 PDF 渲染成图 → 横竖框线 → 每个封闭格子(页面比例坐标)。
业务端右侧「填好的表」据此让每一格都能填,不再只限配置平台框过的栏;填好的值按同一坐标写进 PDF,
再按同一位置换算到 Excel 表样(第二册附带的 Sheet*.xlsx)的单元格,PDF 与 Excel 出自同一份值。
  · 格子键 g<y千分比>_<x千分比>:同一表样每次算出来相同,存进填报草稿(fill.values)
  · 印了字的格子(栏目名、规定值)只作标签,不可填;空格子的名称 = 同一行左边最近的栏目 · 同一列上面最近的栏目
  · 版面坐标(layouts/jb12、book1)里已有的栏(表头 fld_*)优先,与它们重叠的格子不再单列"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import openpyxl
import pymupdf
from openpyxl.utils import get_column_letter

from app.ocr.form_ocr import layout_of
from app.ocr.resources import asset, forms, resource_cache

PX = 1400  # 渲染宽度(像素)


def _pdf(code: str) -> Path | None:
    f = forms().get(code) or {}
    return asset(f["pdf"][0]) if f.get("pdf") and asset(f["pdf"][0]).exists() else None


def _text(s: str) -> str:
    """去空白;粗体字表样里同一段字画两遍(施工单位施工单位),折成一遍"""
    t = re.sub(r"\s+", "", s or "")
    half = len(t) // 2
    return t[:half] if len(t) % 2 == 0 and half and t[:half] == t[half:] else t


def _overlap(a: dict, b: dict) -> float:
    """a 被 b 盖住的比例"""
    iw = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    ih = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    return iw * ih / max(a["w"] * a["h"], 1e-9)


@resource_cache(maxsize=512)
def cells(code: str) -> tuple:
    """表样第 1 页的格子:({key, rect:{x,y,w,h}, text}, …),按从上到下、从左到右"""
    pdf = _pdf(code)
    if not pdf:
        return ()
    with pymupdf.open(pdf) as doc:
        pg = doc[0]
        W, H = pg.rect.width, pg.rect.height
        z = PX / W
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)
        bw = (cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) < 160).astype(np.uint8) * 255
        h, w = bw.shape
        lines = cv2.morphologyEx(
            bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        )
        lines |= cv2.morphologyEx(
            bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
        )
        lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
        n, _, st, _ = cv2.connectedComponentsWithStats(255 - lines, connectivity=4)
        # 只取看得见的字(texttrace type 0 填充 / 1 描边);type 3 是扫描件叠的隐藏文字层,有错字、重复,
        # 拼进栏目名就成了「实测值或实测偏差值实值或实测」(与 form_ocr.template_runs 同一规则)
        chars = [
            (chr(ch[0]), (ch[3][0] + ch[3][2]) / 2, (ch[3][1] + ch[3][3]) / 2, ch[3][0])
            for sp in pg.get_texttrace()
            if sp["type"] != 3
            for ch in sp["chars"]
            if chr(ch[0]).strip()
        ]
        out = []
        for i in range(1, n):
            x, y, cw, ch, area = st[i]
            # 贴着页边的是表外空白;太小的是线交叉处的碎块;面积远小于外接框的是不规则的表外区域
            if (
                x == 0
                or y == 0
                or x + cw >= w
                or y + ch >= h
                or cw < 15
                or ch < 12
                or area < 0.6 * cw * ch
            ):
                continue
            r = pymupdf.Rect(x / z, y / z, (x + cw) / z, (y + ch) / z)
            rect = {
                "x": round(r.x0 / W, 4),
                "y": round(r.y0 / H, 4),
                "w": round(r.width / W, 4),
                "h": round(r.height / H, 4),
            }
            # 按 PDF 内容流里画字的先后取(就是表上的阅读顺序;按坐标重排会把同一格里左右两栏的字交错拼在一起),
            # 同一位置重画的字(粗体描边)只留一次
            seen, inside = set(), []
            for c, x, y, x0 in chars:
                if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1 and (c, round(x0), round(y)) not in seen:
                    seen.add((c, round(x0), round(y)))
                    inside.append(c)
            out.append(
                {
                    "key": f"g{round(rect['y'] * 1000):03d}_{round(rect['x'] * 1000):03d}",
                    "rect": rect,
                    "text": _text("".join(inside)),
                    # 字的位置(页面比例):合并的表头格里有几段栏目名时,按空格子的横向位置取它正上方那一段
                    "chars": tuple(
                        (c, round(x / W, 4), round(y / H, 4))
                        for c, x, y, _ in chars
                        if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1
                    ),
                }
            )
    out.sort(key=lambda c: (c["rect"]["y"], c["rect"]["x"]))
    return tuple(out)


def _short(t: str) -> str:
    """栏目名整理:扫描件表样的隐藏文字层把同一段字又认了一遍(常有错字),拼在后面 ——
    「实测值或实测偏差值实值或实测」「检查结论检查结诊」「合格率（%）合格率(%)」;
    从第 2 个字起找与开头 2 个字相同的位置,其后的是重复,截掉;只留第一行要点(到第一个句号 / 编号前),最长 12 字"""
    t = re.sub(r"[□☐]", "", t)
    # 重复段从第 i 个字起又是开头那几个字(允许中间错一个字):i 取最靠后、且其后与开头相同的前缀最长的位置
    best, keep = 0, len(t)
    for i in range(3, len(t) - 1):
        same = sum(1 for a, b in zip(t[i:], t, strict=False) if a == b)
        same = max(
            same, sum(1 for a, b in zip(t[i:], t[1:], strict=False) if a == b) + (t[i] == t[0])
        )  # 扫描层漏认一个字(实测值 → 实值)
        span = min(len(t) - i, i)
        if (
            i * 2 >= len(t) - 1
            and span >= 2
            and same >= max(2, span * 0.5)
            and t[i] == t[0]
            and same > best
            and len(t) - i >= 2
            and len(t) - i <= i
        ):
            best, keep = same, i
    t = t[:keep]
    t = re.split(r"(?<=.)(?:\d+\.|[。;；])", t)[0]
    return t[:12]


def _label(c: dict, all_cells: tuple) -> str:
    """空格子的名称:同一行左边最近印字格 · 同一列上面最近印字格(都没有就用位置)"""
    r = c["rect"]
    cy, cx = r["y"] + r["h"] / 2, r["x"] + r["w"] / 2
    left = [
        o
        for o in all_cells
        if o["text"]
        and o["rect"]["x"] + o["rect"]["w"] <= r["x"] + 0.002
        and o["rect"]["y"] - 0.002 <= cy <= o["rect"]["y"] + o["rect"]["h"] + 0.002
    ]
    up = [
        o
        for o in all_cells
        if o["text"]
        and o["rect"]["y"] + o["rect"]["h"] <= r["y"] + 0.002
        and o["rect"]["x"] - 0.002 <= cx <= o["rect"]["x"] + o["rect"]["w"] + 0.002
    ]
    clip = lambda s: _short(s)  # noqa: E731
    parts = []
    if left:
        parts.append(clip(max(left, key=lambda o: o["rect"]["x"])["text"]))
    # 列标题只取同一块表格里紧挨着的上一格;隔着成段说明(外观质量「□1.钢筋表面无…」)或离得远的不算 ——
    # 处理意见、审核人这些整行栏只用左边的栏目名
    if up:
        near_head = max(up, key=lambda o: o["rect"]["y"])
        gap = r["y"] - (near_head["rect"]["y"] + near_head["rect"]["h"])
        # 中间隔着别的印字格(另一块表)就不算;实测区下面几行与列标题之间只有空格子,照样算
        between = [
            o
            for o in all_cells
            if o["text"]
            and o is not near_head
            and o["rect"]["y"] >= near_head["rect"]["y"] + near_head["rect"]["h"] - 0.002
            and o["rect"]["y"] + o["rect"]["h"] <= r["y"] + 0.002
            and o["rect"]["x"] - 0.002 <= cx <= o["rect"]["x"] + o["rect"]["w"] + 0.002
        ]
        if (
            between
            or gap > 0.2
            or re.match(r"^\D{0,6}\d+\.", near_head["text"])
            or len(near_head["text"]) > 40
            or (left and r["w"] > 0.3)
        ):
            up = []
    if up:
        head = max(up, key=lambda o: o["rect"]["y"])
        # 表头格比空格子宽(合并格,如「实测值或实测偏差值 | 合格率(%)」):字按位置分成几段(横向隔得远的另起一段),
        # 取横向中心离空格子最近的那一段 —— 实测格得「实测值或实测偏差值」,合格率格得「合格率(%)」
        t = head["text"]
        if head["rect"]["w"] > r["w"] * 1.8 and head.get("chars"):
            runs = []
            for ch, x, y in sorted(head["chars"], key=lambda c: (c[1], c[2])):
                if runs and x - runs[-1]["x1"] < 0.03:
                    runs[-1]["c"].append((y, x, ch))
                    runs[-1]["x1"] = x
                else:
                    runs.append({"c": [(y, x, ch)], "x0": x, "x1": x})
            run = min(runs, key=lambda u: abs((u["x0"] + u["x1"]) / 2 - cx))
            t = _text(
                "".join(
                    ch for _, _, ch in sorted(run["c"], key=lambda c: (round(c[0] * 200), c[1]))
                )
            )
        t = clip(t)
        if t and t not in parts:
            parts.append(t)
    return " · ".join(parts) or f"第 {round(r['y'] * 100)}% 行格子"


# 表头栏的中文名(版面坐标里只有字段号,表样上又没有可取的栏目字时用)
FIELD_NAME = {
    "fld_supervisor": "监理单位",
    "fld_contractor": "施工单位",
    "fld_contract_sec": "合同段",
    "fld_sampler": "抽检人",
    "fld_sample_date": "抽检日期",
    "fld_location": "工程部位",
    "fld_conclusion": "检查结论",
    "fld_sv_opinion": "处理意见",
    "fld_reviewer": "审核人",
    "fld_review_date": "审核日期",
    "fld_project": "项目名称",
    "fld_item_name": "分项工程名称",
}


def sheet(code: str) -> list[dict]:
    """业务端可填的全部栏:版面坐标里的表头栏(fld_*)+ 其余空格子(g*);
    [{field, name, rect, behavior, kind: layout|grid}]"""
    _, header, _ = layout_of(code)
    all_cells = cells(code)
    out = []
    for f in header:
        x, y, w, h = f["rect"]
        rect = {"x": x, "y": y, "w": w, "h": h}
        near = [c for c in all_cells if _overlap(rect, c["rect"]) > 0.3]
        name = (
            f.get("label")
            or (_label(near[0], all_cells) if near else "")
            or FIELD_NAME.get(f["field"], f["field"])
        )
        out.append(
            {
                "field": f["field"],
                "name": name,
                "rect": rect,
                "behavior": f.get("behavior", "INPUT"),
                "kind": "layout",
            }
        )
    taken = [o["rect"] for o in out]
    for c in all_cells:
        if c["text"] or any(
            _overlap(c["rect"], t) > 0.3 or _overlap(t, c["rect"]) > 0.3 for t in taken
        ):
            continue
        out.append(
            {
                "field": c["key"],
                "name": _label(c, all_cells),
                "rect": c["rect"],
                "behavior": "INPUT",
                "kind": "grid",
            }
        )
    return out


def grid_rects(code: str) -> dict:
    """格子键 → 坐标(填 PDF / Excel 用)"""
    return {c["key"]: c["rect"] for c in cells(code)}


# ───────── Excel:按 PDF 上的位置换算到表样 Excel 的单元格 ─────────


def _edges(ws):
    """Excel 列 / 行的累计边界(列宽按字符、行高按磅,只用来比例换算)"""
    dw = ws.sheet_format.defaultColWidth or 8.43
    dh = ws.sheet_format.defaultRowHeight or 15
    cols, x = [0.0], 0.0
    for i in range(1, ws.max_column + 1):
        d = ws.column_dimensions.get(get_column_letter(i))
        x += (d.width if d is not None and d.width else dw) * (
            0 if d is not None and d.hidden else 1
        )
        cols.append(x)
    rows, y = [0.0], 0.0
    for i in range(1, ws.max_row + 1):
        d = ws.row_dimensions.get(i)
        y += (d.height if d is not None and d.height else dh) * (
            0 if d is not None and d.hidden else 1
        )
        rows.append(y)
    return cols, rows


def _bordered(ws):
    """有框线的单元格范围(表格主体)"""
    r0 = c0 = 10**6
    r1 = c1 = 0
    for row in ws.iter_rows():
        for c in row:
            b = c.border
            if b.left.style or b.right.style or b.top.style or b.bottom.style:
                r0, r1, c0, c1 = (
                    min(r0, c.row),
                    max(r1, c.row),
                    min(c0, c.column),
                    max(c1, c.column),
                )
    return (r0, c0, r1, c1) if r1 else None


def _find(edges: list[float], v: float) -> int:
    for i in range(1, len(edges)):
        if v < edges[i]:
            return i
    return len(edges) - 1


def _norm(s) -> str:
    return re.sub(r"[\s□☐_＿:：()（）]", "", str(s or ""))[:6]


def _knots(
    pairs: list[tuple[float, float]], lo: tuple[float, float], hi: tuple[float, float]
) -> list[tuple[float, float]]:
    """对齐点(PDF 比例, Excel 累计尺寸)按 PDF 排序,去掉与前后不单调的(同名栏目对错了),两端加表格外框"""
    out = [lo]
    for p, e in sorted(set(pairs)):
        if out[-1][0] < p < hi[0] and out[-1][1] < e < hi[1]:
            out.append((p, e))
    out.append(hi)
    return out


def _interp(knots: list[tuple[float, float]], v: float) -> float:
    for (p0, e0), (p1, e1) in zip(knots, knots[1:], strict=False):
        if v <= p1:
            return e0 + (v - p0) / max(p1 - p0, 1e-9) * (e1 - e0)
    return knots[-1][1]


@dataclass(frozen=True)
class ExcelOutput:
    path: str = ""
    skipped: tuple[str, ...] = ()


def fill_xlsx(code: str, values: list[dict], excel_anchors: dict, out: Path) -> ExcelOutput:
    """values = [{field, rect, value}](与填 PDF 同一份);excel_anchors = 配置平台 EXCEL_RANGE 锚点 {字段: 单元格};
    返回写好的 Excel 路径及本次跳过的字段，表样没有 Excel 时路径为空。
    没配单元格的栏按 PDF 上的位置换算:PDF 与 Excel 的行高 / 列宽不成比例,只按外框整体换算会错行,
    所以先用两边都印着的栏目名(施工单位、△压实度……)对齐成分段的换算点,再在相邻两个对齐点之间按比例换算。
    同一单元格不写两个值、印好的栏目名不覆盖:放不下的栏返回 skipped,PDF 上照样有。"""
    f = forms().get(code) or {}
    rel = (f.get("excel") or {}).get("path")
    if not rel or not asset(rel).exists():
        return ExcelOutput()
    wb = openpyxl.load_workbook(asset(rel))
    ws = wb.active
    box = _bordered(ws)
    tbl = cells(code)
    if not box or not tbl:
        wb.close()
        return ExcelOutput()
    cols, rows = _edges(ws)
    r0, c0, r1, c1 = box
    px0 = min(c["rect"]["x"] for c in tbl)
    py0 = min(c["rect"]["y"] for c in tbl)
    px1 = max(c["rect"]["x"] + c["rect"]["w"] for c in tbl)
    py1 = max(c["rect"]["y"] + c["rect"]["h"] for c in tbl)
    ex0, ex1, ey0, ey1 = cols[c0 - 1], cols[c1], rows[r0 - 1], rows[r1]
    merged = list(ws.merged_cells.ranges)

    def span(cell):
        for m in merged:
            if cell.coordinate in m:
                return m.min_row, m.min_col, m.max_row, m.max_col
        return cell.row, cell.column, cell.row, cell.column

    def top_left(cell):
        r, c, _, _ = span(cell)
        return ws.cell(r, c)

    # 两边都印着、且各只出现一次的栏目名 → 对齐点(行取上沿,列取左沿)
    pdf_lab, xls_lab = {}, {}
    for c in tbl:
        k = _norm(c["text"])
        if len(k) >= 2:
            pdf_lab.setdefault(k, []).append(c["rect"])
    for row in ws.iter_rows(min_row=r0, max_row=r1, min_col=c0, max_col=c1):
        for x in row:
            k = _norm(x.value)
            if len(k) >= 2:
                xls_lab.setdefault(k, []).append(span(x))
    ys, xs = [], []
    for k, rs in pdf_lab.items():
        if len(rs) == 1 and len(xls_lab.get(k, [])) == 1:
            ra, (sr, sc, _, _) = rs[0], xls_lab[k][0]
            ys.append((ra["y"], rows[sr - 1]))
            xs.append((ra["x"], cols[sc - 1]))
    ky = _knots(ys, (py0, ey0), (py1, ey1))
    kx = _knots(xs, (px0, ex0), (px1, ex1))

    written, skipped = {}, []
    for v in values:
        if not v.get("value"):
            continue
        if v["field"] in excel_anchors:
            cell = top_left(ws[excel_anchors[v["field"]]])
        else:
            r = v["rect"]
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            if not (px0 <= cx <= px1 and py0 <= cy <= py1):
                continue  # 表外(如表名上方的项目名称):Excel 表样里一般是表头行,按表外不写
            cell = top_left(ws.cell(_find(rows, _interp(ky, cy)), _find(cols, _interp(kx, cx))))
        if cell.coordinate in written and v["field"] not in excel_anchors:
            skipped.append(
                v["field"]
            )  # 两个栏换算到同一单元格(Excel 表样少了 PDF 上的这几格):保留先写的,不覆盖
            continue
        # 空格子或「年 月 日」占位直接写;印着字的格子只填它留的空,印好的字不覆盖(配置平台指定的单元格也一样)
        old = "" if cell.value is None else str(cell.value)
        gap = re.match(
            r"^(\s*[^\s:：]{2,8}\s*[:：])(\s{2,})", old
        )  # 「  监理单位：        编 号:…」:冒号后留的空
        if not old.strip() or re.fullmatch(r"[\s年月日:：]*", old):
            cell.value = v["value"]
        elif gap:
            cell.value = gap.group(1) + v["value"] + "  " + old[gap.end() :].lstrip()
        elif re.match(r"^\s{4,}\S", old):  # 「          钢筋安装」:前面留空是给填工程部位的
            cell.value = v["value"] + old.strip()
        elif v["field"] in excel_anchors:
            cell.value = v["value"]  # 配置平台明确指定、格子里也没留空:按配置写
        else:
            skipped.append(v["field"])
            continue
        written[cell.coordinate] = v["field"]
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    wb.close()
    return ExcelOutput(str(out), tuple(skipped))


def excel_anchors(cfg: dict, code: str) -> dict:
    return {
        a["field"]: a["range"]
        for a in cfg.get("anchors", [])
        if a.get("doc") == code and a.get("kind") == "EXCEL_RANGE" and a.get("range")
    }


if __name__ == "__main__":  # 自检:python -m app.ocr.grid JB12-8.3.1-1
    import sys

    for c in sys.argv[1:]:
        s = sheet(c)
        print(c, len(s), json.dumps(s[:6], ensure_ascii=False))
