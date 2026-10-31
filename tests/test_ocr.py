"""OCR 提取、公式、PDF/Excel 同源填表与 WBS 的行为回归。"""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import cv2
import numpy as np
import openpyxl
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.ocr import form_ocr, grid, jianbiao, wbs_draft
from app.ocr.resources import OCRResources, forms, use_resources
from tests.ocr_helpers import CODE, fill_config, make_ocr_settings


def ocr_result(*items):
    """RapidOCR 3.x 输出边界：boxes / txts / scores 三个平级字段。"""
    if not items:
        return SimpleNamespace(boxes=None, txts=None, scores=None)
    return SimpleNamespace(
        boxes=np.array([item[0] for item in items], dtype=np.float32),
        txts=tuple(item[1] for item in items),
        scores=tuple(item[2] for item in items),
    )


@pytest.fixture
def settings(tmp_path):
    return make_ocr_settings(tmp_path)


@pytest.fixture
def resources(settings):
    resource = OCRResources(settings)
    with use_resources(resource):
        yield resource


def test_fill_writes_pdf_and_excel_using_same_calculated_values(resources, tmp_path):
    values = {
        "fld_supervisor": "测试监理公司",
        "fld_location": "K1+000",
        "fld_1": "96.1",
        "fld_2": "93.2",
        "fld_rate": "999",
    }
    result = jianbiao.compute(CODE, fill_config(), values, tmp_path / "filled.pdf")
    assert result["values"]["fld_rate"] == "50"
    assert values["fld_rate"] == "999"
    with pymupdf.open(result["pdf"]) as pdf:
        text = pdf[0].get_text()
        assert "96.1" in text and "93.2" in text and "50" in text
    workbook = openpyxl.load_workbook(result["xlsx"])
    worksheet = workbook.active
    assert worksheet["A1"].value == "监理单位：测试监理公司  编 号:TEST"
    assert worksheet["A2"].value == "K1+000土方路基"
    assert worksheet["B3"].value == "96.1"
    assert worksheet["C3"].value == "93.2"
    assert worksheet["B4"].value == "50"
    workbook.close()


def test_calculation_without_output_does_not_write_files(resources):
    result = jianbiao.compute(CODE, fill_config(), {"fld_1": "95", "fld_2": "96"}, None)
    assert result["values"]["fld_rate"] == "100"
    assert result["pdf"] == result["xlsx"] == ""
    assert list(resources.projects.iterdir()) == []


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("ROUND(2.5)", 3),
        ("ROUND(-1.5)", -1),
        ("ROUND(AVG(1, 2, 3), 1)", 2),
        ("PASS_RATE_LE(10, 8, 10, 12)", 66.7),
        ("IF(@{a} >= 2 && @{b} < 5, SUM(@{a}, @{b}), 0)", 5),
        ('IF(!(@{a} > 2), "合格", "不合格")', "合格"),
    ],
)
def test_formula_js_compatible_semantics(expression, expected):
    result, errors = jianbiao.evaluate(
        {"formulas": [{"target": "result", "expr": expression}]}, {"a": "2", "b": "3"}
    )
    assert errors == {}
    assert result["result"] == expected


def test_formula_dependencies_and_partial_failure():
    result, errors = jianbiao.evaluate(
        {
            "formulas": [
                {"target": "later", "expr": "@{first} * 2"},
                {"target": "first", "expr": "SUM(1, 2)"},
                {"target": "invalid", "expr": '__import__("os")'},
            ]
        },
        {},
    )
    assert result == {"first": 3, "later": 6, "invalid": None}
    assert set(errors) == {"invalid"}


def test_formula_cycle_is_reported():
    with pytest.raises(ValueError, match="循环引用"):
        jianbiao.evaluate(
            {"formulas": [{"target": "a", "expr": "@{b}"}, {"target": "b", "expr": "@{a}"}]}, {}
        )


def test_reference_template_takes_precedence_over_copy(resources):
    config = fill_config()
    config["edges"] = [
        {"id": "copy", "type": "COPY", "from": "fld_1", "to": "fld_location"},
        {
            "id": "template",
            "type": "TEMPLATE",
            "to": "fld_location",
            "template": "实测 @{fld_2} / @{missing}",
        },
    ]
    values = {"fld_1": "95", "fld_2": "96"}
    cells = jianbiao.anchor_values(config, CODE, values)
    assert next(cell for cell in cells if cell["field"] == "fld_location")["value"] == "实测 96 / —"


