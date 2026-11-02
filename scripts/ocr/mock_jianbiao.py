"""模拟一张现场简表照片(按 layouts/jianbiao.json 的简表版面,任一张有简表的抽检表都行):
画外框 + 格子 + 印的栏目名,楷体「手写」数值,再加透视倾斜、旋转、光照不均、噪点,当手机拍的照片用。
用法:uv run --locked python -m scripts.ocr.mock_jianbiao <输出.jpg> [目标表号,默认 JB12-4.2.2] [数据 JSON 文件] [随机种子]
数据 JSON = { 字段: 值 };不给时用 DATA(土方路基示例),实测格按项目给一组合理的值。"""

import json
import sys
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

from app.ocr.jianbiao import jianbiao_of

PRINT = "C:/Windows/Fonts/simhei.ttf"  # 印的栏目名
HAND = "C:/Windows/Fonts/simkai.ttf"  # 手写


def font(size: int, path: str = PRINT) -> ImageFont.FreeTypeFont:
    """无 Windows 字体时复用 PyMuPDF 内置中文字体，Mac/Linux 也能造样图。"""
    source = path if Path(path).is_file() else BytesIO(pymupdf.Font("cjk").buffer)
    return ImageFont.truetype(source, size)


# 现场抽检记录(示例):压实度规定值 94%,5 个测点;弯沉设计值 265(0.01mm),5 个测点
DATA = {
    "fld_location": "K23+900~K24+100 路床",
    "fld_sample_date": "2026年10月25日",
    "fld_sampler": "云飞",
    "fld_contract_sec": "S210",
    "fld_ysd_design": "94",
    "fld_ysd_1": "96.8",
    "fld_ysd_2": "95.5",
    "fld_ysd_3": "97.1",
    "fld_ysd_4": "94.6",
    "fld_ysd_5": "95.0",
    "fld_wc_design": "265",
    "fld_wc_1": "210",
    "fld_wc_2": "198",
    "fld_wc_3": "225",
    "fld_wc_4": "240",
    "fld_wc_5": "231",
    "fld_sv_opinion": "同意进入下道工序",
    "fld_reviewer": "秀英",
    "fld_review_date": "2026年10月25日",
}


def draw_sheet(lay: dict) -> Image.Image:
    """标准简表(白纸):外框 1000 宽,上方留表名"""
    W, aspect, M, TOP = 1000, lay["aspect"], 60, 110
    H = round(W * aspect)
    img = Image.new("RGB", (W + 2 * M, H + TOP + M), "white")
    d = ImageDraw.Draw(img)
    fp, fh, ft = font(22), font(40, HAND), font(40)
    fl = font(26)
    d.text((M + W / 2, 52), lay["title"], font=ft, fill="black", anchor="mm")
    d.rectangle([M, TOP, M + W, TOP + H], outline="black", width=5)
    for c in lay["cells"]:
        x, y, w, h = c["rect"]
        X0, Y0, X1, Y1 = M + x * W, TOP + y * H, M + (x + w) * W, TOP + (y + h) * H
        d.rectangle([X0, Y0, X1, Y1], outline="black", width=2)
        if c.get("print"):  # 印好的检查项目名(简表上不填)
            d.text(
                ((X0 + X1) / 2, (Y0 + Y1) / 2), c["label"], font=fl, fill=(30, 30, 30), anchor="mm"
            )
            continue
        d.text((X0 + 8, Y0 + 6), c["label"], font=fp, fill=(40, 40, 40))
        v = DATA.get(c["field"], "")
        if v:
            d.text(
                ((X0 + X1) / 2, Y0 + (Y1 - Y0) * 0.62), v, font=fh, fill=(20, 30, 110), anchor="mm"
            )
    return img


def photograph(sheet: Image.Image, seed: int = 0) -> np.ndarray:
    """把白纸放到桌面上「拍照」:透视 + 旋转 + 光照 + 噪点(seed 不同,每张角度 / 桌面略有不同)"""
    src = cv2.cvtColor(np.array(sheet), cv2.COLOR_RGB2BGR)
    h, w = src.shape[:2]
    PW, PH = 1600, round(1600 * max(0.78, h / w * 1.05))
    rng = np.random.default_rng(seed)
    bg = np.full((PH, PW, 3), (92 + seed % 3 * 8, 104, 118 - seed % 4 * 6), np.uint8)  # 深色桌面
    bg = cv2.add(bg, np.random.default_rng(1).integers(0, 18, bg.shape, dtype=np.uint8))
    s = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    j = rng.integers(-35, 36, (4, 2)) if seed else np.zeros((4, 2), int)
    d = np.array(
        [
            [230, 150 * PH / 1250],
            [1390, 205 * PH / 1250],
            [1345, 1110 * PH / 1250],
            [185, 1040 * PH / 1250],
        ],
        np.float32,
    ) + j.astype(np.float32)  # 透视倾斜 + 轻微旋转
    M = cv2.getPerspectiveTransform(s, d)
    paper = cv2.warpPerspective(src, M, (PW, PH), borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (PW, PH))
    out = np.where(mask[..., None] > 0, paper, bg)
    yy, xx = np.mgrid[0:PH, 0:PW]
    light = 0.78 + 0.27 * (xx / PW) * (1 - 0.4 * yy / PH)  # 一侧偏暗
    out = np.clip(out * light[..., None], 0, 255).astype(np.uint8)
    out = cv2.add(out, np.random.default_rng(2).integers(0, 10, out.shape, dtype=np.uint8))
    return cv2.GaussianBlur(out, (3, 3), 0)


if __name__ == "__main__":
    dst = Path(sys.argv[1])
    target = sys.argv[2] if len(sys.argv) > 2 else "JB12-4.2.2"
    if len(sys.argv) > 3:
        DATA.clear()
        DATA.update(json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")))
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    code, lay = jianbiao_of(target)
    if not lay:
        sys.exit(f"没有 {target} 的简表版面")
    sheet = draw_sheet(lay)
    dst.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dst.with_name(dst.stem + "_flat.png"))
    cv2.imencode(".jpg", photograph(sheet, seed), [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tofile(
        str(dst)
    )
    print(f"简表 {code}({lay['name']})→ {dst}")
