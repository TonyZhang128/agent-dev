"""照片读入：path/base64、EXIF 方向、透明背景和尺寸上限。

Pillow 负责解码和 EXIF；OpenCV 负责后续几何与识别。OpenCV 4.14 的
imdecode 实测不应用 EXIF orientation，所以这里不直接用它读图。
"""

import base64
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from app.ocr.journal.spec import INPUT_MAX_SIDE
from app.ocr.journal.types import Photo


def load_photo(path: Path | None, img: str = "") -> Photo:
    """读取照片；img 与 path 同时提供时优先 img。"""
    data = _source_bytes(path, img)
    try:
        with Image.open(io.BytesIO(data)) as opened:
            oriented = ImageOps.exif_transpose(opened)
            rgb = _flatten(oriented).convert("RGB")
            pixels = np.asarray(rgb)
    except Exception as exc:  # noqa: BLE001 —— 解码库异常统一为图片不可识别
        raise ValueError("不是可识别的图片") from exc
    if pixels.ndim != 3 or pixels.shape[2] != 3 or pixels.size == 0:
        raise ValueError("不是可识别的图片")
    bgr = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)

    height, width = bgr.shape[:2]
    scale = 1.0
    longest = max(width, height)
    if longest > INPUT_MAX_SIDE:
        scale = INPUT_MAX_SIDE / longest
        bgr = cv2.resize(
            bgr,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return Photo(bgr=bgr, gray=gray, width=width, height=height, scale=scale)


def _source_bytes(path: Path | None, img: str) -> bytes:
    if img:
        payload = img.split(",", 1)[1] if img.startswith("data:") and "," in img else img
        try:
            return base64.b64decode(payload)
        except Exception as exc:  # noqa: BLE001 —— binascii 等异常统一为无效输入
            raise ValueError("图片 base64 内容无效") from exc
    if path is None:
        raise ValueError("path 与 img 至少提供一个")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"不是可识别的图片:{path.name}") from exc


def _flatten(image: Image.Image) -> Image.Image:
    """带透明通道的图片铺到白底，避免转 RGB 后透明区变黑。"""
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image
