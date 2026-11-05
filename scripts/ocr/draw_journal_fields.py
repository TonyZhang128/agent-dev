"""把 FIELD_SPECS 画到校正页和原照片上，便于人工核对栏目坐标。

不调用 OCR 模型，只复用读图和表格定位：
    uv run --locked python -m scripts.ocr.draw_journal_fields app/ocr/resources/jl1.jpg
    uv run --locked python -m scripts.ocr.draw_journal_fields ./photos/a.jpg --photo-output /tmp/a-fields.png

输出默认写到 Git 忽略的 verification/ocr/，红色线框为检测到的表格外框。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from app.ocr.journal import frame, image, spec
from app.ocr.journal.types import PageLocation, Photo


def _color(index: int) -> tuple[int, int, int]:
    hue = int(180 * index / max(len(spec.FIELD_SPECS), 1))
    pixel = np.uint8([[[hue, 220, 255]]])
    blue, green, red = cv2.cvtColor(pixel, cv2.COLOR_HSV2BGR)[0, 0]
    return int(blue), int(green), int(red)


def _label(canvas: np.ndarray, text: str, x: int, y: int, color: tuple[int, int, int]) -> None:
    """在矩形左上角画带底色的英文栏目键；OpenCV 不渲染中文，字段键本身就是英文。"""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thickness = 1
    (width, height), baseline = cv2.getTextSize(text, font, scale, thickness)
    x = max(0, min(x, canvas.shape[1] - width - 6))
    y = max(height + 4, min(y, canvas.shape[0] - baseline - 2))
    cv2.rectangle(canvas, (x, y - height - 4), (x + width + 4, y + baseline), color, -1)
    cv2.putText(
        canvas,
        text,
        (x + 2, y - 2),
        font,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def draw_page(location: PageLocation) -> np.ndarray:
    """在校正后的整页图上画各栏目 rect。"""
    canvas = location.sheet.copy()
    for index, field in enumerate(spec.FIELD_SPECS):
        x, y, width, height = field.rect
        x0, y0 = round(x * location.width), round(y * location.height)
        x1, y1 = round((x + width) * location.width), round((y + height) * location.height)
        color = _color(index)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), color, 2)
        _label(canvas, field.key, x0, y0, color)
    cv2.putText(
        canvas,
        f"{location.how}  {location.width}x{location.height}",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return canvas


def draw_photo(photo: Photo, location: PageLocation) -> np.ndarray:
    """把页面坐标经单应逆变换投回原照片；红线为检测到的表格外框。"""
    if location.matrix is None:
        raise ValueError("定位结果缺少单应矩阵，无法投影到原图")
    canvas = photo.bgr.copy()
    inverse = np.linalg.inv(location.matrix)
    for index, field in enumerate(spec.FIELD_SPECS):
        x, y, width, height = field.rect
        page = np.array(
            [
                [x * location.width, y * location.height],
                [(x + width) * location.width, y * location.height],
                [(x + width) * location.width, (y + height) * location.height],
                [x * location.width, (y + height) * location.height],
            ],
            np.float32,
        )
        points = cv2.perspectiveTransform(page.reshape(1, 4, 2), inverse).reshape(4, 2)
        polygon = np.rint(points).astype(np.int32)
        color = _color(index)
        cv2.polylines(canvas, [polygon], True, color, 2)
        _label(
            canvas,
            field.key,
            int(polygon[:, 0].min()),
            int(polygon[:, 1].min()),
            color,
        )
    table = np.rint(location.quad if photo.scale == 1.0 else location.quad * photo.scale).astype(
        np.int32
    )
    cv2.polylines(canvas, [table], True, (0, 0, 255), 3)
    cv2.putText(
        canvas,
        f"{location.how}  red = detected table",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return canvas


def _write(path: Path, picture: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", picture)
    if not ok:
        raise SystemExit(f"图片编码失败：{path}")
    buffer.tofile(str(path))
    print(f"已写入 {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把监理日志 FIELD_SPECS 画到样例图片上。")
    parser.add_argument(
        "photo",
        nargs="?",
        type=Path,
        default=Path("app/ocr/resources/jl1.jpg"),
        help="样例照片；默认 app/ocr/resources/jl1.jpg。",
    )
    parser.add_argument(
        "--page-output",
        type=Path,
        default=Path("verification/ocr/journal-fields-page.png"),
        help="校正页可视化输出路径。",
    )
    parser.add_argument(
        "--photo-output",
        type=Path,
        default=Path("verification/ocr/journal-fields-photo.png"),
        help="原照片投影可视化输出路径。",
    )
    args = parser.parse_args(argv)
    if not args.photo.is_file():
        parser.error(f"照片不存在：{args.photo}")

    source = image.load_photo(args.photo)
    location = frame.locate(source)
    _write(args.page_output, draw_page(location))
    _write(args.photo_output, draw_photo(source, location))
    print(f"frame: {location.how}，画布: {location.width}x{location.height}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
