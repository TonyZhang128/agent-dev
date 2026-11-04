"""本地依赖与资源诊断：静态检查、设备一致性和错误脱敏。"""

import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.ocr.core import deps
from app.ocr.core.resources import OCRResources


class FakeOrt:
    def __init__(self, providers, device="CPU"):
        self.providers = providers
        self.device = device

    def get_available_providers(self):
        return self.providers

    def get_device(self):
        return self.device


def make_resources(tmp_path, *, device="cpu", model_files=1):
    templates = tmp_path / "templates"
    for relative in ("forms", "layouts", "refs"):
        (templates / relative).mkdir(parents=True)
    (templates / "forms/files.json").write_text('{"forms": {"JB12": {}}}', encoding="utf-8")
    (templates / "layouts/jb12.json").write_text('{"forms": {}}', encoding="utf-8")
    (templates / "layouts/book1.json").write_text('{"forms": {}}', encoding="utf-8")
    (templates / "refs/wbs_rules.json").write_text('{"drawingCues": {}}', encoding="utf-8")
    admin = tmp_path / "admin"
    admin.mkdir()
    assets = tmp_path / "assets"
    assets.mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    models = tmp_path / "models"
    models.mkdir()
    for index in range(model_files):
        (models / f"model{index}.onnx").write_bytes(b"")
    settings = Settings(
        _env_file=None,
        templates_root=templates,
        admin_root=admin,
        asset_root=assets,
        projects_root=projects,
        ocr_model_root=models,
        ocr_device=device,
    )
    return OCRResources(settings)


def fake_ort(monkeypatch, providers, device="CPU"):
    module = FakeOrt(providers, device)
    actual = deps._load

    def load(name):
        return module if name == "onnxruntime" else actual(name)

    monkeypatch.setattr(deps, "_load", load)


def test_check_reports_complete_cpu_resources(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CPUExecutionProvider"], "CPU")
    resources = make_resources(tmp_path)

    result = deps.check(resources)

    assert result["ok"] is True
    assert result["warnings"] == []
    inference = result["caps"]["推理设备"]
    assert inference["configured"] == "cpu"
    assert inference["device"] == "CPU"
    assert "CPUExecutionProvider" in inference["providers"]
    assert result["caps"]["OCR 资源"]["templates"] == {"ok": True, "forms": 1}
    assert result["caps"]["OCR 资源"]["models"]["files"] == 1
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_missing_template_manifest_marks_failure(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CPUExecutionProvider"], "CPU")
    resources = make_resources(tmp_path)
    (resources.templates / "forms/files.json").unlink()

    result = deps.check(resources)

    assert result["ok"] is False
    assert result["caps"]["OCR 资源"]["templates"]["ok"] is False
    assert result["caps"]["OCR 资源"]["templates"]["error"] == "OCRResourceError"


def test_empty_writable_model_directory_is_warning(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CPUExecutionProvider"], "CPU")
    resources = make_resources(tmp_path, model_files=0)

    result = deps.check(resources)

    assert result["ok"] is True
    assert result["caps"]["OCR 资源"]["models"] == {
        "ok": True,
        "files": 0,
        "writable": True,
    }
    assert any("模型" in warning for warning in result["warnings"])


def test_unwritable_model_directory_marks_failure(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CPUExecutionProvider"], "CPU")
    resources = make_resources(tmp_path, model_files=0)
    monkeypatch.setattr(deps, "_writable", lambda path: False)

    result = deps.check(resources)

    assert result["ok"] is False
    assert result["caps"]["OCR 资源"]["models"]["ok"] is False


def test_cuda_configuration_requires_cuda_provider(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CPUExecutionProvider"], "CPU")
    resources = make_resources(tmp_path, device="cuda")

    result = deps.check(resources)

    assert result["ok"] is False
    assert result["caps"]["推理设备"]["ok"] is False
    assert result["caps"]["推理设备"]["configured"] == "cuda"


def test_cpu_configuration_requires_cpu_provider(tmp_path, monkeypatch):
    fake_ort(monkeypatch, ["CUDAExecutionProvider"], "GPU")
    resources = make_resources(tmp_path, device="cpu")

    result = deps.check(resources)

    assert result["ok"] is False
    assert result["caps"]["推理设备"]["ok"] is False


def test_import_failure_is_reported_without_raising(tmp_path, monkeypatch):
    resources = make_resources(tmp_path)
    actual = deps._load

    def load(name):
        if name == "onnxruntime":
            raise ModuleNotFoundError("onnxruntime")
        return actual(name)

    monkeypatch.setattr(deps, "_load", load)

    result = deps.check(resources)

    assert result["ok"] is False
    assert result["caps"]["推理设备"] == {
        "ok": False,
        "configured": "cpu",
        "error": "ModuleNotFoundError",
    }


def test_missing_resources_does_not_raise():
    result = deps.check(None)

    assert result["caps"]["OCR 资源"] == {"ok": False, "error": "应用资源未初始化"}
    assert isinstance(result["warnings"], list)


def test_diagnostics_endpoint_returns_envelope():
    with TestClient(create_app()) as client:
        response = client.get("/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == 200
    assert set(body["data"]) == {"ok", "warnings", "caps"}
