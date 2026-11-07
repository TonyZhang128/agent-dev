"""同步识别编排：读图、模板对齐、单次 OCR 和字段归属，不调用语言模型。"""

from pathlib import Path

from app.ocr.journal.alignment import align_canvas
from app.ocr.journal.field_matching import extract_fields
from app.ocr.journal.models import JournalRecognition
from app.ocr.journal.ocr_adapter import detect_text_boxes
from app.ocr.journal.photo import load_photo
from app.ocr.journal.template import load_template


def recognize_journal(path: Path | None, img: str = "", task_id: str = "") -> JournalRecognition:
    """识别完整照片；保留来源覆盖和原文片段，img 优先，结果由请求独占。"""
    photo = load_photo(path, img)
    alignment = align_canvas(photo)
    template = load_template()
    readings = extract_fields(
        alignment.canvas,
        template.field_layouts(),
        alignment.table_rect_on_canvas,
        detect_text_boxes,
        valid_mask=alignment.source_coverage_mask,
    )
    return JournalRecognition(photo, alignment, tuple(readings), task_id)
