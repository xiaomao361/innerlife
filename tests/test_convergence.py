from __future__ import annotations

from innerlife.config import Settings
from innerlife.convergence import ConvergenceEngine
from innerlife.llm import FakeBackend
from innerlife.models import ValidationError
from innerlife.service import get_briefing
from innerlife.storage import new_id, utc_now
from innerlife.digest import DigestEngine

import pytest


def configure_small_policy(storage):
    agent = storage.get_agent("agent-a")
    profile = agent["profile"]
    profile["convergence"] = {
        "enabled": True,
        "max_active_internal_events": 2,
        "max_active_experiences": 1,
        "max_active_open_loops": 1,
        "min_interval_hours": 0,
        "max_archive_events_per_run": 20,
        "max_archive_experiences_per_run": 10,
    }
    storage.create_agent(profile)


def seed_internal_events(storage, count=4):
    ids = []
    with storage.transaction() as conn:
        for index in range(count):
            event_id = f"internal_seed_{index}"
            ids.append(event_id)
            conn.execute(
                """
                INSERT INTO internal_events(
                  id, agent_id, event_type, content, source,
                  source_refs_json, metadata_json, fingerprint, created_at
                ) VALUES (?, 'agent-a', 'new_insight', ?, 'digest',
                  '["seed"]', '{}', ?, ?)
                """,
                (event_id, f"旧理解 {index}", f"fingerprint-{index}", utc_now()),
            )
    return ids


def seed_experiences(storage, count=3):
    ids = []
    for index in range(count):
        run_id = f"explore_seed_{index}"
        storage.record_exploration_run(
            run_id=run_id,
            agent_id="agent-a",
            status="processing",
            candidate_count=1,
            result={},
        )
        experience_id = f"experience_seed_{index}"
        ids.append(experience_id)
        storage.save_autonomous_experience(
            experience_id=experience_id,
            agent_id="agent-a",
            run_id=run_id,
            source_name="Test",
            title=f"旧经历 {index}",
            url=f"https://example.com/{index}",
            published_at=None,
            fetched_at=utc_now(),
            content_fingerprint=f"experience-fingerprint-{index}",
            evidence={"text_excerpt": f"evidence {index}"},
            experience={
                "experience_summary": f"经历摘要 {index}",
                "why_it_mattered": "测试收敛",
                "new_questions": [],
            },
        )
    return ids


def settings_for(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("INNERLIFE_DB_PATH", str(storage.db_path))
    monkeypatch.setenv("INNERLIFE_ROOT", str(tmp_path))
    monkeypatch.setenv("INNERLIFE_LLM_BACKEND", "fake")
    return Settings.from_env()


def test_convergence_archives_old_content_and_keeps_summary(
    storage, tmp_path, monkeypatch
):
    configure_small_policy(storage)
    seed_internal_events(storage, 4)
    seed_experiences(storage, 3)

    def responder(payload):
        events = payload["archive_candidates"]["internal_events"]
        experiences = payload["archive_candidates"]["autonomous_experiences"]
        refs = [item["id"] for item in events + experiences]
        return {
            "changed": True,
            "reason": "旧内容已经形成稳定认识",
            "summary": {
                "title": "有来源的持续理解",
                "content": "多次经历共同说明，内部变化需要真实来源并保持克制。",
                "source_refs": refs,
            },
            "archive_internal_event_ids": [item["id"] for item in events],
            "archive_experience_ids": [item["id"] for item in experiences],
            "dormant_loop_ids": [],
            "resolved_loop_ids": [],
        }

    result = ConvergenceEngine(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=responder),
    ).run("agent-a")

    assert result["changed"] is True
    assert result["pressure_after"]["active_internal_events"] == 2
    assert result["pressure_after"]["active_experiences"] == 1
    assert len(storage.list_inner_summaries("agent-a")) == 1
    assert len(storage.recent_internal_events("agent-a", 20)) == 2
    assert len(storage.recent_internal_events("agent-a", 20, True)) == 4
    assert len(storage.list_autonomous_experiences("agent-a", 20)) == 1
    assert len(storage.list_autonomous_experiences("agent-a", 20, True)) == 3
    briefing = get_briefing(storage, "agent-a")
    assert len(briefing["recent_internal_events"]) == 2
    assert len(briefing["recent_autonomous_experiences"]) == 1
    assert briefing["stable_summaries"][0]["title"] == "有来源的持续理解"


def test_convergence_cannot_archive_protected_recent_content(
    storage, tmp_path, monkeypatch
):
    configure_small_policy(storage)
    seed_internal_events(storage, 4)

    def responder(payload):
        protected = payload["protected_recent"]["internal_event_ids"][0]
        return {
            "changed": True,
            "reason": "错误选择最新内容",
            "summary": {
                "title": "错误摘要",
                "content": "不应成功",
                "source_refs": [protected],
            },
            "archive_internal_event_ids": [protected],
            "archive_experience_ids": [],
            "dormant_loop_ids": [],
            "resolved_loop_ids": [],
        }

    with pytest.raises(ValidationError, match="protected"):
        ConvergenceEngine(
            storage,
            settings_for(storage, tmp_path, monkeypatch),
            FakeBackend(responder=responder),
        ).run("agent-a")

    assert storage.convergence_pressure("agent-a")["active_internal_events"] == 4
    assert storage.list_convergence_runs("agent-a")[0]["status"] == "failed"


def test_convergence_can_cool_open_loop_out_of_briefing(
    storage, tmp_path, monkeypatch
):
    configure_small_policy(storage)
    agent = storage.get_agent("agent-a")
    state = agent["state"]
    state["open_loops"] = [
        {"id": "loop-old", "content": "很久未推进的问题", "source_refs": ["seed"], "status": "open"},
        {"id": "loop-new", "content": "当前问题", "source_refs": ["seed"], "status": "open"},
    ]
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE agent_state SET state_json=? WHERE agent_id='agent-a'",
            (__import__("json").dumps(state, ensure_ascii=False),),
        )

    backend = FakeBackend(
        response={
            "changed": True,
            "reason": "旧问题暂时降温",
            "summary": None,
            "archive_internal_event_ids": [],
            "archive_experience_ids": [],
            "dormant_loop_ids": ["loop-old"],
            "resolved_loop_ids": [],
        }
    )
    ConvergenceEngine(
        storage, settings_for(storage, tmp_path, monkeypatch), backend
    ).run("agent-a")

    assert [loop["id"] for loop in get_briefing(storage, "agent-a")["open_loops"]] == [
        "loop-new"
    ]
    all_loops = storage.get_agent("agent-a")["state"]["open_loops"]
    assert next(loop for loop in all_loops if loop["id"] == "loop-old")["status"] == "dormant"

    seen = {}

    def inspect(payload):
        seen.update(payload)
        return {
            "changed": False,
            "reason": "没有新输入",
            "internal_events": [],
            "state_update": {},
            "pending_shares": [],
        }

    DigestEngine(storage, FakeBackend(responder=inspect)).run("agent-a")
    assert [loop["id"] for loop in seen["state"]["open_loops"]] == ["loop-new"]


def test_convergence_within_limits_does_not_call_model(
    storage, tmp_path, monkeypatch
):
    configure_small_policy(storage)
    engine = ConvergenceEngine(
        storage,
        settings_for(storage, tmp_path, monkeypatch),
        FakeBackend(responder=lambda _: (_ for _ in ()).throw(AssertionError())),
    )

    result = engine.run("agent-a")

    assert result["changed"] is False
    assert "阈值内" in result["reason"]
