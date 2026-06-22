from __future__ import annotations

import json
import os
import subprocess
import sys

from innerlife.config import PROJECT_ROOT


def run_cli(tmp_path, *args):
    env = os.environ.copy()
    env["INNERLIFE_DB_PATH"] = str(tmp_path / "cli.db")
    return subprocess.run(
        [sys.executable, "-m", "innerlife.cli", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_happy_path_and_error_status(tmp_path):
    initialized = run_cli(tmp_path, "init-db", "--json")
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["initialized"] is True

    created = run_cli(
        tmp_path,
        "create-agent",
        "--profile",
        str(PROJECT_ROOT / "profiles" / "example-agent.json"),
        "--json",
    )
    assert created.returncode == 0, created.stderr

    state = run_cli(tmp_path, "state", "--agent", "example-agent", "--json")
    assert state.returncode == 0, state.stderr
    assert json.loads(state.stdout)["profile"]["agent_id"] == "example-agent"

    missing = run_cli(tmp_path, "state", "--agent", "missing", "--json")
    assert missing.returncode == 1
    assert "Unknown agent" in missing.stderr


def test_init_creates_example_agent_and_doctor_does_not_create_hidden_agents(
    tmp_path,
):
    initialized = run_cli(tmp_path, "init", "--json")
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["agent"]["profile"]["agent_id"] == "example-agent"

    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_cli(empty, "doctor", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["agents"] == []
    assert any("No agents configured" in item for item in payload["warnings"])
