"""简表识别编排：模板核验、单次 OCR 和字段归属。"""

from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.ocr.jianbiao.alignment import align_canvas
from app.ocr.jianbiao.field_matching import extract_fields
from app.ocr.jianbiao.models import JianbiaoRecognition, OcrTextBox
from app.ocr.jianbiao.ocr_adapter import detect_text_boxes
from app.ocr.jianbiao.photo import load_photo
from app.ocr.jianbiao.template import load_template

Reader = Callable[[np.ndarray], list[OcrTextBox]]


def recognize_jianbiao(
    photo: np.ndarray | Path | None,
    template_id: str,
    *,
    img: str = "",
    task_id: str = "",
    reader: Reader = detect_text_boxes,
) -> JianbiaoRecognition:
    """识别一张已绑定模板的简表照片，保留原值供业务输出和诊断使用。"""
    if img:
        image = load_photo(photo if isinstance(photo, Path) else None, img)
    elif isinstance(photo, np.ndarray):
        image = photo
    elif photo is None or isinstance(photo, Path):
        image = load_photo(photo)
    else:
        raise ValueError("不是可识别的简表图片")
    if image.ndim != 3 or image.shape[2] != 3 or image.size == 0:
        raise ValueError("不是可识别的简表图片")
    template = load_template(template_id)
    alignment = align_canvas(image, template)
    boxes = reader(alignment.canvas)
    readings = extract_fields(alignment.canvas, template, alignment.table_rect_on_canvas, boxes)
    values = {reading.key: reading.value for reading in readings if reading.value}
    return JianbiaoRecognition(
        source_template_id=template.template_id,
        values=values,
        readings=tuple(readings),
        alignment=alignment,
        task_id=task_id,
    )
