"""Verify tunnel startup and lifecycle without connecting to a public server."""

import os
import shutil
import subprocess
import tomllib

import pytest

from app.config import ROOT


@pytest.fixture
def tunnel(tmp_path):
    if not shutil.which("zsh"):
        pytest.skip("macOS tunnel entry points require zsh")
    root = tmp_path / "project with spaces"
    shutil.copytree(ROOT / "scripts" / "dev", root / "scripts" / "dev")
    config = root / "config" / "dev" / "frp"
    config.mkdir(parents=True)
    (config / "frpc.toml").write_text('serverAddr = "107.182.190.191"\n')
    secrets = root / ".secrets" / "frp"
    secrets.mkdir(parents=True)
    (secrets / "token").write_text("test-token-never-print\n")
    (secrets / "ca.crt").write_text("test CA\n")
    binary = root / "bin"
    binary.mkdir()
    trace = root / "trace.txt"
    env = {
        "PATH": f"{binary}:/usr/bin:/bin",
        "TRACE_FILE": str(trace),
        "REGISTERED_FILE": str(root / "registered"),
    }

    def stub(name, body):
        path = binary / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)

    stub("uname", "echo Darwin")
    stub("curl", 'exit "${API_EXIT:-0}"')
    stub(
        "frpc",
        'printf "%s\\n" "$PWD" "$@" >> "$TRACE_FILE"\n'
        'if [ "$1" = verify ]; then exit "${VERIFY_EXIT:-0}"; fi',
    )
    stub(
        "launchctl",
        'printf "%s\\n" "$@" >> "$TRACE_FILE"\n'
        'case "$1" in\n'
        'list) test -e "$REGISTERED_FILE" ;;\n'
        'submit) touch "$REGISTERED_FILE" ;;\n'
        'remove) rm -f "$REGISTERED_FILE" ;;\n'
        "esac",
    )

    def run(script="start-frpc.sh", *args):
        return subprocess.run(
            [shutil.which("zsh"), str(root / "scripts" / "dev" / script), *args],
            cwd="/",
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    return root, env, trace, run


def test_frpc_configuration_targets_business_api_and_verifies_server_identity():
    config = tomllib.loads((ROOT / "config" / "dev" / "frp" / "frpc.toml").read_text())
    assert config["serverAddr"] == "107.182.190.191"
    assert config["serverPort"] == 7000
    assert config["auth"]["tokenSource"]["type"] == "file"
    assert config["transport"]["tls"]["trustedCaFile"] == ".secrets/frp/ca.crt"
    assert config["transport"]["tls"]["serverName"] == "107.182.190.191"
    proxy = config["proxies"][0]
    assert (proxy["localIP"], proxy["localPort"], proxy["remotePort"]) == (
        "127.0.0.1",
        8309,
        18000,
    )


def test_frpc_starts_from_other_directory_without_changing_business_env(tunnel):
    root, _, trace, run = tunnel
    env_file = root / ".env"
    env_file.write_text("LLM_API_KEY=preserve-this\n")
    result = run()
    assert result.returncode == 0, result.stderr
    commands = trace.read_text()
    assert f"{root}\nverify\n-c\nconfig/dev/frp/frpc.toml\n" in commands
    assert commands.endswith(f"{root}\n-c\nconfig/dev/frp/frpc.toml\n")
    assert env_file.read_text() == "LLM_API_KEY=preserve-this\n"
    assert "test-token-never-print" not in result.stdout + result.stderr + commands


@pytest.mark.parametrize("missing", ("token", "ca.crt"))
def test_frpc_rejects_missing_credentials_before_launch(tunnel, missing):
    root, _, trace, run = tunnel
    (root / ".secrets" / "frp" / missing).unlink()
    result = run()
    assert result.returncode != 0
    assert missing in result.stderr
    assert not trace.exists()


def test_frpc_rejects_unhealthy_local_api(tunnel):
    _, env, trace, run = tunnel
    env["API_EXIT"] = "7"
    result = run()
    assert result.returncode != 0
    assert "8309" in result.stderr
    assert trace.read_text().count("-c\n") == 1


def test_frpc_does_not_launch_after_configuration_failure(tunnel):
    _, env, trace, run = tunnel
    env["VERIFY_EXIT"] = "1"
    result = run()
    assert result.returncode != 0
    assert trace.read_text().count("verify\n") == 1
    assert trace.read_text().count("-c\n") == 1


def test_frpc_check_validates_without_starting_tunnel(tunnel):
    _, _, trace, run = tunnel
    result = run("start-frpc.sh", "--check")
    assert result.returncode == 0, result.stderr
    assert trace.read_text().count("-c\n") == 1


def test_frpc_background_start_is_idempotent_and_stop_owns_only_its_job(tunnel):
    _, env, trace, run = tunnel
    first = run("services.sh", "start-frpc")
    assert first.returncode == 0, first.stderr
    second = run("services.sh", "start-frpc")
    assert second.returncode == 0, second.stderr
    commands = trace.read_text()
    assert commands.count("submit\n") == 1
    assert "local.highway-agent.frpc" in commands
    assert "start-frpc.sh" in commands
    stop = run("services.sh", "stop-frpc")
    assert stop.returncode == 0, stop.stderr
    assert not os.path.exists(env["REGISTERED_FILE"])
    commands = trace.read_text()
    assert "remove\nlocal.highway-agent.frpc\n" in commands
    assert "local.highway-agent.api" not in commands


def test_frpc_background_job_is_not_submitted_when_preflight_fails(tunnel):
    root, _, trace, run = tunnel
    (root / ".secrets" / "frp" / "token").unlink()
    result = run("services.sh", "start-frpc")
    assert result.returncode != 0
    assert not trace.exists() or "submit\n" not in trace.read_text()
