from __future__ import annotations

import pytest

from innerlife.evaluator import evaluate_output
from innerlife.models import ValidationError

from conftest import load_profile


def evaluate(output, allowed=None, recent=None):
    return evaluate_output(
        raw_output=output,
        agent_id="agent-a",
        profile=load_profile("agent-a"),
        state_before={
            "current_interests": [],
            "open_loops": [],
            "recent_mood": None,
            "recent_focus": None,
        },
        allowed_refs=set(allowed or {"source_1"}),
        recent_internal_events=recent or [],
    )


def valid_output(content="一个有来源的新问题", refs=None):
    return {
        "changed": True,
        "reason": "形成新问题",
        "internal_events": [
            {
                "event_type": "new_question",
                "content": content,
                "source_refs": refs or ["source_1"],
            }
        ],
        "state_update": {},
        "pending_shares": [],
    }


def test_rejects_reality_claim():
    with pytest.raises(ValidationError, match="reality claim"):
        evaluate(valid_output("我今天去散步时想明白了"))


def test_rejects_cross_agent_or_unknown_source():
    with pytest.raises(ValidationError, match="unavailable source ref"):
        evaluate(valid_output(refs=["agent-b_private"]), allowed={"source_1"})


def test_rejects_share_that_copies_internal_event():
    output = valid_output("我在想如何保持安静")
    output["pending_shares"] = [
        {
            "content": "我在想如何保持安静",
            "source_refs": ["source_1"],
            "share_mode": "when_relevant",
        }
    ]
    with pytest.raises(ValidationError, match="must not copy"):
        evaluate(output)


def test_changed_false_must_be_empty():
    output = {
        "changed": False,
        "reason": "没有变化",
        "internal_events": [],
        "state_update": {"recent_focus": "不应更新"},
        "pending_shares": [],
    }
    with pytest.raises(ValidationError, match="changed=false"):
        evaluate(output)


def test_changed_false_accepts_null_empty_fields_from_real_models():
    output = {
        "changed": False,
        "reason": "没有变化",
        "internal_events": None,
        "state_update": None,
        "pending_shares": None,
    }
    normalized, state = evaluate(output)
    assert normalized["changed"] is False
    assert normalized["internal_events"] == []
    assert normalized["state_update"] == {}
    assert normalized["pending_shares"] == []
    assert state["open_loops"] == []
