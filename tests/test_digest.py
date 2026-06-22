from __future__ import annotations

import pytest

from innerlife.digest import DigestEngine
from innerlife.llm import FakeBackend
from innerlife.models import ValidationError


def test_no_change_is_recorded_without_changing_revision(storage):
    before = storage.get_agent("clara")
    result = DigestEngine(
        storage,
        FakeBackend(
            response={
                "changed": False,
                "reason": "没有新材料",
                "internal_events": [],
                "state_update": {},
                "pending_shares": [],
            }
        ),
    ).run("clara")

    after = storage.get_agent("clara")
    assert result.changed is False
    assert after["revision"] == before["revision"]
    runs = storage.digest_runs("clara")
    assert runs[0]["changed"] is False
    assert runs[0]["status"] == "completed"


def test_success_is_atomic_and_consumes_inputs(storage):
    storage.submit_event(
        "clara",
        "afterthought",
        "session-a",
        {"text": "怎样判断内部变化"},
        event_id="source_1",
    )
    response = {
        "changed": True,
        "reason": "形成一个新问题",
        "internal_events": [
            {
                "event_type": "new_question",
                "content": "怎样判断内部变化是否有真实来源",
                "source_refs": ["source_1"],
            }
        ],
        "state_update": {
            "open_loops": [
                {
                    "content": "怎样判断内部变化是否有真实来源",
                    "source_refs": ["source_1"],
                }
            ]
        },
        "pending_shares": [],
    }
    result = DigestEngine(storage, FakeBackend(response=response)).run("clara")

    assert result.changed is True
    assert storage.pending_events("clara") == []
    assert len(storage.recent_internal_events("clara")) == 1
    assert len(storage.get_agent("clara")["state"]["open_loops"]) == 1


def test_invalid_output_does_not_consume_input_or_update_state(storage):
    storage.submit_event(
        "clara",
        "afterthought",
        "session-a",
        {"text": "测试失败路径"},
        event_id="source_fail",
    )
    before = storage.get_agent("clara")
    response = {
        "changed": True,
        "reason": "无来源变化",
        "internal_events": [
            {
                "event_type": "new_question",
                "content": "这是一个无来源问题",
                "source_refs": ["not_available"],
            }
        ],
        "state_update": {},
        "pending_shares": [],
    }
    with pytest.raises(ValidationError):
        DigestEngine(storage, FakeBackend(response=response)).run("clara")

    assert [event["id"] for event in storage.pending_events("clara")] == [
        "source_fail"
    ]
    assert storage.get_agent("clara")["state"] == before["state"]
    assert storage.digest_runs("clara")[0]["status"] == "failed"


def test_duplicate_change_is_downgraded_to_no_change(storage):
    first = {
        "changed": True,
        "reason": "第一次形成",
        "internal_events": [
            {
                "event_type": "new_insight",
                "content": "每次变化都必须有来源",
                "source_refs": ["repeat_a"],
            }
        ],
        "state_update": {"recent_focus": "变化来源"},
        "pending_shares": [],
    }
    storage.submit_event(
        "clara",
        "afterthought",
        "session-a",
        {"text": "变化来源"},
        event_id="repeat_a",
    )
    DigestEngine(storage, FakeBackend(response=first)).run("clara")

    storage.submit_event(
        "clara",
        "afterthought",
        "session-b",
        {"text": "还是变化来源"},
        event_id="repeat_b",
    )
    second = dict(first)
    second["reason"] = "第二次形成"
    second["internal_events"] = [
        {
            "event_type": "new_insight",
            "content": "每次变化都必须有来源",
            "source_refs": ["repeat_b"],
        }
    ]
    result = DigestEngine(storage, FakeBackend(response=second)).run("clara")

    assert result.changed is False
    assert len(storage.recent_internal_events("clara")) == 1
    assert storage.pending_events("clara") == []
