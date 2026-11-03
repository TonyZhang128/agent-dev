"""OCR 推理设备可配置：cuda(默认,校验运行库)或 cpu(Mac 等无 NVIDIA GPU 环境)。"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ocr.core import cuda_runtime
from app.ocr.core import engine as ocr_engine
from app.ocr.core.resources import OCRModelError, OCRResources, use_resources


def test_rapidocr_params_enable_cuda_ep_by_default():
    params = ocr_engine.rapidocr_params(Path("models"))
    assert params["Global.model_root_dir"] == "models"
    assert params["EngineConfig.onnxruntime.use_cuda"] is True
    assert params["EngineConfig.onnxruntime.cuda_ep_cfg"]["device_id"] == 0


def test_rapidocr_params_cpu_mode_disables_cuda_ep():
    params = ocr_engine.rapidocr_params(Path("models"), use_cuda=False)
    assert params["Global.model_root_dir"] == "models"
    assert params["EngineConfig.onnxruntime.use_cuda"] is False
    assert "EngineConfig.onnxruntime.cuda_ep_cfg" not in params


def test_settings_ocr_device_defaults_to_cuda():
    assert Settings(_env_file=None).ocr_device == "cuda"


def test_settings_ocr_device_accepts_cpu():
    assert Settings(_env_file=None, ocr_device="cpu").ocr_device == "cpu"


def test_settings_ocr_device_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ocr_device="metal")


def test_resources_expose_configured_device():
    resources = OCRResources(Settings(_env_file=None, ocr_device="cpu"))
    assert resources.device == "cpu"


@pytest.mark.skipif(sys.platform != "win32", reason="DLL 搜索路径注册是 Windows 免安装 redist 方案")
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


def test_engine_requests_cuda_in_default_mode(monkeypatch):
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


def test_engine_cpu_mode_skips_cuda_runtime(monkeypatch):
    import rapidocr

    settings = Settings(_env_file=None, ocr_device="cpu")

    def reject_cuda(resources):
        raise AssertionError("cpu 模式不得校验 CUDA 运行库")

    monkeypatch.setattr(cuda_runtime, "ensure_cuda_runtime", reject_cuda)
    captured = {}

    class FakeRapidOCR:
        def __init__(self, **kwargs):
            captured.update(kwargs["params"])

    monkeypatch.setattr(rapidocr, "RapidOCR", FakeRapidOCR)
    with use_resources(OCRResources(settings)):
        ocr_engine.engine()

    assert captured["EngineConfig.onnxruntime.use_cuda"] is False
    assert "EngineConfig.onnxruntime.cuda_ep_cfg" not in captured


@pytest.mark.skipif(sys.platform != "win32", reason="CUDA EP 校验依赖 Windows 本机 redist 运行库")
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
