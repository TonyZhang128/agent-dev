"""模板库生成脚本共用:路径、PDF 文字层(PyMuPDF)、输出 JS / JSON。
v5 用 Node(pdfjs-dist / pdftotext / xlsx)做,v6 统一到 Python(PyMuPDF / openpyxl),不再重复装 PDF / Excel 包。"""

import datetime
import json
import re
from pathlib import Path

import pymupdf

from app.config import ROOT as ROOT
from app.config import Settings
from app.ocr.resources import asset as asset

# CLI 与 API 读取同一份 .env；脚本不再依赖旧部署的目录层级。
_settings = Settings()
ADMIN = _settings.admin_root
TEMPLATES = _settings.templates_root
PROJECTS = _settings.projects_root
ASSET = _settings.asset_root
POOL = PROJECTS.parent


def clean(s) -> str:
    return re.sub(r"\s+", " ", "" if s is None else str(s)).strip()


def today() -> str:
    return datetime.date.today().isoformat()


def spans(pg):
    """页内实际画出的文字段 [(文字, x0, 基线 y, x1)]。
    用 get_texttrace(内容流里每次画字):相邻同字形部分重叠时(施工图常见,如「cos22.4」两个 2 相距 0.7pt)
    get_text 会当成重复去掉,texttrace 与 pdf.js 一样保留。"""
    out = []
    for sp in pg.get_texttrace():
        s = "".join(chr(c[0]) for c in sp["chars"])
        if s.strip():
            out.append(
                (s, sp["chars"][0][2][0], sp["chars"][0][2][1], sp["bbox"][2])
            )  # chars[i][2] = 字形原点(基线),与 pdf.js 的 transform 一致
    return out


def page_items(pdf: Path, page: int = 0):
    """单页文字项:[{s, x, y, w}],坐标为页面百分比、左上原点(与 v5 pdf.js 版一致:y 取基线)"""
    with pymupdf.open(pdf) as doc:
        pg = doc[page]
        W, H = pg.rect.width, pg.rect.height
        return [{"s": s, "x": x0 / W, "y": y / H, "w": (x1 - x0) / W} for s, x0, y, x1 in spans(pg)]


def page_lines(pdf: Path) -> str:
    """整份 PDF 按行拼接的文字(行内按 x 排序)"""
    with pymupdf.open(pdf) as doc:
        res = []
        for pg in doc:
            lines = {}
            for s, x0, y, _ in spans(pg):
                lines.setdefault(round(y), []).append((x0, s))
            res.append(
                "\n".join("".join(t for _, t in sorted(v)) for _, v in sorted(lines.items()))
            )
        return "\n".join(res)


def layout_text(pdf: Path) -> list[str]:
    """逐页的版式文字(替代 pdftotext -layout):页内按行、行内按 x"""
    with pymupdf.open(pdf) as doc:
        out = []
        for pg in doc:
            words = pg.get_text("words")
            rows = {}
            for x0, _y0, _x1, y1, w, *_ in words:
                rows.setdefault(round(y1 / 3), []).append((x0, w))
            out.append(
                "\n".join(" ".join(w for _, w in sorted(v)) for _, v in sorted(rows.items()))
            )
        return out


def write_js(path: Path, header: str, var: str, data) -> None:
    """管理端 / 配置平台以 <script> 离线加载的模板数据(window.XXX = …)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"/* {header} */\nwindow.{var} = {json.dumps(data, ensure_ascii=False, separators=(',', ':'))};\n",
        encoding="utf-8",
    )


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
