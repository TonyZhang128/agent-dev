"""以真实照片的线段和独立人工四角约束几何；真实整图验收另行执行。"""

import json
from pathlib import Path

import numpy as np
import pytest


def scene_cases():
    fixture = Path(__file__).parent / "fixtures/journal_table_geometry.json"
    return json.loads(fixture.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", scene_cases(), ids=lambda case: case["name"])
def test_real_scene_segments_select_the_table_not_paper(case):
    from app.ocr.journal.table_detection import match_table_segments
    from app.ocr.journal.template import load_template

    match = match_table_segments(
        np.asarray(case["segments"], dtype=np.float32),
        image_size=tuple(case["size"]),
        template=load_template(),
    )
    # 手工标注本身有少量误差；此处最大12px远小于旧框的百像素误差。
    assert match.corners == pytest.approx(np.asarray(case["expected_corners"]), abs=12)


def test_field_rect_is_relative_to_actual_table_placement():
    from app.ocr.journal.field_matching import field_bounds_on_canvas
    from app.ocr.journal.models import FieldLayout

    layout = FieldLayout(key="plan", label="计划", rect_in_table=(0.2, 0.8, 0.8, 0.2))
    assert field_bounds_on_canvas(layout, (1000, 1400), (0.25, 0.25, 0.75, 0.75)) == pytest.approx(
        (350, 910, 750, 1050)
    )
    assert field_bounds_on_canvas(layout, (1000, 1400), (0.1, 0.1, 0.9, 0.9)) == pytest.approx(
        (260, 1036, 900, 1260)
    )


def test_table_detection_is_invariant_to_extra_photo_background():
    from app.ocr.journal.table_detection import match_table_segments
    from app.ocr.journal.template import load_template

    case = next(case for case in scene_cases() if case["name"] == "ag-0.png")
    segments = np.asarray(case["segments"], np.float32) + 1400
    match = match_table_segments(segments, image_size=(3886, 4248), template=load_template())
    assert match.corners == pytest.approx(np.asarray(case["expected_corners"]) + 1400, abs=12)


@pytest.mark.parametrize("uniform_columns", [False, True])
def test_paper_border_or_wrong_merged_cells_are_not_target_table(uniform_columns):
    import cv2

    from app.errors import JournalFrameNotFound
    from app.ocr.journal.table_detection import detect_table
    from app.ocr.journal.template import load_template

    picture = np.full((1000, 800), 255, np.uint8)
    cv2.rectangle(picture, (30, 30), (770, 970), 0, 2)
    if uniform_columns:
        # 正确行比例，但所有竖线贯穿，违反内容合并格，不能只凭有横竖线通过。
        for fraction in (0, 0.0875, 0.167, 0.259, 0.6, 0.824, 1):
            y = round(120 + fraction * 800)
            cv2.line(picture, (50, y), (750, y), 0, 2)
        for fraction in (0, 0.173, 0.598, 0.802, 1):
            x = round(50 + fraction * 700)
            cv2.line(picture, (x, 120), (x, 920), 0, 2)
    with pytest.raises(JournalFrameNotFound):
        detect_table(picture, load_template())


@pytest.mark.parametrize("extra_span", [(0, 0.0875), (0.6, 0.824), (0.824, 1)])
def test_each_merged_value_cell_rejects_unexpected_vertical_separator(extra_span):
    import cv2

    from app.errors import JournalFrameNotFound
    from app.ocr.journal.table_detection import detect_table
    from app.ocr.journal.template import load_template

    picture = np.full((1000, 800), 255, np.uint8)
    for fraction in (0, 0.0875, 0.167, 0.259, 0.6, 0.824, 1):
        y = round(120 + fraction * 800)
        cv2.line(picture, (50, y), (750, y), 0, 2)
    for fraction in (0, 0.173, 1):
        x = round(50 + fraction * 700)
        cv2.line(picture, (x, 120), (x, 920), 0, 2)
    for fraction in (0.598, 0.802):
        x = round(50 + fraction * 700)
        cv2.line(picture, (x, 190), (x, 327), 0, 2)
        cv2.line(
            picture,
            (x, round(120 + extra_span[0] * 800)),
            (x, round(120 + extra_span[1] * 800)),
            0,
            2,
        )
    with pytest.raises(JournalFrameNotFound):
        detect_table(picture, load_template())


def test_no_table_returns_approved_400_without_ocr(tmp_path):
    import base64

    import cv2
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.ocr_helpers import make_ocr_settings

    calls = []

    def unexpected_engine(picture):
        calls.append(picture)
        raise AssertionError("无table不得进入OCR")

    blank = np.full((700, 500, 3), 255, np.uint8)
    encoded = base64.b64encode(cv2.imencode(".png", blank)[1]).decode("ascii")
    with TestClient(create_app(settings=make_ocr_settings(tmp_path))) as client:
        client.app.state.ocr_resources.engine = unexpected_engine
        response = client.post("/ocr/daily-logs-new", json={"img": encoded})
    assert response.status_code == 400
    assert response.json() == {"detail": "未检测到监理日志表格，请重新拍摄"}
    assert not calls
