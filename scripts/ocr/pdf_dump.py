"""抽取 PDF 全文(按页、按行)→ 文本:uv run --locked python -m scripts.ocr.pdf_dump <pdf> <out.txt>
输出格式「=== 第 N 页」分隔,供第一册签字栏(tools/build_book1_signs.js)、表间引用(tools/build_doc_refs.js)、
表号索引(scripts/build_files.py)读取。(由 v5 tools/pdf_dump.js 移植)"""

import re
import sys
from pathlib import Path

import pymupdf


def dump(pdf: Path) -> str:
    out = []
    with pymupdf.open(pdf) as doc:
        for i, pg in enumerate(doc, 1):
            lines = {}
            for b in pg.get_text("rawdict")["blocks"]:
                for ln in b.get("lines", []):
                    for sp in ln["spans"]:
                        s = "".join(c["c"] for c in sp["chars"])
                        if s.strip():
                            lines.setdefault(round(sp["origin"][1] / 3) * 3, []).append(
                                (sp["bbox"][0], s)
                            )
            text = [
                re.sub(r"\s+", " ", " ".join(t for _, t in sorted(v))).strip()
                for _, v in sorted(lines.items())
            ]
            out.append(f"=== 第 {i} 页\n" + "\n".join(text))
    return "\n".join(out)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    Path(dst).write_text(dump(Path(src)), encoding="utf-8")
    print("ok", dst)
