from __future__ import annotations

from innerlife.digest import DigestEngine
from innerlife.llm import FakeBackend
from innerlife.storage import Storage


def test_state_and_history_survive_reopen(storage):
    storage.submit_event(
        "agent-a",
        "afterthought",
        "session-a",
        {"text": "重启不能改变连续性"},
        event_id="restart_source",
    )
    response = {
        "changed": True,
        "reason": "形成稳定理解",
        "internal_events": [
            {
                "event_type": "new_insight",
                "content": "连续性依赖保存下来的状态和历史",
                "source_refs": ["restart_source"],
            }
        ],
        "state_update": {"recent_focus": "重启后的连续性"},
        "pending_shares": [],
    }
    DigestEngine(storage, FakeBackend(response=response)).run("agent-a")
    expected = storage.get_agent("agent-a")

    reopened = Storage(storage.db_path)
    assert reopened.get_agent("agent-a") == expected
    assert reopened.recent_internal_events("agent-a")[0]["source_refs"] == [
        "restart_source"
    ]
