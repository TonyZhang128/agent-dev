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
