"""Exercise deployment entry points without installing packages or starting services."""

import shutil
import subprocess

import pytest

from app.config import ROOT, Settings
from scripts.prod.check_config import main as check_production_config


class ScriptHarness:
    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        shutil.copytree(ROOT / "scripts" / "prod", self.root / "scripts" / "prod")
        shutil.copytree(ROOT / "scripts" / "dev", self.root / "scripts" / "dev")
        shutil.copyfile(ROOT / "scripts" / "start-api.sh", self.root / "scripts" / "start-api.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.trace = self.root / "commands.txt"
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "TRACE_FILE": str(self.trace),
            "VLLM_MODEL_PATH": "/models/qwen model",
            "VLLM_API_KEY": "test-secret-never-in-argv",
        }
        self.stub("uname", "echo Linux")
        self.stub("uv", 'printf "%s\\n" "$PWD" "$@" >> "$TRACE_FILE"')
        self.stub("nvidia-smi", "exit 0")
        self.env["VLLM_BIN"] = str(self.stub("vllm", 'printf "%s\\n" "$@" > "$TRACE_FILE"'))
        self.venv = self.root / ".venv" / "bin"
        self.venv.mkdir(parents=True)
        for name in ("python", "uvicorn"):
            path = self.venv / name
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)
        return path

    def run_script(self, name, *args):
        return subprocess.run(
            ["/bin/bash", str(self.root / "scripts" / "prod" / name), *args],
            cwd="/",
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )


@pytest.fixture
def deployment(tmp_path):
    return ScriptHarness(tmp_path / "qwen scripts")


@pytest.mark.parametrize("script", ("setup.sh", "start-api.sh", "start-vllm.sh", "verify.sh"))
def test_wrong_platform_exits_before_install_or_launch(deployment, script):
    deployment.stub("uname", "echo Darwin")
    result = deployment.run_script(script)
    assert result.returncode != 0
    assert "Linux" in result.stderr
    assert not deployment.trace.exists()


def test_setup_preserves_existing_env_and_installs_runtime_only(deployment):
    env_file = deployment.root / ".env"
    original = b"LLM_API_KEY=keep-this-value\n"
    env_file.write_bytes(original)
    result = deployment.run_script("setup.sh")
    assert result.returncode == 0, result.stderr
    assert env_file.read_bytes() == original
    commands = deployment.trace.read_text()
    assert "sync\n--locked\n--no-dev\n" in commands
    assert "vllm" not in commands


def test_setup_creates_linux_template_with_private_permissions(deployment):
    result = deployment.run_script("setup.sh")
    assert result.returncode == 0, result.stderr
    env_file = deployment.root / ".env"
    assert "http://127.0.0.1:8001/v1" in env_file.read_text()
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_api_start_works_outside_project_and_does_not_sync(deployment):
    result = deployment.run_script("start-api.sh", "--workers", "2")
    assert result.returncode == 0, result.stderr
    commands = deployment.trace.read_text()
    assert str(deployment.root) in commands
    assert "--no-sync\n--no-dev\nuvicorn\napp.main:app" in commands
    assert "--port\n8309" in commands
    assert "--workers\n2" in commands


@pytest.mark.parametrize("arg", ("--reload", "--reload=true"))
def test_api_rejects_reload_before_start(deployment, arg):
    result = deployment.run_script("start-api.sh", arg)
    assert result.returncode == 2
    assert not deployment.trace.exists()


def test_api_does_not_start_if_config_check_fails(deployment):
    deployment.stub("uv", "exit 1")
    assert deployment.run_script("start-api.sh").returncode != 0


def test_vllm_requires_working_gpu_before_launch(deployment):
    deployment.stub("nvidia-smi", "exit 1")
    assert deployment.run_script("start-vllm.sh").returncode != 0
    assert not deployment.trace.exists()


def test_vllm_requires_explicit_key(deployment):
    del deployment.env["VLLM_API_KEY"]
    result = deployment.run_script("start-vllm.sh")
    assert result.returncode != 0
    assert "VLLM_API_KEY" in result.stderr
    assert not deployment.trace.exists()


def test_vllm_rejects_business_venv(deployment):
    path = deployment.venv / "vllm"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    deployment.env["VLLM_BIN"] = str(path)
    result = deployment.run_script("start-vllm.sh")
    assert result.returncode != 0
    assert "独立环境" in result.stderr


def test_vllm_preserves_arguments_without_key_in_argv(deployment):
    result = deployment.run_script("start-vllm.sh", "--tensor-parallel-size", "2")
    assert result.returncode == 0, result.stderr
    args = deployment.trace.read_text().splitlines()
    assert args[:2] == ["serve", "/models/qwen model"]
    assert "highway-agent" in args
    assert args[-2:] == ["--tensor-parallel-size", "2"]
    assert deployment.env["VLLM_API_KEY"] not in " ".join(args) + result.stdout + result.stderr


@pytest.mark.parametrize(
    "values",
    (
        {},
        {"llm_base_url": "http://127.0.0.1:8001/v1", "llm_model": "highway-agent"},
        {
            "llm_base_url": "http://127.0.0.1:8001/v1",
            "llm_model": "highway-agent",
            "llm_api_key": "CHANGE_ME",
        },
    ),
    ids=["mac-defaults", "ollama-key", "placeholder-key"],
)
def test_production_config_rejects_mac_defaults_and_placeholder_keys(monkeypatch, values):
    settings = Settings(_env_file=None, **values)
    monkeypatch.setattr("scripts.prod.check_config.Settings", lambda: settings)
    with pytest.raises(SystemExit):
        check_production_config()


def test_production_config_accepts_remote_vllm(monkeypatch):
    settings = Settings(
        _env_file=None,
        llm_base_url="https://model.example.com/v1",
        llm_model="highway-agent",
        llm_api_key="test-production-key",
    )
    monkeypatch.setattr("scripts.prod.check_config.Settings", lambda: settings)
    check_production_config()


@pytest.mark.skipif(not shutil.which("zsh"), reason="macOS compatibility scripts require zsh")
def test_legacy_mac_api_entry_preserves_root_and_reload(deployment):
    deployment.stub("uname", "echo Darwin")
    result = subprocess.run(
        ["zsh", str(deployment.root / "scripts" / "start-api.sh"), "--reload"],
        cwd="/",
        env=deployment.env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    commands = deployment.trace.read_text()
    assert str(deployment.root) in commands
    assert "uvicorn\napp.main:app" in commands
    assert "--port\n8309" in commands
    assert "--reload" in commands


def test_production_entry_points_do_not_include_frp_tunnel():
    for path in (ROOT / "scripts" / "prod").iterdir():
        if path.suffix in {".sh", ".py"}:
            assert "frp" not in path.read_text(encoding="utf-8").lower(), path.name
    assert not (ROOT / "config" / "frp").exists()


def test_legacy_python_entry_points_resolve_to_expected_environments():
    from scripts import verify_agents, verify_live
    from scripts.common import verify_agents as common_agents
    from scripts.dev import verify_live as mac_live

    assert verify_agents.main is common_agents.main
    assert verify_live.main is mac_live.main
