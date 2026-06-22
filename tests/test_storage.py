from __future__ import annotations

from innerlife.models import NotFoundError
from innerlife.storage import Storage

from conftest import load_profile


def test_init_is_idempotent_and_agents_are_isolated(tmp_path):
    store = Storage(tmp_path / "db.sqlite")
    store.init_db()
    store.init_db()
    store.create_agent(load_profile("clara"))
    store.create_agent(load_profile("lara"))

    store.submit_event(
        "clara",
        "afterthought",
        "session-a",
        {"text": "Clara private"},
        event_id="private_clara",
    )

    assert [event["id"] for event in store.pending_events("clara")] == [
        "private_clara"
    ]
    assert store.pending_events("lara") == []
    try:
        store.get_inbox_event("private_clara", "lara")
    except NotFoundError:
        pass
    else:
        raise AssertionError("Lara could read Clara's event")


def test_pending_events_have_stable_order(storage):
    timestamp = "2026-06-22T00:00:00+00:00"
    storage.submit_event(
        "clara",
        "afterthought",
        "session-b",
        {"text": "second by id"},
        event_id="event_b",
        created_at=timestamp,
    )
    storage.submit_event(
        "clara",
        "afterthought",
        "session-a",
        {"text": "first by id"},
        event_id="event_a",
        created_at=timestamp,
    )

    assert [event["id"] for event in storage.pending_events("clara")] == [
        "event_a",
        "event_b",
    ]