def test_sheet_grid_keys_are_stable_and_printed_cells_are_not_fillable(resources):
    first, second = grid.sheet(CODE), grid.sheet(CODE)
    assert first == second
    assert any(cell["kind"] == "layout" for cell in first)
    assert any(cell["kind"] == "grid" for cell in first)
    assert "g135_102" not in {cell["field"] for cell in first}
    assert len({cell["field"] for cell in first}) == len(first)


@pytest.mark.parametrize(
    "value,want", [("2026年10月3日", "2026-10-03"), ("2026/10/03", "2026-10-03")]
)
def test_ocr_date_normalization(value, want):
    assert form_ocr.date_value(value) == want


def test_ocr_cell_value_removes_printed_label_and_retains_negative_measurement():
    boxes = [
        {"s": "数值", "box": [0, 0, 40, 10], "conf": 0.99},
        {"s": "一2.5", "box": [0, 20, 60, 40], "conf": 0.9},
    ]
    assert jianbiao._cell_value(boxes, "数值", "number") == ("-2.5", 0.9)


def test_ocr_converts_rapidocr_output_to_boxes(resources):
    resources.engine = lambda image: ocr_result(
        ([[10, 10], [300, 10], [300, 40], [10, 40]], "监理单位：测试公司", 0.99),
        ([[20, 50], [80, 50], [80, 70], [20, 70]], "2026-10-31", 0.5),
    )
    boxes = form_ocr.ocr(np.zeros((100, 100, 3), np.uint8))
    assert [b["s"] for b in boxes] == ["监理单位：测试公司", "2026-10-31"]
    assert [b["box"] for b in boxes] == [[10.0, 10.0, 300.0, 40.0], [20.0, 50.0, 80.0, 70.0]]
    assert boxes[0]["conf"] == pytest.approx(0.99)
    assert boxes[1]["conf"] == pytest.approx(0.5)


def test_ocr_empty_detection_returns_no_boxes(resources):
    resources.engine = lambda image: ocr_result()
    assert form_ocr.ocr(np.zeros((10, 10, 3), np.uint8)) == []


def test_engine_uses_ppocrv6_medium_and_ppocrv5_server_direction_model(settings, monkeypatch):
    import rapidocr

    captured = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs["params"])

    monkeypatch.setattr(rapidocr, "RapidOCR", FakeRapidOCR)
    with use_resources(OCRResources(settings)):
        form_ocr.engine()

    assert captured["Global.model_root_dir"] == str(settings.ocr_model_root)
    assert captured["Det.model_type"] is rapidocr.ModelType.MEDIUM
    assert captured["Det.ocr_version"] is rapidocr.OCRVersion.PPOCRV6
    assert captured["Rec.model_type"] is rapidocr.ModelType.MEDIUM
    assert captured["Rec.ocr_version"] is rapidocr.OCRVersion.PPOCRV6
    assert captured["Cls.model_type"] is rapidocr.ModelType.SERVER
    assert captured["Cls.ocr_version"] is rapidocr.OCRVersion.PPOCRV5


def test_ocr_model_initialization_failure_returns_503(settings, monkeypatch):
    import rapidocr

    image = np.full((40, 60, 3), 255, dtype=np.uint8)
    cv2.imencode(".png", image)[1].tofile(str(settings.projects_root / "照片.png"))

    class BrokenEngine:
        def __init__(self, **kwargs):
            pass

        def __call__(self, image):
            # RapidOCR 3.x 在首次推理时才加载模型，下载失败发生在这里。
            raise RuntimeError("model download failed")

    monkeypatch.setattr(rapidocr, "RapidOCR", BrokenEngine)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/ocr/recognize", json={"path": "projects/照片.png"})
    assert response.status_code == 503
    assert "model download failed" not in response.json()["detail"]


