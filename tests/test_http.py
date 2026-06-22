from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app


def test_http_status_and_briefing(tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(tmp_path / "http.db"))
    from conftest import load_profile
    from innerlife.storage import Storage

    storage = Storage(tmp_path / "http.db")
    storage.init_db()
    storage.create_agent(load_profile("agent-a"))
    client = TestClient(app)
    status = client.get("/api/status")
    assert status.status_code == 200
    assert len(status.json()["agents"]) == 1
    briefing = client.get("/api/agents/agent-a/briefing")
    assert briefing.status_code == 200
    assert briefing.json()["agent_id"] == "agent-a"
