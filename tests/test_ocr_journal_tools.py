"""离线构建工具实际输出模板和覆盖图；不依赖本机业务文件。"""

import json

from PIL import Image

from tests.test_ocr_journal_template import write_template


def test_build_cli_writes_template_and_overlay(tmp_path):
    from scripts.ocr.build_journal_template import main

    pdf = tmp_path / "source.pdf"
    snapshot = tmp_path / "generated.json"
    overlay = tmp_path / "template.png"
    write_template(pdf)
    main(["--pdf", str(pdf), "--output", str(snapshot), "--overlay", str(overlay)])
    assert len(json.loads(snapshot.read_text())["fields"]) == 11
    with Image.open(overlay) as rendered:
        assert rendered.width > 595
        assert rendered.height > 842


def test_inspection_removes_previous_success_when_next_photo_needs_agent(tmp_path, monkeypatch):
    import rapidocr

    from scripts.ocr import inspect_journal
    from tests.ocr_helpers import make_ocr_settings
    from tests.test_agents_main_work import MIXED_MAIN_WORK_PARTS, JournalEngine
    from tests.test_ocr_journal import write_photo

    settings = make_ocr_settings(tmp_path)
    write_photo(settings)
    monkeypatch.setattr(inspect_journal, "Settings", lambda: settings)
    monkeypatch.setattr(rapidocr, "RapidOCR", lambda **kwargs: JournalEngine())
    output = tmp_path / "inspection"
    photo = settings.projects_root / "journal.png"
    inspect_journal.inspect_photo(photo, output)
    assert (output / "response.json").exists()
    monkeypatch.setattr(
        rapidocr, "RapidOCR", lambda **kwargs: JournalEngine(parts=MIXED_MAIN_WORK_PARTS)
    )
    report = inspect_journal.inspect_photo(photo, output)
    assert report["split_strategy"] == "requires_model"
    assert report["response"] is None
    assert not (output / "response.json").exists()