def test_recognize_uses_real_image_pipeline_and_mocked_ocr_boundary(settings):
    image = np.full((400, 600, 3), 255, dtype=np.uint8)
    cv2.imencode(".png", image)[1].tofile(str(settings.projects_root / "照片.png"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        app.state.ocr_resources.engine = lambda image: ocr_result(
            ([[10, 10], [300, 10], [300, 40], [10, 40]], "监理单位：测试公司", 0.99)
        )
        result = client.post("/ocr/recognize", json={"path": "projects/照片.png"})
        assert result.status_code == 200
        assert result.json()["data"]["fields"]["fld_supervisor"] == "测试公司"
        assert result.json()["data"]["image"] == {"width": 600, "height": 400}


def test_jianbiao_pipeline_recognizes_and_computes_without_writing(settings):
    image = np.full((1000, 1000, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (50, 50), (950, 950), (0, 0, 0), 5)
    cv2.imencode(".png", image)[1].tofile(str(settings.projects_root / "simple.png"))
    app = create_app(settings=settings)
    with TestClient(app) as client:
        app.state.ocr_resources.engine = lambda image: ocr_result(
            ([[20, 20], [100, 20], [100, 60], [20, 60]], "96.5", 0.99)
        )
        response = client.post(
            "/ocr/jianbiao",
            json={"path": "simple.png", "form": CODE, "cfg": {}, "bound": {"fld_1": "1"}},
        )
        assert response.status_code == 200
        assert response.json()["data"]["recognized"] == {"fld_1": "96.5"}
        assert response.json()["data"]["values"]["fld_1"] == "96.5"
        assert set(path.name for path in settings.projects_root.iterdir()) == {"simple.png"}


def test_ocr_apps_keep_catalogs_caches_and_paths_isolated(tmp_path):
    first = make_ocr_settings(tmp_path / "first", name="first", height=300)
    second = make_ocr_settings(tmp_path / "second", name="second", height=600)
    applications = [create_app(settings=first), create_app(settings=second)]
    with TestClient(applications[0]) as left, TestClient(applications[1]) as right:

        def call(pair):
            client, name = pair
            response = client.post("/ocr/fill", json={"form": CODE, "cfg": {}, "values": {}})
            assert response.status_code == 200
            assert response.json()["data"]["targetName"] == name

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(call, [(left, "first"), (right, "second")] * 4))
        for app, aspect in zip(applications, (0.75, 1.5), strict=True):
            with use_resources(app.state.ocr_resources):
                assert form_ocr.page_aspect(CODE) == aspect
        assert (
            applications[0].state.ocr_resources.lock is not applications[1].state.ocr_resources.lock
        )


def test_blank_sheet_and_relative_output_paths(settings):
    with TestClient(create_app(settings=settings)) as client:
        image = client.get(f"/ocr/blank/{CODE}.png?width=600")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert (
            cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR).shape[1] == 600
        )
        assert client.get(f"/ocr/blank/{CODE}.png?width=0").status_code == 422
        assert client.get("/ocr/sheet/unknown").status_code == 404
        assert client.get(f"/ocr/sheet/{CODE}").json()["data"]
        response = client.post(
            "/ocr/fill",
            json={
                "form": CODE,
                "cfg": fill_config(),
                "values": {"fld_1": "97"},
                "out": "projects/out/result.pdf",
            },
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert result["pdf"] == "out/result.pdf"
        assert result["xlsx"] == "out/result.xlsx"
        assert (settings.projects_root / result["pdf"]).is_file()


@pytest.mark.parametrize(
    "relative", ["../outside.pdf", "/tmp/outside.pdf", "projects/../../outside.pdf"]
)
def test_paths_cannot_escape_data_pool(settings, relative):
    with TestClient(create_app(settings=settings)) as client:
        assert client.post("/ocr/recognize", json={"path": relative}).status_code == 400
        assert (
            client.post(
                "/ocr/fill", json={"form": CODE, "cfg": {}, "values": {}, "out": relative}
            ).status_code
            == 400
        )
        assert (
            client.post("/wbs/draft", json={"prefix": "S210", "drawings": [relative]}).status_code
            == 400
        )


def test_symlinks_cannot_escape_data_pool(settings, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "input.png").write_bytes(b"private")
    (settings.projects_root / "link").symlink_to(outside, target_is_directory=True)
    (settings.projects_root / "result.xlsx").symlink_to(outside / "result.xlsx")
    with TestClient(create_app(settings=settings)) as client:
        assert client.post("/ocr/recognize", json={"path": "link/input.png"}).status_code == 400
        assert (
            client.post(
                "/ocr/fill", json={"form": CODE, "cfg": {}, "values": {}, "out": "result.pdf"}
            ).status_code
            == 400
        )
    assert not (outside / "result.xlsx").exists()


def test_missing_or_invalid_image_and_cycle_return_actionable_errors(settings):
    (settings.projects_root / "invalid.png").write_bytes(b"not an image")
    with TestClient(create_app(settings=settings)) as client:
        assert client.post("/ocr/recognize", json={"path": "missing.png"}).status_code == 400
        assert client.post("/ocr/recognize", json={"path": "invalid.png"}).status_code == 400
        response = client.post(
            "/ocr/fill",
            json={
                "form": CODE,
                "cfg": {"formulas": [{"target": "x", "expr": "@{x}"}]},
                "values": {},
            },
        )
        assert response.status_code == 400
        assert "循环引用" in response.json()["detail"]


def test_wbs_can_build_road_draft_from_basis(settings):
    with TestClient(create_app(settings=settings)) as client:
        response = client.post(
            "/wbs/draft",
            json={
                "prefix": "S210",
                "drawings": [],
                "basis": {"facts": [["路线起讫", "K0+000~K4+000"]]},
            },
        )
        assert response.status_code == 200
        result = response.json()["data"]
        assert result["count"] == {"units": 2, "parts": 8, "items": 8, "subs": 0}
        assert [unit["code"] for unit in result["units"]] == ["S210-LJ01", "S210-LM01"]


def test_wbs_reads_drawing_pdf(resources):
    drawing = resources.projects / "drawing.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "封面\n道路工程\nK1+000~K4+000", fontname="china-s")
        document.save(drawing)
    result = wbs_draft.draft("S210", [drawing])
    assert result["drawings"][0]["chainage"] == [1000, 4000]
    assert result["count"]["units"] == 2


def test_template_asset_priority_and_renamed_directory(resources):
    (resources.admin / "pdf").mkdir(parents=True)
    (resources.admin / "pdf/test.pdf").write_bytes(b"admin wins")
    assert resources.asset("pdf/test.pdf") == resources.admin / "pdf/test.pdf"
    assert resources.asset("excel/test.xlsx") == resources.assets / "excel/test.xlsx"
    target = resources.assets / "pdf/new/test.pdf"
    target.parent.mkdir()
    target.write_bytes(b"renamed")
    library = resources.templates / "library"
    library.mkdir()
    (library / "pdf_dirs.json").write_text(
        json.dumps({"books": {"test": {"old": "old", "dir": "new"}}})
    )
    assert resources.asset("pdf/old/test.pdf") == target
    with pytest.raises(ValueError):
        resources.asset("../../private.pdf")


def test_settings_paths_are_project_relative_and_explicit_environment_wins(monkeypatch):
    from app.config import ROOT

    monkeypatch.setenv("PROJECTS_ROOT", "relative/pool")
    assert Settings(_env_file=None).projects_root == ROOT / "relative/pool"


def test_corrupt_catalog_is_503_without_disclosing_filesystem(settings):
    (settings.templates_root / "forms/files.json").write_text("[]")
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/ocr/sheet/TEST")
        assert response.status_code == 503
        assert str(settings.templates_root) not in response.text
        assert client.get("/health").json() == {"status": "ok"}


def test_catalog_context_restored_after_exception(resources):
    other = OCRResources(Settings(_env_file=None))
    with pytest.raises(RuntimeError), use_resources(other):
        raise RuntimeError("test")
    assert forms()[CODE]["name"] == "测试表"


@pytest.mark.parametrize(
    "config",
    [
        {"formulas": [{}]},
        {"formulas": "invalid"},
        {"anchors": [{"id": "a"}]},
        {"edges": [{"type": "TEMPLATE", "to": "a"}]},
    ],
)
def test_malformed_configuration_is_rejected_before_processing(settings, config):
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/ocr/fill", json={"form": CODE, "cfg": config, "values": {}})
        assert response.status_code == 422


def test_all_migrated_script_modules_can_import_without_external_data():
    import importlib
    import pkgutil

    import scripts.ocr

    for module in pkgutil.iter_modules(scripts.ocr.__path__, scripts.ocr.__name__ + "."):
        importlib.import_module(module.name)


def test_excel_skipped_fields_are_returned_per_call(resources, tmp_path):
    workbook = openpyxl.load_workbook(resources.assets / "excel/test.xlsx")
    workbook.active["C1"] = "不可覆盖"
    workbook.save(resources.assets / "excel/test.xlsx")
    workbook.close()
    cell = {
        "field": "printed",
        "rect": {"x": 0.68, "y": 0.14, "w": 0.1, "h": 0.1},
        "value": "overwrite",
    }
    first = grid.fill_xlsx(CODE, [cell], {}, tmp_path / "first.xlsx")
    second = grid.fill_xlsx(CODE, [], {}, tmp_path / "second.xlsx")
    assert first.skipped == ("printed",)
    assert second.skipped == ()
    assert first.path.endswith("first.xlsx")


def test_zero_length_road_partition_is_reported_as_resource_error(resources):
    from app.ocr.resources import OCRResourceError

    rules = resources.load("refs/wbs_rules.json")
    rules["units"]["LJ"]["splitKm"] = 0
    with pytest.raises(OCRResourceError, match="划分步长"):
        wbs_draft.road_units([0, 1000], "S210")


def test_mock_sheet_works_without_windows_fonts(resources):
    from scripts.ocr.mock_jianbiao import draw_sheet

    layout = jianbiao.layouts()["SIMPLE"]
    image = draw_sheet(layout)
    assert image.width == 1120
    assert np.asarray(image).min() < 100


def test_wbs_does_not_read_symlinked_pdf_outside_pool(settings, tmp_path):
    outside = tmp_path / "secret.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), "private document")
        document.save(outside)
    directory = settings.projects_root / "drawings"
    directory.mkdir()
    (directory / "plan_1.pdf").symlink_to(outside)
    with TestClient(create_app(settings=settings)) as client:
        response = client.post("/wbs/draft", json={"prefix": "S210", "drawings": ["drawings"]})
        assert response.status_code == 400


def test_wbs_ignores_files_without_numbered_page_suffix(resources):
    directory = resources.projects / "drawings"
    directory.mkdir()
    for name in ("plan_1.pdf", "plan_draft.pdf"):
        with pymupdf.open() as document:
            document.new_page().insert_text((50, 50), "numbered page")
            document.save(directory / name)
    assert [number for number, text in wbs_draft.pdf_text(directory)] == [1]


def test_template_asset_lookup_can_find_admin_directories(resources):
    from scripts.ocr.build_files import pages_of

    directory = resources.admin / "pdf/book"
    directory.mkdir(parents=True)
    (directory / "page_1.pdf").write_bytes(b"index-only")
    assert resources.asset("pdf/book") == directory
    assert pages_of("book") == [1]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "form": CODE,
            "cfg": {
                "anchors": [
                    {"id": "a", "doc": CODE, "kind": "EXCEL_RANGE", "field": "x", "range": 3}
                ]
            },
            "values": {},
        },
    ],
)
def test_invalid_excel_range_returns_validation_error(settings, payload):
    with TestClient(create_app(settings=settings)) as client:
        assert client.post("/ocr/fill", json=payload).status_code == 422


def test_invalid_wbs_basis_returns_validation_error(settings):
    with TestClient(create_app(settings=settings)) as client:
        response = client.post(
            "/wbs/draft",
            json={"prefix": "S210", "drawings": [], "basis": {"facts": [["路线起讫", 123]]}},
        )
        assert response.status_code == 422


def test_application_shutdown_releases_ocr_model_and_template_caches(settings):
    app = create_app(settings=settings)
    with TestClient(app) as client:
        assert client.get(f"/ocr/sheet/{CODE}").status_code == 200
        app.state.ocr_resources.engine = object()
    assert app.state.ocr_resources.engine is None
    assert app.state.ocr_resources.caches == {}
