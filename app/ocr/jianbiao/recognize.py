"""现场简表识别(布局 + 编排):
  · 格子配置在 layouts/jianbiao.json(配置平台生成,外框内比例坐标)
  · 识别链(找纸/表外框 → 透视校正 → 逐格 OCR)在 core/sheet_scan,与监理日志共用
  · 识别结果交给 fill.compute 按配置平台公式 / 引用填目标表(见 fill.py)
简表上手写的值优先于项目资料带入的;结果是草稿,由业务端 / App 人工核对后确认。"""

from pathlib import Path

import cv2
import numpy as np

from app.ocr.core.media import read_image
from app.ocr.core.resources import get_resources, resource_cache
from app.ocr.core.sheet_scan import W, scan
from app.ocr.jianbiao.fill import compute


@resource_cache(maxsize=1)
def layouts() -> dict:
    return get_resources().load("layouts/jianbiao.json")["forms"]


def jianbiao_of(target: str) -> tuple[str, dict] | tuple[None, None]:
    """目标表号 → (简表号, 简表版面);没有对应简表返回 (None, None)"""
    for code, f in layouts().items():
        if f["target"] == target or code == target:
            return code, f
    return None, None


def _frame_dst(aspect: float) -> tuple:
    """简表校正目标:宽 W、高 W×aspect 的矩形四角与输出尺寸(格子坐标是框内比例)"""
    H = round(W * aspect)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
    return dst, (W, H)


def run(photo: Path, target: str, cfg: dict, bound: dict, out_pdf: Path | None) -> dict:
    """现场简表照片:轮廓定位 → 格子识别 → compute(简表上手写的优先于项目资料带入的)"""
    code, lay = jianbiao_of(target)
    if not lay:
        raise ValueError(f"模板库没有 {target} 的简表版面(layouts/jianbiao.json)")
    img = read_image(photo)
    sheet, quad, how, got, detail = scan(
        img, lay["cells"], lambda _q, _h: _frame_dst(lay["aspect"])
    )
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
