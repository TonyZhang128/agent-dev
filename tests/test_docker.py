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
        ({"MAIN_WORK_SPLIT_TIMEOUT_SECONDS": "45", "MAIN_WORK_SPLIT_CONCURRENCY": "3"}, 45, 3),
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
    injected = json.loads(process.stdout)["services"]["api"]["environment"]
    settings = Settings(
        _env_file=None,
        main_work_split_timeout_seconds=injected["MAIN_WORK_SPLIT_TIMEOUT_SECONDS"],
        main_work_split_concurrency=injected["MAIN_WORK_SPLIT_CONCURRENCY"],
    )
    assert settings.main_work_split_timeout_seconds == expected_timeout
    assert settings.main_work_split_concurrency == expected_concurrency
