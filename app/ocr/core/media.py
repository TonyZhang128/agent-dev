"""图像与 PDF 文档原语：读图、文字层、按表号开 PDF、日期规整（无业务，各识别链共用）。"""

import base64
import re
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from app.ocr.core.resources import asset, forms


def strip_data_url_prefix(data: str) -> str:
    """去掉 data:image/...;base64, 之类的前缀，保留纯编码内容。"""
    if data.startswith("data:") and "," in data:
        return data.split(",", 1)[1]
    return data


def read_image(path: Path) -> np.ndarray:
    img = cv2.imdecode(
        np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR
    )  # 中文路径不能用 cv2.imread
    if img is None:
        raise ValueError(f"不是可识别的图片:{path.name}")
    return img


def decode_base64_image(data: str) -> np.ndarray:
    """base64 图片 -> BGR 图像；兼容 data:image/jpeg;base64,... 前缀。"""
    buffer = np.frombuffer(base64.b64decode(strip_data_url_prefix(data)), dtype=np.uint8)
    img = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("不是可识别的图片:base64 内容无效")
    return img


def load_image(path: Path | None, img: str = "") -> np.ndarray:
    """照片路径与 base64 图片至少提供一个；同时提供时优先用 base64。"""
    if img:
        return decode_base64_image(img)
    if path is None:
        raise ValueError("path 与 img 至少提供一个")
    return read_image(path)


def visible_chars(pg: pymupdf.Page) -> Generator[tuple, None, None]:
    """页面上看得见的字(texttrace type 0 填充 / 1 描边),按内容流顺序逐个 yield 字元组。

    type 3 是扫描件叠的隐藏文字层，有错字、重复，拼进栏目名会出错，一律跳过。"""
    for sp in pg.get_texttrace():
        if sp["type"] == 3:
            continue
        yield from sp["chars"]


@contextmanager
def open_form_pdf(code: str) -> Generator[pymupdf.Document | None, None, None]:
    """按表号打开表样 PDF(管理端优先,兼容旧目录名);模板库没有该表或文件缺失时 yield None。"""
    f = forms().get(code) or {}
    path = asset(f["pdf"][0]) if f.get("pdf") else None
    if path is None or not path.exists():
        yield None
        return
    with pymupdf.open(path) as doc:
        yield doc


def date_value(s: str) -> str:
    """日期栏:「2024 年 3 月 21 日」「2024.3.21」「2024 3 21」「20240321」→ 2024-03-21;认不全的原样返回"""
    m = re.search(r"(\d{4})\s*[年.\-/\s]\s*(\d{1,2})\s*[月.\-/\s]\s*(\d{1,2})", s) or re.fullmatch(
        r"\s*(20\d{2})(\d{2})(\d{2})\s*", s
    )
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s
