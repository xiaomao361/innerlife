from __future__ import annotations

from datetime import datetime, timedelta, timezone

from innerlife.config import Settings
from innerlife.digest import DigestEngine
from innerlife.llm import FakeBackend
from innerlife.session import SessionLifecycle
from innerlife.sharing import ShareScheduler


def settings_for(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    monkeypatch.setenv("INNERLIFE_LLM_BACKEND", "fake")
    return Settings.from_env()


def create_share(storage, mode="when_relevant", expires_at=None, suffix="one"):
    event_id = f"share_source_{suffix}"
    storage.submit_event(
        "agent-a",
        "afterthought",
        f"session-{suffix}",
        {"text": f"待分享来源 {suffix}"},
        event_id=event_id,
    )
    response = {
        "changed": True,
        "reason": "形成了一个可分享的新想法",
        "internal_events": [
            {
                "event_type": "share_desire",
                "content": f"我想进一步讨论 {suffix}",
                "source_refs": [event_id],
            }
        ],
        "state_update": {"recent_focus": f"分享时机 {suffix}"},
        "pending_shares": [
            {
                "user_id": "user-1",
                "content": f"有一件关于 {suffix} 的事，我想找合适时机聊聊。",
                "reason": "它可能值得继续讨论",
                "share_mode": mode,
                "urgency": 0.3,
                "relevance": 0.7,
                "novelty": 0.6,
                "source_refs": [event_id],
                "expires_at": expires_at,
            }
        ],
    }
    DigestEngine(storage, FakeBackend(response=response)).run("agent-a")
    return storage.pending_shares("agent-a")[-1]


def test_session_start_can_surface_mature_proactive_share(
    storage, tmp_path, monkeypatch
):
    share = create_share(storage, "proactive_allowed")
    old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE pending_shares SET created_at=? WHERE id=?",
            (old, share["id"]),
        )

    def responder(payload):
        if "candidate_shares" in payload:
            candidate = payload["candidate_shares"][0]
            return {
                "selected": True,
                "share_id": candidate["id"],
                "decision": "share_now",
                "delivery_style": "proactive",
                "reason": "已经等待足够久，适合在新会话主动开启一次",
                "suggested_opening": "我有件之前一直想找机会聊的事。",
            }
        raise AssertionError("unexpected model call")

    started = SessionLifecycle(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=responder),
    ).start(
        agent_id="agent-a",
        user_id="user-1",
        host="test",
        external_session_id="proactive",
    )

    plan = started["briefing"]["share_plan"]
    assert plan["selected"] is True
    assert plan["delivery_style"] == "proactive"
    assert plan["share"]["id"] == share["id"]
    assert storage.get_share(share["id"], "agent-a")["surface_count"] == 1


def test_share_check_can_surface_relevant_share_during_active_session(
    storage, tmp_path, monkeypatch
):
    share = create_share(storage, "when_relevant")

    def responder(payload):
        if "candidate_shares" in payload and payload["conversation_context"] is None:
            return {
                "selected": False,
                "decision": "wait",
                "reason": "会话开始时没有上下文",
            }
        if "candidate_shares" in payload:
            return {
                "selected": True,
                "share_id": share["id"],
                "decision": "share_now",
                "delivery_style": "natural",
                "reason": "当前正在讨论相同问题",
                "suggested_opening": "这正好和我之前留下的一个想法有关。",
            }
        raise AssertionError("unexpected model call")

    lifecycle = SessionLifecycle(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=responder),
    )
    started = lifecycle.start(
        agent_id="agent-a",
        user_id="user-1",
        host="test",
        external_session_id="relevant",
    )
    result = lifecycle.check_shares(
        session_id=started["session"]["id"],
        agent_id="agent-a",
        conversation_context={"summary": "正在讨论分享时机 one"},
    )

    assert result["selected"] is True
    assert result["delivery_style"] == "natural"


def test_deferred_share_remains_pending_and_increments_count(storage):
    share = create_share(storage)

    result = storage.update_share_status(
        share["id"], "agent-a", "deferred", "当前不适合打断"
    )

    assert result["status"] == "pending"
    assert result["defer_count"] == 1
    assert result["last_outcome"] == "deferred"
    assert [item["id"] for item in storage.pending_shares("agent-a")] == [
        share["id"]
    ]


def test_used_share_leaves_pending_queue_and_records_action(storage):
    share = create_share(storage)

    result = storage.update_share_status(
        share["id"], "agent-a", "used", "已经自然说出"
    )

    assert result["status"] == "used"
    assert storage.pending_shares("agent-a") == []
    assert storage.share_actions("agent-a", share["id"])[0]["action"] == "used"


def test_expired_share_is_discarded_without_model_call(
    storage, tmp_path, monkeypatch
):
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    share = create_share(storage, expires_at=expired)

    result = ShareScheduler(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=lambda _: (_ for _ in ()).throw(AssertionError())),
    ).check(agent_id="agent-a", user_id="user-1")

    assert result["selected"] is False
    assert storage.get_share(share["id"], "agent-a")["status"] == "discarded"


def test_daily_proactive_limit_prevents_second_opener(
    storage, tmp_path, monkeypatch
):
    first = create_share(storage, "proactive_allowed", suffix="first")
    second = create_share(storage, "proactive_allowed", suffix="second")
    old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE pending_shares SET created_at=? WHERE id IN (?,?)",
            (old, first["id"], second["id"]),
        )

    calls = {"count": 0}

    def responder(payload):
        calls["count"] += 1
        candidate = payload["candidate_shares"][0]
        return {
            "selected": True,
            "share_id": candidate["id"],
            "decision": "share_now",
            "delivery_style": "proactive",
            "reason": "选择一条主动开启",
            "suggested_opening": "我想主动聊一件事。",
        }

    scheduler = ShareScheduler(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=responder),
    )
    first_result = scheduler.check(agent_id="agent-a", user_id="user-1")
    second_result = scheduler.check(agent_id="agent-a", user_id="user-1")

    assert first_result["selected"] is True
    assert second_result["selected"] is False
    assert calls["count"] == 1
