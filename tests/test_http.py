from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app


def test_http_status_and_briefing(tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(tmp_path / "http.db"))
    from innerlife.daemon import ensure_default_agents
    from innerlife.storage import Storage

    storage = Storage(tmp_path / "http.db")
    storage.init_db()
    ensure_default_agents(storage)
    client = TestClient(app)
    status = client.get("/api/status")
    assert status.status_code == 200
    assert len(status.json()["agents"]) == 2
    briefing = client.get("/api/agents/clara/briefing")
    assert briefing.status_code == 200
    assert briefing.json()["agent_id"] == "clara"
