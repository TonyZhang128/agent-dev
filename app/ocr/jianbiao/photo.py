"""简表照片解码：路径/base64、EXIF 方向和尺寸上限。"""

import base64
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

INPUT_MAX_SIDE = 6000


def load_photo(path: Path | None, img: str = "") -> np.ndarray:
    """读取 BGR 照片；同时提供路径和 base64 时优先 base64。"""
    payload = _source_bytes(path, img)
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            oriented = ImageOps.exif_transpose(opened)
            rgb = _flatten(oriented).convert("RGB")
            pixels = np.asarray(rgb)
    except Exception as exc:  # noqa: BLE001 —— 解码边界统一映射为受控输入错误
        raise ValueError("不是可识别的简表图片") from exc
    image = cv2.cvtColor(pixels, cv2.COLOR_RGB2BGR)
    longest = max(image.shape[:2])
    if longest > INPUT_MAX_SIDE:
        ratio = INPUT_MAX_SIDE / longest
        image = cv2.resize(
            image,
            (max(1, round(image.shape[1] * ratio)), max(1, round(image.shape[0] * ratio))),
            interpolation=cv2.INTER_AREA,
        )
    return image


def _source_bytes(path: Path | None, img: str) -> bytes:
    if img:
        payload = img.split(",", 1)[1] if img.startswith("data:") and "," in img else img
        try:
            return base64.b64decode(payload)
        except Exception as exc:  # noqa: BLE001 —— base64 边界统一映射
            raise ValueError("简表图片 base64 内容无效") from exc
    if path is None:
        raise ValueError("path 与 img 至少提供一个")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"不是可识别的简表图片:{path.name}") from exc


def _flatten(image: Image.Image) -> Image.Image:
    """透明图片铺白，避免透明区域转 RGB 后变黑。"""
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.split()[-1])
        return canvas
    return image
