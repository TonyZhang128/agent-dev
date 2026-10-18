"""Exercise deployment entry points without installing packages or starting services."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import ROOT, Settings
from scripts.prod.check_config import main as check_production_config


class DeploymentScriptTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="qwen scripts ")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
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

    def test_wrong_platform_exits_before_install_or_launch(self):
        self.stub("uname", "echo Darwin")
        for script in ("setup.sh", "start-api.sh", "start-vllm.sh", "verify.sh"):
            with self.subTest(script=script):
                result = self.run_script(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Linux", result.stderr)
                self.assertFalse(self.trace.exists())

    def test_setup_preserves_existing_env_and_installs_runtime_only(self):
        env_file = self.root / ".env"
        original = b"LLM_API_KEY=keep-this-value\n"
        env_file.write_bytes(original)
        result = self.run_script("setup.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(env_file.read_bytes(), original)
        commands = self.trace.read_text()
        self.assertIn("sync\n--locked\n--no-dev\n", commands)
        self.assertNotIn("vllm", commands)

    def test_setup_creates_linux_template_with_private_permissions(self):
        result = self.run_script("setup.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        env_file = self.root / ".env"
        self.assertIn("http://127.0.0.1:8001/v1", env_file.read_text())
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)

    def test_api_start_works_outside_project_and_does_not_sync(self):
        result = self.run_script("start-api.sh", "--workers", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.trace.read_text()
        self.assertIn(str(self.root), commands)
        self.assertIn("--no-sync\n--no-dev\nuvicorn\napp.main:app", commands)
        self.assertIn("--workers\n2", commands)

    def test_api_rejects_reload_before_start(self):
        for arg in ("--reload", "--reload=true"):
            with self.subTest(arg=arg):
                result = self.run_script("start-api.sh", arg)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.trace.exists())

    def test_api_does_not_start_if_config_check_fails(self):
        self.stub("uv", "exit 1")
        self.assertNotEqual(self.run_script("start-api.sh").returncode, 0)

    def test_vllm_requires_working_gpu_before_launch(self):
        self.stub("nvidia-smi", "exit 1")
        self.assertNotEqual(self.run_script("start-vllm.sh").returncode, 0)
        self.assertFalse(self.trace.exists())

    def test_vllm_requires_explicit_key(self):
        del self.env["VLLM_API_KEY"]
        result = self.run_script("start-vllm.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VLLM_API_KEY", result.stderr)
        self.assertFalse(self.trace.exists())

    def test_vllm_rejects_business_venv(self):
        path = self.venv / "vllm"
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        self.env["VLLM_BIN"] = str(path)
        result = self.run_script("start-vllm.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("独立环境", result.stderr)

    def test_vllm_preserves_arguments_without_key_in_argv(self):
        result = self.run_script("start-vllm.sh", "--tensor-parallel-size", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.trace.read_text().splitlines()
        self.assertEqual(args[:2], ["serve", "/models/qwen model"])
        self.assertIn("qwen-business", args)
        self.assertEqual(args[-2:], ["--tensor-parallel-size", "2"])
        self.assertNotIn(self.env["VLLM_API_KEY"], " ".join(args) + result.stdout + result.stderr)

    def test_production_config_rejects_mac_defaults_and_placeholder_keys(self):
        for values in (
            {},
            {"llm_base_url": "http://127.0.0.1:8001/v1", "llm_model": "qwen-business"},
            {
                "llm_base_url": "http://127.0.0.1:8001/v1",
                "llm_model": "qwen-business",
                "llm_api_key": "CHANGE_ME",
            },
        ):
            with self.subTest(values=values), patch.dict(os.environ, {}, clear=True):
                settings = Settings(_env_file=None, **values)
                with patch("scripts.prod.check_config.Settings", return_value=settings):
                    with self.assertRaises(SystemExit):
                        check_production_config()

    def test_production_config_accepts_remote_vllm(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(
                _env_file=None,
                llm_base_url="https://model.example.com/v1",
                llm_model="qwen-business",
                llm_api_key="test-production-key",
            )
        with patch("scripts.prod.check_config.Settings", return_value=settings):
            check_production_config()

    @unittest.skipUnless(shutil.which("zsh"), "macOS compatibility scripts require zsh")
    def test_legacy_mac_api_entry_preserves_root_and_reload(self):
        self.stub("uname", "echo Darwin")
        result = subprocess.run(
            ["zsh", str(self.root / "scripts" / "start-api.sh"), "--reload"],
            cwd="/",
            env=self.env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.trace.read_text()
        self.assertIn(str(self.root), commands)
        self.assertIn("uvicorn\napp.main:app", commands)
        self.assertIn("--reload", commands)

    def test_legacy_python_entry_points_resolve_to_expected_environments(self):
        from scripts import verify_agents, verify_live
        from scripts.common import verify_agents as common_agents
        from scripts.dev import verify_live as mac_live

        self.assertIs(verify_agents.main, common_agents.main)
        self.assertIs(verify_live.main, mac_live.main)


if __name__ == "__main__":
    unittest.main()
