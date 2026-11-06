"""OCR 第三方输出边界的有效结果与不完整结果回归。"""

from types import SimpleNamespace

import numpy as np
import pytest

from app.ocr.core import cuda_runtime
from app.ocr.core.engine import ocr
from app.ocr.core.resources import OCRModelError, OCRResources, use_resources
from tests.ocr_helpers import make_ocr_settings, ocr_result


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(cls_res=[]),
        SimpleNamespace(boxes=np.zeros((1, 4, 2))),
        SimpleNamespace(txts=("文字",), scores=(0.9,)),
        SimpleNamespace(boxes=None, txts=("文字",), scores=(0.9,)),
        SimpleNamespace(boxes=np.zeros((1, 4, 2)), txts=(), scores=()),
    ],
)
def test_partial_ocr_output_raises_model_error(tmp_path, result):
    resources = OCRResources(make_ocr_settings(tmp_path))
    resources.engine = lambda image: result
    with use_resources(resources), pytest.raises(OCRModelError, match="OCR 模型输出不完整"):
        ocr(np.zeros((20, 20, 3), dtype=np.uint8))


def test_local_cuda_skips_dll_registration_when_platform_has_no_dll_api(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    monkeypatch.delattr(cuda_runtime.os, "add_dll_directory", raising=False)
    monkeypatch.setenv("PATH", "unchanged")
    assert cuda_runtime.enable_local_cuda(tmp_path) == []
    assert cuda_runtime.os.environ["PATH"] == "unchanged"


@pytest.mark.parametrize("empty", [True, False])
def test_complete_ocr_output_remains_supported(tmp_path, empty):
    result = ocr_result() if empty else ocr_result(([[1, 2], [5, 2], [5, 6], [1, 6]], "文字", 0.9))
    resources = OCRResources(make_ocr_settings(tmp_path))
    resources.engine = lambda image: result
    with use_resources(resources):
        assert ocr(np.zeros((20, 20, 3), dtype=np.uint8)) == (
            [] if empty else [{"s": "文字", "box": [1.0, 2.0, 5.0, 6.0], "conf": 0.9}]
        )
