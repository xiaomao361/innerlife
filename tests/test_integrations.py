from __future__ import annotations

import sqlite3

from innerlife.integrations import sync_continuity, sync_memoria


def test_memoria_sync_is_idempotent(storage, tmp_path):
    path = tmp_path / "memoria.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE memories (
              id TEXT PRIMARY KEY, summary TEXT, content TEXT, source TEXT,
              source_agent TEXT, created_at TEXT, updated_at TEXT,
              archived INTEGER, status TEXT, kind TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO memories VALUES (
              'm1', '摘要', '用户明确选择本地模型', 'test', 'codex',
              '2026-06-22T00:00:00+00:00', '2026-06-22T00:00:00+00:00',
              0, 'active', 'fact'
            )
            """
        )
    first = sync_memoria(storage, path, "agent-a")
    second = sync_memoria(storage, path, "agent-a")
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert storage.pending_events("agent-a")[0]["source_type"] == "memoria_fact"


def test_continuity_sync_preserves_position_boundary(storage, tmp_path):
    path = tmp_path / "continuity.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE session_threads (
              thread_id TEXT PRIMARY KEY, version INTEGER, topic TEXT, status TEXT,
              last_active_at TEXT, last_position TEXT, next_step TEXT,
              state_summary TEXT, agent_id TEXT, facts_used TEXT,
              current_interpretation TEXT, interpretation_status TEXT,
              user_confirmed INTEGER, reality_line TEXT, entry_posture TEXT,
              confirmed_ground TEXT, provisional_read TEXT, boundary_notes TEXT,
              misread_risks TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO session_threads VALUES (
              't1', 1, 'InnerLife', 'active', '2026-06-22T00:00:00+00:00',
              '正在从核心验证升级到可用系统', '接入 MCP', '边界保持清楚',
              'agent-a', '[]', '这是当前位置', 'active', 0,
              '共同建设可用系统', '直接但谨慎', '内外边界明确',
              '仍需验证长期运行', '不要把位置当事实', '不要假装已经成熟'
            )
            """
        )
    result = sync_continuity(storage, path, "agent-a")
    assert result["imported"] == 1
    event = storage.pending_events("agent-a")[0]
    assert event["source_type"] == "continuity_position"
    assert event["content"]["current_interpretation"] == "这是当前位置"
