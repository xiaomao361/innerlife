from __future__ import annotations

import pytest

from innerlife.config import Settings
from innerlife.llm import FakeBackend
from innerlife.models import ModelError
from innerlife.models import ValidationError
from innerlife.session import SessionLifecycle


def test_two_session_closed_loop(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()

    def responder(payload):
        if "conversation" in payload:
            return {
                "has_afterthought": True,
                "reason": "这轮留下了一个此前没有的问题",
                "conversation_summary": "讨论如何让内部生活形成闭环",
                "agent_afterthought": "我还没有想清楚怎样判断第二次会话真的接上了第一次",
                "open_loops": ["怎样验证跨会话接续不是摘要复述"],
            }
        source_id = payload["pending_inbox_events"][0]["id"]
        return {
            "changed": True,
            "reason": "会话余韵形成了一个长期未完成问题",
            "internal_events": [
                {
                    "event_type": "new_question",
                    "content": "怎样验证跨会话接续不是摘要复述",
                    "source_refs": [source_id],
                }
            ],
            "state_update": {
                "open_loops": [
                    {
                        "content": "怎样验证跨会话接续不是摘要复述",
                        "source_refs": [source_id],
                    }
                ]
            },
            "pending_shares": [],
        }

    lifecycle = SessionLifecycle(storage, settings, FakeBackend(responder=responder))
    first = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="closed-loop-test",
        external_session_id="first",
    )
    ended = lifecycle.end(
        session_id=first["session"]["id"],
        agent_id="agent-a",
        conversation={
            "messages": [
                {"role": "user", "content": "怎样才算闭环？"},
                {"role": "assistant", "content": "下一次应能接回未完成问题。"},
            ]
        },
    )
    assert ended["reflection"]["has_afterthought"] is True
    assert ended["digest"]["changed"] is True

    second = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="closed-loop-test",
        external_session_id="second",
    )
    briefing = second["briefing"]
    assert briefing["open_loops"][0]["content"] == "怎样验证跨会话接续不是摘要复述"
    assert briefing["recent_internal_events"][0]["source_refs"] == [
        f"afterthought_{first['session']['id']}"
    ]


def test_session_rejects_user_outside_agent_boundary(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    lifecycle = SessionLifecycle(storage, Settings.from_env(), FakeBackend())

    with pytest.raises(ValidationError, match="not allowed"):
        lifecycle.start(
            agent_id="agent-a",
            user_id="unknown-user",
            host="test",
            external_session_id="denied",
        )


def test_session_without_afterthought_creates_no_internal_change(
    storage, tmp_path, monkeypatch
):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()
    backend = FakeBackend(
        response={
            "has_afterthought": False,
            "reason": "只是完成了普通查询，没有内部变化",
            "conversation_summary": "查询了一个命令",
            "agent_afterthought": "",
            "open_loops": [],
        }
    )
    lifecycle = SessionLifecycle(storage, settings, backend)
    started = lifecycle.start(
        agent_id="agent-b", user_id="user-1", host="test", external_session_id="quiet"
    )
    ended = lifecycle.end(
        session_id=started["session"]["id"],
        agent_id="agent-b",
        conversation={"summary": "查询了当前时间"},
    )
    assert ended["reflection"]["has_afterthought"] is False
    assert ended["submitted_event"] is None
    assert storage.recent_internal_events("agent-b") == []
    assert storage.pending_events("agent-b") == []


def test_session_start_and_end_are_idempotent(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()
    backend = FakeBackend(
        response={
            "has_afterthought": False,
            "reason": "没有变化",
            "conversation_summary": "",
            "agent_afterthought": "",
            "open_loops": [],
        }
    )
    lifecycle = SessionLifecycle(storage, settings, backend)
    first = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="test",
        external_session_id="same",
    )
    same = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="test",
        external_session_id="same",
    )
    assert first["session"]["id"] == same["session"]["id"]
    ended = lifecycle.end(
        session_id=first["session"]["id"],
        agent_id="agent-a",
        conversation={"summary": "nothing"},
    )
    repeated = lifecycle.end(
        session_id=first["session"]["id"],
        agent_id="agent-a",
        conversation={"summary": "nothing"},
    )
    assert ended["idempotent"] is False
    assert repeated["idempotent"] is True


def test_unanswered_meaningful_question_can_be_afterthought(
    storage, tmp_path, monkeypatch
):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()
    backend = FakeBackend(
        response={
            "has_afterthought": True,
            "reason": "未回答问题进入了 Agent 自己的持续关注",
            "conversation_summary": "用户追问如何判断跨会话接续是否真实",
            "agent_afterthought": "我需要继续想清楚接续与摘要复述的区别",
            "open_loops": ["如何验证接续不是摘要复述"],
        }
    )
    lifecycle = SessionLifecycle(storage, settings, backend)
    started = lifecycle.start(
        agent_id="agent-a", user_id="user-1", host="test", external_session_id="open"
    )
    ended = lifecycle.end(
        session_id=started["session"]["id"],
        agent_id="agent-a",
        conversation={
            "messages": [
                {"role": "user", "content": "怎么判断它不是复述？"}
            ]
        },
        process_now=False,
    )
    assert ended["reflection"]["has_afterthought"] is True
    assert storage.pending_events("agent-a")[0]["content"]["open_loops"] == [
        "如何验证接续不是摘要复述"
    ]


def test_session_reflection_retries_once_on_bad_model_output(
    storage, tmp_path, monkeypatch
):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()
    calls = {"count": 0}

    def responder(payload):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ModelError("invalid output")
        return {
            "has_afterthought": False,
            "reason": "普通查询没有余韵",
            "conversation_summary": "查询地址",
            "agent_afterthought": "",
            "open_loops": [],
        }

    lifecycle = SessionLifecycle(storage, settings, FakeBackend(responder=responder))
    started = lifecycle.start(
        agent_id="agent-b", user_id="user-1", host="test", external_session_id="retry"
    )
    ended = lifecycle.end(
        session_id=started["session"]["id"],
        agent_id="agent-b",
        conversation={"summary": "查询地址"},
    )
    assert calls["count"] == 2
    assert ended["reflection"]["has_afterthought"] is False


def test_session_end_reports_concurrent_state_change(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    settings = Settings.from_env()
    seen = {}

    def responder(payload):
        seen.update(payload)
        return {
            "has_afterthought": False,
            "reason": "当前会话没有额外变化",
            "conversation_summary": "",
            "agent_afterthought": "",
            "open_loops": [],
        }

    lifecycle = SessionLifecycle(storage, settings, FakeBackend(responder=responder))
    started = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="test",
        external_session_id="concurrent",
    )
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE agent_state SET revision = revision + 1 WHERE agent_id = 'agent-a'"
        )
    ended = lifecycle.end(
        session_id=started["session"]["id"],
        agent_id="agent-a",
        conversation={"summary": "并发会话测试"},
    )
    assert ended["state_changed_during_session"] is True
    assert seen["state_changed_during_session"] is True
