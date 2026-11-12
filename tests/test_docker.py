"""通过 Compose 实际解析验证生产配置，不启动容器或访问模型。"""

import json
import os
import shutil
import subprocess

import pytest

from app.config import ROOT, Settings


@pytest.fixture
def compose_environment():
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("此环境未安装 Docker CLI，无法执行 Compose 配置解析")
    # 不继承本机 LLM/OCR 密钥或配置，保证测试只使用公开模板与显式覆盖值。
    environment = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ}
    version = subprocess.run(
        [docker, "compose", "version"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if version.returncode:
        pytest.skip("此环境未安装 Docker Compose 插件")
    return docker, environment


@pytest.mark.parametrize(
    ("overrides", "expected_timeout", "expected_concurrency"),
    [
        ({}, 30, 1),
        ({"JOURNAL_TIMEOUT_SECONDS": "45", "JOURNAL_CONCURRENCY": "3"}, 45, 3),
    ],
)
def test_compose_passes_main_work_configuration_to_api(
    compose_environment, overrides, expected_timeout, expected_concurrency
):
    docker, environment = compose_environment
    process = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(ROOT / "compose.prod.yml"),
            "--env-file",
            str(ROOT / "docker/env.example"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment | overrides,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr
    injected = json.loads(process.stdout)["services"]["agent-service"]["environment"]
    settings = Settings(
        _env_file=None,
        journal_timeout_seconds=injected["JOURNAL_TIMEOUT_SECONDS"],
        journal_concurrency=injected["JOURNAL_CONCURRENCY"],
    )
    assert settings.journal_timeout_seconds == expected_timeout
    assert settings.journal_concurrency == expected_concurrency


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_compose_ocr_variant(compose_environment, device):
    docker, environment = compose_environment
    process = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(ROOT / "compose.prod.yml"),
            "--env-file",
            str(ROOT / "docker/env.example"),
            "config",
            "--format",
            "json",
        ],
        env=environment | {"OCR_DEVICE": device},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr
    services = json.loads(process.stdout)["services"]
    api = services["agent-service"]
    assert api["build"]["args"]["OCR_DEVICE"] == device
    assert api["image"] == "agent-service:0.1.0"
    assert api["environment"]["OCR_DEVICE"] == device
    devices = api.get("deploy", {}).get("resources", {}).get("reservations", {}).get("devices", [])
    assert devices[0]["driver"] == "nvidia"
    assert services["model"]["deploy"]["resources"]["reservations"]["devices"]


@pytest.mark.parametrize("model_directory", [None, "", "missing"])
def test_compose_ocr_models_optional(compose_environment, tmp_path, model_directory):
    docker, environment = compose_environment
    template = (ROOT / "docker/env.example").read_text()
    env_file = tmp_path / "deploy.env"
    env_file.write_text(
        "\n".join(line for line in template.splitlines() if not line.startswith("OCR_MODEL_DIR="))
    )
    overrides = (
        {}
        if model_directory is None
        else {
            "OCR_MODEL_DIR": str(tmp_path / "not-created") if model_directory == "missing" else ""
        }
    )
    process = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(ROOT / "compose.prod.yml"),
            "--env-file",
            str(env_file),
            "config",
            "--format",
            "json",
        ],
        env=environment | overrides,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr
    configuration = json.loads(process.stdout)
    mounts = configuration["services"]["agent-service"]["volumes"]
    models = next(mount for mount in mounts if mount["target"] == "/app/data/ocr/models")
    assert not models.get("read_only", False)
    if model_directory == "missing":
        assert models["type"] == "bind"
        # 短语法默认创建目录，Compose 5 的标准化输出会省略默认值。
        assert models["bind"].get("create_host_path", True) is True
    else:
        assert models["type"] == "volume"
        assert models["source"] == "ocr-models"
        assert "ocr-models" in configuration["volumes"]
