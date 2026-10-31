"""施工图文字层 → JSON(识别引擎 admin/libs/recog.js 的输入格式):
uv run --locked python -m scripts.ocr.pdf_items <单页 PDF 目录前缀> <页数> <out.json>
每页 { no, w, h, engine:'text', items:[{ s, x, y, w, h }] },坐标为 PDF 点、左下原点(与 v5 pdf.js 版一致)。
供 tools/test_recog.js 离线测试识别规则(PDF 文字层统一由 PyMuPDF 抽取,Node 不再装 PDF 包)。
用 get_texttrace(内容流里实际画的每个字形):施工图常把相邻同字形画得部分重叠(如「cos22.4」两个 2 相距 0.7pt),
get_text 会把重叠字形当成重复去掉,得到「cos2.4」;texttrace 与 pdf.js 一样保留。"""

import json
import sys
from pathlib import Path

import pymupdf


def items(prefix: str, pages: int):
    out = []
    for n in range(1, pages + 1):
        f = Path(f"{prefix}{n}.pdf")
        if not f.exists():
            continue
        with pymupdf.open(f) as doc:
            pg = doc[0]
            H = pg.rect.height
            its = []
            for sp in pg.get_texttrace():
                s = "".join(chr(c[0]) for c in sp["chars"])
                if not s.strip():
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                its.append(
                    {
                        "s": s,
                        "x": sp["chars"][0][2][0],
                        "y": H - sp["chars"][0][2][1],
                        "w": x1 - x0,
                        "h": y1 - y0,
                    }
                )  # chars[i][2] = 字形原点(基线)
            out.append({"no": n, "w": pg.rect.width, "h": H, "engine": "text", "items": its})
    return out


if __name__ == "__main__":
    prefix, pages, dst = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    Path(dst).write_text(json.dumps(items(prefix, pages), ensure_ascii=False), encoding="utf-8")
    print("ok", dst)
