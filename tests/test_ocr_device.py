"""OCR 固定使用 CUDA：运行库不可用时应失败，不得静默回退 CPU。"""

from pathlib import Path

import pytest

from app.config import Settings
from app.ocr.core import cuda_runtime
from app.ocr.core import engine as ocr_engine
from app.ocr.core.resources import OCRModelError, OCRResources, use_resources


def test_rapidocr_params_always_enable_cuda_ep():
    params = ocr_engine.rapidocr_params(Path("models"))
    assert params["Global.model_root_dir"] == "models"
    assert params["EngineConfig.onnxruntime.use_cuda"] is True
    assert params["EngineConfig.onnxruntime.cuda_ep_cfg"]["device_id"] == 0


def test_enable_local_cuda_registers_bin_directories(tmp_path, monkeypatch):
    added = []
    monkeypatch.setattr(cuda_runtime.os, "add_dll_directory", added.append)
    (tmp_path / "libcublas" / "bin").mkdir(parents=True)
    (tmp_path / "cudnn" / "bin").mkdir(parents=True)

    found = cuda_runtime.enable_local_cuda(tmp_path)

    assert {Path(p) for p in added} == {
        tmp_path / "libcublas" / "bin",
        tmp_path / "cudnn" / "bin",
    }
    assert found == sorted(found)
    head = cuda_runtime.os.environ["PATH"].split(cuda_runtime.os.pathsep)
    assert head[:2] == [str(tmp_path / "cudnn" / "bin"), str(tmp_path / "libcublas" / "bin")]


def test_enable_local_cuda_without_libs_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(cuda_runtime.os, "add_dll_directory", lambda p: None)
    assert cuda_runtime.enable_local_cuda(tmp_path) == []


def test_resources_resolve_cuda_root():
    settings = Settings(_env_file=None, ocr_cuda_root=Path("pool"))
    resources = OCRResources(settings)
    assert resources.cuda_root.is_absolute()


def test_engine_always_requests_cuda(monkeypatch):
    import rapidocr

    settings = Settings(_env_file=None)
    monkeypatch.setattr(cuda_runtime, "ensure_cuda_runtime", lambda resources: None)
    captured = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs["params"])

    monkeypatch.setattr(rapidocr, "RapidOCR", FakeRapidOCR)
    with use_resources(OCRResources(settings)):
        ocr_engine.engine()

    assert captured["EngineConfig.onnxruntime.use_cuda"] is True


def test_ensure_cuda_runtime_rejects_missing_cuda_ep(monkeypatch, tmp_path):
    import onnxruntime as ort

    monkeypatch.setattr(cuda_runtime, "enable_local_cuda", lambda root: [])
    monkeypatch.setattr(cuda_runtime, "probe_cuda", lambda models: True)
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(ort, "get_device", lambda: "CPU")
    resources = OCRResources(Settings(_env_file=None, ocr_cuda_root=tmp_path))

    with pytest.raises(OCRModelError):
        cuda_runtime.ensure_cuda_runtime(resources)


def test_engine_raises_when_cuda_runtime_unusable(monkeypatch):
    import rapidocr

    settings = Settings(_env_file=None)

    def reject_cuda(resources):
        raise OCRModelError(cuda_runtime.CUDA_UNAVAILABLE)

    monkeypatch.setattr(cuda_runtime, "ensure_cuda_runtime", reject_cuda)
    monkeypatch.setattr(rapidocr, "RapidOCR", lambda **kwargs: None)

    with use_resources(OCRResources(settings)):
        with pytest.raises(OCRModelError):
            ocr_engine.engine()
