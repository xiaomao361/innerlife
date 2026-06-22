from __future__ import annotations

import json

from innerlife.config import Settings
from innerlife.daemon import InnerLifeDaemon
from innerlife.storage import Storage
from conftest import load_profile


def test_daemon_processes_pending_and_records_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(tmp_path / "daemon.db"))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    monkeypatch.setenv("INNERLIFE_LLM_BACKEND", "fake")
    monkeypatch.setenv("INNERLIFE_AUTONOMY_ENABLED", "false")
    settings = Settings.from_env()
    daemon = InnerLifeDaemon(settings)
    daemon.storage.create_agent(load_profile("agent-a"))
    daemon.storage.submit_event(
        "agent-a",
        "afterthought",
        "session-a",
        {"text": "需要让系统真正可用"},
        event_id="daemon_source",
    )
    result = daemon.process_once()
    assert result["heartbeat"]["processed"] == 1
    assert daemon.storage.pending_events("agent-a") == []
    assert daemon.storage.get_service_state("daemon.heartbeat")["backend"] == "fake"


def test_doctor_default_root_is_not_project_data(monkeypatch):
    monkeypatch.delenv("INNERLIFE_ROOT", raising=False)
    monkeypatch.delenv("INNERLIFE_DB_PATH", raising=False)
    settings = Settings.from_env()
    assert settings.db_path.name == "innerlife.db"
    assert "apps/innerlife/data" not in str(settings.db_path)


def test_settings_load_private_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    for key in (
        "INNERLIFE_LLM_BACKEND",
        "INNERLIFE_LIGHT_MODEL",
        "INNERLIFE_MEMORIA_SYNC_AGENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "innerlife.env").write_text(
        "INNERLIFE_LLM_BACKEND=openai_compatible\n"
        "INNERLIFE_LIGHT_MODEL=local-small\n"
        "INNERLIFE_MEMORIA_SYNC_AGENTS=agent-a\n",
        encoding="utf-8",
    )
    settings = Settings.from_env()
    assert settings.backend == "openai_compatible"
    assert settings.light_model == "local-small"
    assert settings.memoria_sync_agents == ("agent-a",)


def test_settings_load_external_secret_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.env"
    secret.write_text("DEEPSEEK_API_KEY=test-secret\n", encoding="utf-8")
    monkeypatch.setenv("INNERLIFE_ROOT", str(root))
    monkeypatch.setenv("INNERLIFE_SECRET_ENV_FILE", str(secret))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("INNERLIFE_LLM_API_KEY", raising=False)
    settings = Settings.from_env()
    assert settings.api_key == "test-secret"


def test_settings_loads_secret_file_declared_inside_private_env(tmp_path, monkeypatch):
    secret = tmp_path / "secret.env"
    secret.write_text("INNERLIFE_LLM_API_KEY=indirect-secret\n", encoding="utf-8")
    (tmp_path / "innerlife.env").write_text(
        f"INNERLIFE_SECRET_ENV_FILE={secret}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    monkeypatch.delenv("INNERLIFE_SECRET_ENV_FILE", raising=False)
    monkeypatch.delenv("INNERLIFE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert Settings.from_env().api_key == "indirect-secret"
