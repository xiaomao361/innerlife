from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .storage import Storage


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def sync_memoria(
    storage: Storage,
    memoria_db: Path,
    agent_id: str,
    *,
    limit: int = 100,
    bootstrap_from_now: bool = False,
) -> dict[str, Any]:
    if not memoria_db.exists():
        return {"source": "memoria", "agent_id": agent_id, "imported": 0, "missing": True}
    cursor_key = f"sync.memoria.{agent_id}"
    cursor = storage.get_service_state(cursor_key)
    if cursor is None and bootstrap_from_now:
        with _connect(memoria_db) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(COALESCE(updated_at, created_at)), '') value FROM memories"
            ).fetchone()
        storage.set_service_state(cursor_key, row["value"])
        return {
            "source": "memoria",
            "agent_id": agent_id,
            "imported": 0,
            "bootstrapped": True,
        }
    cursor = cursor or ""
    with _connect(memoria_db) as conn:
        rows = conn.execute(
            """
            SELECT id, summary, content, source, source_agent, created_at,
                   COALESCE(updated_at, created_at) cursor_time
            FROM memories
            WHERE archived = 0
              AND status = 'active'
              AND kind = 'fact'
              AND COALESCE(updated_at, created_at) > ?
            ORDER BY COALESCE(updated_at, created_at), id
            LIMIT ?
            """,
            (cursor, limit),
        ).fetchall()
    imported = 0
    newest = cursor
    for row in rows:
        event_id = f"memoria_{agent_id}_{row['id']}"
        storage.submit_event(
            agent_id,
            "memoria_fact",
            row["id"],
            {
                "memory_id": row["id"],
                "summary": row["summary"],
                "text": row["content"],
                "source": row["source"],
                "source_agent": row["source_agent"],
                "observed_at": row["created_at"],
            },
            event_id=event_id,
            created_at=row["cursor_time"],
        )
        imported += 1
        newest = row["cursor_time"]
    if rows:
        storage.set_service_state(cursor_key, newest)
    return {
        "source": "memoria",
        "agent_id": agent_id,
        "imported": imported,
        "cursor": newest,
    }


def sync_continuity(
    storage: Storage,
    continuity_db: Path,
    agent_id: str,
    *,
    limit: int = 50,
    bootstrap_from_now: bool = False,
) -> dict[str, Any]:
    if not continuity_db.exists():
        return {
            "source": "continuity",
            "agent_id": agent_id,
            "imported": 0,
            "missing": True,
        }
    cursor_key = f"sync.continuity.{agent_id}"
    cursor = storage.get_service_state(cursor_key)
    if cursor is None and bootstrap_from_now:
        with _connect(continuity_db) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(last_active_at), '') value FROM session_threads WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        storage.set_service_state(cursor_key, row["value"])
        return {
            "source": "continuity",
            "agent_id": agent_id,
            "imported": 0,
            "bootstrapped": True,
        }
    cursor = cursor or ""
    with _connect(continuity_db) as conn:
        rows = conn.execute(
            """
            SELECT * FROM session_threads
            WHERE agent_id = ? AND status = 'active' AND last_active_at > ?
            ORDER BY last_active_at, thread_id
            LIMIT ?
            """,
            (agent_id, cursor, limit),
        ).fetchall()
    imported = 0
    newest = cursor
    for row in rows:
        event_id = f"continuity_{agent_id}_{row['thread_id']}_{row['version']}"
        storage.submit_event(
            agent_id,
            "continuity_position",
            row["thread_id"],
            {
                "thread_id": row["thread_id"],
                "topic": row["topic"],
                "last_position": row["last_position"],
                "next_step": row["next_step"],
                "state_summary": row["state_summary"],
                "current_interpretation": row["current_interpretation"],
                "interpretation_status": row["interpretation_status"],
                "user_confirmed": bool(row["user_confirmed"]),
                "reality_line": row["reality_line"],
                "entry_posture": row["entry_posture"],
                "confirmed_ground": row["confirmed_ground"],
                "provisional_read": row["provisional_read"],
                "boundary_notes": row["boundary_notes"],
                "misread_risks": row["misread_risks"],
                "facts_used": json.loads(row["facts_used"] or "[]"),
            },
            event_id=event_id,
            created_at=row["last_active_at"],
        )
        imported += 1
        newest = row["last_active_at"]
    if rows:
        storage.set_service_state(cursor_key, newest)
    return {
        "source": "continuity",
        "agent_id": agent_id,
        "imported": imported,
        "cursor": newest,
    }
