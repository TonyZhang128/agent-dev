"""划分初稿识别:工可(项目依据)+ 施工图设计文件(PDF)→ 单位 / 分部 / 分项 / 子分项划分初稿
规则取模板库 templates/refs/wbs_rules.json(第一册 总则「公路工程单位、分部、分项工程划分规则」):
  · 施工图:读封面 / 总目录 / 分册目录的文字层,找出桥梁(名称、桩号、墩台数、跨数、梁型、是否分幅)、道路路段
  · 桥梁:每座一个单位工程,左右幅体现在分项名称;基础及下部构造按每个墩台一个分部;
          上部构造按每跨一个分部;桥面系附属及总体、防护各一个分部;分项取规则清单,左右幅各一套
  · 路基 / 路面:按施工图路段桩号,每 ≤10 km 一个单位工程,每 ≤3 km 一个分部
  · 工可:取路线起讫桩号、长度,补全没有施工图的路段
输出与业务库 wbsTrees.rawUnits 同结构:[{ code, title, children:[{ code, title, children:[{ code, title, children:[{ title }] }] }] }]
每个节点带 src(识别依据:哪份文件、第几页、原文),供管理员核对后「下发初稿」。

输入支持数据池路径或 base64 编码的 PDF 字节流,便于 Java 后端直接透传文件内容。
"""

import base64
import binascii
import re
from pathlib import Path
from typing import Any

import pymupdf

from app.ocr.core.media import strip_data_url_prefix
from app.ocr.core.resources import OCRResourceError, get_resources


def rules() -> dict[str, Any]:
    return get_resources().load("refs/wbs_rules.json")


def cues() -> dict[str, re.Pattern[str]]:
    return {key: re.compile(value) for key, value in rules()["drawingCues"].items()}


def chainage_m(s: str) -> float | None:
    """K3+895.108 → 3895.108(米);ZK0+214.642 → 214.642"""
    m = re.search(r"K(\d+)\+(\d+(?:\.\d+)?)", s or "")
    return int(m.group(1)) * 1000 + float(m.group(2)) if m else None


def decode_base64_pdf(data: str) -> bytes:
    """base64 PDF → 字节流；兼容 data:application/pdf;base64,... 前缀。

    base64 数据本身无效时抛出 ValueError，由接口层返回明确的 400。
    """
    try:
        return base64.b64decode(strip_data_url_prefix(data))
    except binascii.Error as exc:
        raise ValueError("imgs 项不是有效的 base64 数据") from exc


def open_pdf(source: Path | bytes) -> pymupdf.Document:
    """打开 PDF 文件或已解码的字节流；内容不是有效 PDF 时抛出可读的 ValueError。"""
    try:
        if isinstance(source, bytes):
            return pymupdf.open(stream=source)
        return pymupdf.open(source)
    except (OSError, RuntimeError) as exc:
        if isinstance(source, bytes):
            raise ValueError("imgs 项解码后不是有效的 PDF") from exc
        raise ValueError("施工图文件不是有效的 PDF，请检查文件内容") from exc


def pdf_text(source: Path | bytes, max_pages: int = 8) -> list[tuple[int, str]]:
    """PDF 前几页的文字层(封面、目录):[(页码, 文字)]。

    source 可以是数据池内的 PDF 文件/目录,也可以是已解码的 PDF 字节流。
    单页拆分目录则读前 max_pages 个文件。
    """
    out = []
    if isinstance(source, Path) and source.is_dir():
        files = []
        for f in source.glob("*.pdf"):
            match = re.search(r"_(\d+)\.pdf$", f.name)
            if match and f.is_file():
                if not f.resolve().is_relative_to(get_resources().projects):
                    raise ValueError("施工图目录包含数据池外的 PDF 文件")
                files.append((int(match.group(1)), f))
        for number, f in sorted(files)[:max_pages]:
            with open_pdf(f) as d:
                out.append((number, d[0].get_text()))
    else:
        with open_pdf(source) as d:
            for i, pg in enumerate(d):
                if i >= max_pages:
                    break
                out.append((i + 1, pg.get_text()))
    return out


