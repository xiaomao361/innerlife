from __future__ import annotations

from innerlife.models import NotFoundError
from innerlife.storage import Storage

from conftest import load_profile


def test_init_is_idempotent_and_agents_are_isolated(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    store.init_db()
    store.init_db()
    store.create_agent(load_profile("agent-a"))
    store.create_agent(load_profile("agent-b"))

    store.submit_event(
        "agent-a",
        "afterthought",
        "session-a",
        {"text": "Agent A private"},
        event_id="private_agent-a",
    )

    assert [event["id"] for event in store.pending_events("agent-a")] == [
        "private_agent-a"
    ]
    assert store.pending_events("agent-b") == []
    try:
        store.get_inbox_event("private_agent-a", "agent-b")
    except NotFoundError:
        pass
    else:
        raise AssertionError("Agent B could read Agent A's event")


def test_pending_events_have_stable_order(storage):
    timestamp = "2026-06-22T00:00:00+00:00"
    storage.submit_event(
        "agent-a",
        "afterthought",
        "session-b",
        {"text": "second by id"},
        event_id="event_b",
        created_at=timestamp,
    )
    storage.submit_event(
        "agent-a",
        "afterthought",
        "session-a",
        {"text": "first by id"},
        event_id="event_a",
        created_at=timestamp,
    )

    assert [event["id"] for event in storage.pending_events("agent-a")] == [
        "event_a",
        "event_b",
    ]


def test_init_migrates_old_pending_share_table(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE pending_shares (
              id TEXT PRIMARY KEY, agent_id TEXT, user_id TEXT, content TEXT,
              reason TEXT, share_mode TEXT, urgency REAL, relevance REAL,
              novelty REAL, status TEXT, source_refs_json TEXT,
              created_at TEXT, expires_at TEXT
            )
            """
        )

    Storage(path).init_db()

    with sqlite3.connect(path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(pending_shares)")
        }
    assert {"decision_status", "defer_count", "last_surfaced_at"} <= columns