def lines_of(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def read_drawing(source: Path | bytes) -> dict[str, Any]:
    pages = pdf_text(source, max_pages=12)
    info = {"file": "base64.pdf" if isinstance(source, bytes) else source.name, "src": []}
    cover = lines_of(pages[0][1]) if pages else []
    # 封面册名:「第 n 分册 共 n 分册」的下一行(如「牛鞍溪大桥工程」「岷江二桥 主桥主拱构造」);没有分册行则取含桥 / 隧道 / 工程的行
    i = next((j for j, ln in enumerate(cover) if re.search(r"分\s*册", ln)), -1)
    title = (
        cover[i + 1]
        if 0 <= i < len(cover) - 1
        else next(
            (
                ln
                for ln in cover[1:]
                if re.search(r"桥|隧道|工程$", ln) and not re.search(r"K\d", ln)
            ),
            "base64.pdf" if isinstance(source, bytes) else source.name,
        )
    )
    info["volume"] = re.sub(r"\s+", " ", title)
    info["src"].append(
        {"page": pages[0][0] if pages else None, "text": "封面册名:" + info["volume"]}
    )
    m = cues()["bridgeName"].search(re.sub(r"\s+", "", title)) or re.search(
        r"([^\s]{2,10}?桥)", title
    )
    # 本册目录页:有「图号」列的页;只取这些页的图名
    catflat = "\n".join(ln for _, t in pages if "图号" in t for ln in lines_of(t))
    if m:
        info.update(kind="bridge", name=m.group(1))
        piers = sorted({int(x) for x in re.findall(r"(\d{1,2})#墩", catflat)})
        abuts = sorted({int(x) for x in re.findall(r"(\d{1,2})#(?:桥)?台", catflat)})
        info["piers"], info["abutments"] = piers, abuts
        info["spans"] = len(piers) + 1 if (piers or abuts) else 0
        info["split"] = "左幅" in catflat or "右幅" in catflat
        g = cues()["girder"].search(catflat) or re.search(r"拱", catflat)
        info["girder"] = g.group(0) if g else "梁板"
        info["precast"] = info["girder"] in ("T梁", "空心板", "小箱梁")
        info[
            "partial"
        ] = not abuts  # 本册不含墩台(如只有主拱构造的分册):只出上部 / 附属,下部构造待其他分册
        info["src"].append(
            {
                "page": None,
                "text": f"分册目录:{len(piers)} 墩 {len(abuts)} 台 · {info['girder']}{' · 分幅' if info['split'] else ''}"
                + (" · 本册无墩台图,下部构造需补其他分册" if info["partial"] else ""),
            }
        )
    else:
        tm = cues()["tunnelName"].search(re.sub(r"\s+", "", title))
        info.update(kind="tunnel" if tm else "road", name=tm.group(1) if tm else info["volume"])
    # 桩号:设计说明里的「起点桩号 K… 终点桩号 K…」(扫描件常有错字,终 / 正 / 止、号 / 社号 都认);没有则取封面路段范围
    body = re.sub(r"\s+", "", "".join(t for _, t in pages))
    se = re.search(
        r"起点桩号([A-Z]*K\d+\+[\d.]+).{0,12}?[终正止]点\S{0,2}号([A-Z]*K\d+\+[\d.]+)", body
    )
    if se:
        info["chainage"] = [chainage_m(se.group(1)), chainage_m(se.group(2))]
        info["src"].append(
            {"page": None, "text": f"设计说明:起点 {se.group(1)} 终点 {se.group(2)}"}
        )
    else:
        first = re.findall(r"K(\d+)\+(\d+(?:\.\d+)?)[~～]K(\d+)\+(\d+(?:\.\d+)?)", " ".join(cover))
        info["chainage"] = (
            [
                int(first[0][0]) * 1000 + float(first[0][1]),
                int(first[0][2]) * 1000 + float(first[0][3]),
            ]
            if first
            else None
        )
    return info


def k(m: float | None) -> str:
    """3895.108 → K3+895.108"""
    if m is None:
        return ""
    km, r = divmod(m, 1000)
    return f"K{int(km)}+{r:07.3f}".rstrip("0").rstrip(".")


def bridge_units(b: dict, prefix: str, no: int) -> list[dict]:
    R = rules()["bridge"]
    sides = ["左幅", "右幅"] if b["split"] else [""]
    code = f"{prefix}-QL{no:02d}"
    title = f"{k(b['chainage'][0]) + ' ' if b.get('chainage') else ''}{b['name']}"
    parts, pi = [], 0

    def part(t: str, items: list[str]) -> dict[str, Any]:
        nonlocal pi
        pi += 1
        pc = f"{code}-{pi}"
        return {
            "code": pc,
            "title": t,
            "children": [
                {"code": f"{pc}-{ii + 1:03d}", "title": it, "children": []}
                for ii, it in enumerate(items)
            ],
        }

    # 基础及下部构造:每个墩台一个分部(第一册:1~3 墩台一个分部,按单孔跨径大的宜小)
    for a in sorted(set(b["abutments"]) | set(b["piers"])):
        is_abut = a in b["abutments"]
        base = R["abutment"] if is_abut else R["substructure"]
        items = [f"{s}{a}#{'台' if is_abut else '墩'}{x}" for s in sides for x in base]
        parts.append(part(f"{a}#{'台' if is_abut else '墩'}基础及下部构造", items))
    for s_ in range(1, max(1, b["spans"]) + 1):
        base = R["superPrecast"] if b["precast"] else R["superCast"]
        items = [f"{s}第{s_}跨{b['girder']}{x}" for s in sides for x in base]
        parts.append(part(f"第{s_}跨上部构造{'预制及安装' if b['precast'] else '现场浇筑'}", items))
    parts.append(part("总体、桥面系和附属工程", [f"{s}{x}" for s in sides for x in R["deck"]]))
    if b["abutments"]:
        parts.append(
            part(
                "防护工程",
                [
                    f"{s}{a}#桥台{x}"
                    for s in sides
                    for a in b["abutments"]
                    for x in R["protect"][:1]
                ],
            )
        )
    return [{"code": code, "title": title, "src": b["src"], "children": parts}]


def road_units(rng: tuple[float, float] | None, prefix: str, start_no: int = 1) -> list[dict]:
    """路段 [起, 止](米)→ 路基 / 路面单位工程(≤10 km 一个),分部每 ≤3 km"""
    if not rng:
        return []
    config = rules()
    steps = [config["road"]["partKm"], *(config["units"][kind]["splitKm"] for kind in ("LJ", "LM"))]
    if any(not isinstance(step, (int, float)) or not 0 < step < float("inf") for step in steps):
        raise OCRResourceError("WBS 划分步长必须为有限正数，请检查 refs/wbs_rules.json")
    R, out = rules()["road"], []
    a, b = rng
    for kind, name, groups in (
        (
            "LJ",
            "路基工程",
            [
                ("路基土石方工程", R["earthwork"]),
                ("排水工程", R["drainage"]),
                ("防护支挡工程", R["protection"]),
            ],
        ),
        ("LM", "路面工程", [("路面工程", R["pavement"])]),
    ):
        u0, no = a, start_no
        while u0 < b:
            u1 = min(b, u0 + rules()["units"][kind]["splitKm"] * 1000)
            code = f"{prefix}-{kind}{no:02d}"
            parts, pi, p0 = [], 0, u0
            while p0 < u1:
                p1 = min(u1, p0 + R["partKm"] * 1000)
                for gname, items in groups:
                    pi += 1
                    pc = f"{code}-{pi}"
                    parts.append(
                        {
                            "code": pc,
                            "title": f"{k(p0)}~{k(p1)} {gname}",
                            "children": [
                                {"code": f"{pc}-{ii + 1:03d}", "title": it, "children": []}
                                for ii, it in enumerate(items)
                            ],
                        }
                    )
                p0 = p1
            out.append({"code": code, "title": f"{k(u0)}-{k(u1)}{name}", "children": parts})
            u0, no = u1, no + 1
    return out


def draft(
    prefix: str, drawings: list[Path], imgs: list[str] | None = None, basis: dict | None = None
) -> dict[str, Any]:
    """prefix = 合同段编码前缀(如 S210);drawings = 施工图(PDF 文件或单页拆分目录);
    imgs = base64 编码的 PDF 数据列表;basis = 工可解析出的指标(roads.basis)。
    """
    imgs = imgs or []
    reads = [read_drawing(p) for p in drawings] + [
        read_drawing(decode_base64_pdf(img)) for img in imgs
    ]
    units, qn = [], 0
    for b in [r for r in reads if r["kind"] == "bridge"]:
        qn += 1
        units += bridge_units(b, prefix, qn)
    road = next((r["chainage"] for r in reads if r["kind"] == "road" and r.get("chainage")), None)
    if not road and basis:
        f = dict(basis.get("facts") or [])
        m = re.findall(r"K\d+\+\d+(?:\.\d+)?", f.get("路线起讫", ""))
        road = [chainage_m(m[0]), chainage_m(m[1])] if len(m) == 2 else None
    units += road_units(road, prefix)
    count = {
        "units": len(units),
        "parts": sum(len(u["children"]) for u in units),
        "items": sum(len(p["children"]) for u in units for p in u["children"]),
        "subs": 0,
    }
    return {"units": units, "count": count, "drawings": reads}
