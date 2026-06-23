from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import DEFAULT_STATE, NotFoundError, ValidationError


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_profiles (
  agent_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  host TEXT,
  profile_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_state (
  agent_id TEXT PRIMARY KEY,
  state_json TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE TABLE IF NOT EXISTS inbox_events (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  content_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  processed_at TEXT,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_inbox_pending
ON inbox_events(agent_id, status, created_at, id);

CREATE TABLE IF NOT EXISTS internal_events (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  content TEXT NOT NULL,
  source TEXT NOT NULL,
  source_refs_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  fingerprint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_internal_recent
ON internal_events(agent_id, created_at, id);

CREATE TABLE IF NOT EXISTS pending_shares (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  content TEXT NOT NULL,
  reason TEXT,
  share_mode TEXT NOT NULL DEFAULT 'when_relevant',
  urgency REAL NOT NULL DEFAULT 0.0,
  relevance REAL NOT NULL DEFAULT 0.0,
  novelty REAL NOT NULL DEFAULT 0.0,
  status TEXT NOT NULL DEFAULT 'pending',
  source_refs_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT,
  decision_status TEXT NOT NULL DEFAULT 'waiting',
  decision_reason TEXT,
  defer_count INTEGER NOT NULL DEFAULT 0,
  surface_count INTEGER NOT NULL DEFAULT 0,
  last_evaluated_at TEXT,
  last_surfaced_at TEXT,
  last_outcome TEXT,
  updated_at TEXT,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE TABLE IF NOT EXISTS share_actions (
  id TEXT PRIMARY KEY,
  share_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  session_id TEXT,
  action TEXT NOT NULL,
  delivery_style TEXT,
  reason TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(share_id) REFERENCES pending_shares(id),
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_share_actions_agent_time
ON share_actions(agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS digest_runs (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  input_refs_json TEXT NOT NULL,
  changed INTEGER NOT NULL,
  reason TEXT,
  status TEXT NOT NULL,
  output_json TEXT NOT NULL,
  error TEXT,
  state_before_json TEXT NOT NULL,
  state_after_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE TABLE IF NOT EXISTS service_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  host TEXT NOT NULL,
  external_session_id TEXT,
  status TEXT NOT NULL,
  start_revision INTEGER NOT NULL,
  start_briefing_json TEXT NOT NULL,
  conversation_json TEXT,
  reflection_json TEXT,
  end_revision INTEGER,
  created_at TEXT NOT NULL,
  ended_at TEXT,
  UNIQUE(agent_id, host, external_session_id),
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_agent_created
ON sessions(agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS source_subscriptions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'rss',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(agent_id, url),
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE TABLE IF NOT EXISTS exploration_runs (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  status TEXT NOT NULL,
  selected_url TEXT,
  selection_reason TEXT,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  result_json TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id)
);

CREATE TABLE IF NOT EXISTS autonomous_experiences (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  source_name TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  published_at TEXT,
  fetched_at TEXT NOT NULL,
  content_fingerprint TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  experience_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(agent_id, content_fingerprint),
  FOREIGN KEY(agent_id) REFERENCES agent_profiles(agent_id),
  FOREIGN KEY(run_id) REFERENCES exploration_runs(id)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load(value: str) -> Any:
    return json.loads(value)


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> dict[str, Any]:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(pending_shares)").fetchall()
            }
            migrations = {
                "decision_status": "TEXT NOT NULL DEFAULT 'waiting'",
                "decision_reason": "TEXT",
                "defer_count": "INTEGER NOT NULL DEFAULT 0",
                "surface_count": "INTEGER NOT NULL DEFAULT 0",
                "last_evaluated_at": "TEXT",
                "last_surfaced_at": "TEXT",
                "last_outcome": "TEXT",
                "updated_at": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE pending_shares ADD COLUMN {name} {definition}"
                    )
        return {"db_path": str(self.db_path), "initialized": True}

    def create_agent(self, profile: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(profile.get("agent_id", "")).strip()
        display_name = str(profile.get("display_name", "")).strip()
        if not agent_id or not display_name:
            raise ValidationError("Profile requires agent_id and display_name")
        now = utc_now()
        initial_state = dict(DEFAULT_STATE)
        initial_state.update(profile.get("initial_state") or {})
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO agent_profiles(
                  agent_id, display_name, host, profile_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  host=excluded.host,
                  profile_json=excluded.profile_json,
                  updated_at=excluded.updated_at
                """,
                (
                    agent_id,
                    display_name,
                    profile.get("host"),
                    dump(profile),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_state(agent_id, state_json, revision, updated_at)
                VALUES (?, ?, 0, ?)
                """,
                (agent_id, dump(initial_state), now),
            )
            profile_sources = profile.get("autonomous_sources") or []
            profile_source_ids = {
                str(source.get("id", "")).strip()
                for source in profile_sources
                if str(source.get("id", "")).strip()
            }
            if profile_source_ids:
                placeholders = ",".join("?" for _ in profile_source_ids)
                conn.execute(
                    f"""
                    UPDATE source_subscriptions SET enabled=0, updated_at=?
                    WHERE agent_id=? AND id LIKE ?
                      AND id NOT IN ({placeholders})
                    """,
                    (
                        now,
                        agent_id,
                        f"{agent_id}-%",
                        *sorted(profile_source_ids),
                    ),
                )
            for source in profile_sources:
                source_url = str(source.get("url", "")).strip()
                source_name = str(source.get("name", "")).strip()
                if not source_url or not source_name:
                    continue
                source_id = str(source.get("id") or new_id("source"))
                conn.execute(
                    """
                    INSERT INTO source_subscriptions(
                      id, agent_id, name, url, source_type, enabled,
                      created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_id, url) DO UPDATE SET
                      name=excluded.name,
                      source_type=excluded.source_type,
                      enabled=excluded.enabled,
                      updated_at=excluded.updated_at
                    """,
                    (
                        source_id,
                        agent_id,
                        source_name,
                        source_url,
                        source.get("source_type", "rss"),
                        int(source.get("enabled", True)),
                        now,
                        now,
                    ),
                )
        return self.get_agent(agent_id)

    def _agent_exists(self, conn: sqlite3.Connection, agent_id: str) -> None:
        row = conn.execute(
            "SELECT 1 FROM agent_profiles WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown agent: {agent_id}")

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT p.profile_json, s.state_json, s.revision, s.updated_at
                FROM agent_profiles p
                JOIN agent_state s USING(agent_id)
                WHERE p.agent_id = ?
                """,
                (agent_id,),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown agent: {agent_id}")
        return {
            "profile": load(row["profile_json"]),
            "state": load(row["state_json"]),
            "revision": row["revision"],
            "updated_at": row["updated_at"],
        }

    def submit_event(
        self,
        agent_id: str,
        source_type: str,
        source_id: str | None,
        content: dict[str, Any],
        *,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        allowed = {
            "memoria_fact",
            "continuity_position",
            "afterthought",
            "autonomous_experience",
        }
        if source_type not in allowed:
            raise ValidationError(f"source_type must be one of {sorted(allowed)}")
        event_id = event_id or new_id("inbox")
        created_at = created_at or utc_now()
        try:
            return self.get_inbox_event(event_id, agent_id)
        except NotFoundError:
            pass
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            conn.execute(
                """
                INSERT INTO inbox_events(
                  id, agent_id, source_type, source_id, content_json,
                  status, created_at, processed_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)
                """,
                (
                    event_id,
                    agent_id,
                    source_type,
                    source_id,
                    dump(content),
                    created_at,
                ),
            )
        return self.get_inbox_event(event_id, agent_id)

    def get_inbox_event(self, event_id: str, agent_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM inbox_events WHERE id = ? AND agent_id = ?",
                (event_id, agent_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown inbox event for {agent_id}: {event_id}")
        return self._inbox_row(row)

    @staticmethod
    def _inbox_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "content": load(row["content_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "processed_at": row["processed_at"],
        }

    def pending_events(self, agent_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            rows = conn.execute(
                """
                SELECT * FROM inbox_events
                WHERE agent_id = ? AND status = 'pending'
                ORDER BY created_at ASC, id ASC
                """,
                (agent_id,),
            ).fetchall()
        return [self._inbox_row(row) for row in rows]

    def list_inbox(
        self, agent_id: str, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            if status:
                rows = conn.execute(
                    """
                    SELECT * FROM inbox_events
                    WHERE agent_id = ? AND status = ?
                    ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (agent_id, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM inbox_events
                    WHERE agent_id = ?
                    ORDER BY created_at DESC, id DESC LIMIT ?
                    """,
                    (agent_id, limit),
                ).fetchall()
        return [self._inbox_row(row) for row in rows]

    def recent_internal_events(
        self, agent_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            rows = conn.execute(
                """
                SELECT * FROM internal_events
                WHERE agent_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "event_type": row["event_type"],
                "content": row["content"],
                "source": row["source"],
                "source_refs": load(row["source_refs_json"]),
                "metadata": load(row["metadata_json"]),
                "fingerprint": row["fingerprint"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def pending_shares(self, agent_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            rows = conn.execute(
                """
                SELECT * FROM pending_shares
                WHERE agent_id = ? AND status = 'pending'
                ORDER BY created_at ASC, id ASC
                """,
                (agent_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "user_id": row["user_id"],
                "content": row["content"],
                "reason": row["reason"],
                "share_mode": row["share_mode"],
                "urgency": row["urgency"],
                "relevance": row["relevance"],
                "novelty": row["novelty"],
                "status": row["status"],
                "source_refs": load(row["source_refs_json"]),
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "decision_status": row["decision_status"],
                "decision_reason": row["decision_reason"],
                "defer_count": row["defer_count"],
                "surface_count": row["surface_count"],
                "last_evaluated_at": row["last_evaluated_at"],
                "last_surfaced_at": row["last_surfaced_at"],
                "last_outcome": row["last_outcome"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def digest_runs(self, agent_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            rows = conn.execute(
                """
                SELECT * FROM digest_runs WHERE agent_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (agent_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "mode": row["mode"],
                "input_refs": load(row["input_refs_json"]),
                "changed": bool(row["changed"]),
                "reason": row["reason"],
                "status": row["status"],
                "output": load(row["output_json"]),
                "error": row["error"],
                "state_before": load(row["state_before_json"]),
                "state_after": load(row["state_after_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_agents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.agent_id, p.display_name, s.revision, s.updated_at,
                       (SELECT COUNT(*) FROM inbox_events i
                        WHERE i.agent_id = p.agent_id AND i.status = 'pending') pending_count,
                       (SELECT COUNT(*) FROM pending_shares ps
                        WHERE ps.agent_id = p.agent_id AND ps.status = 'pending') share_count
                FROM agent_profiles p JOIN agent_state s USING(agent_id)
                ORDER BY p.agent_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            tables = [
                "agent_profiles",
                "inbox_events",
                "internal_events",
                "pending_shares",
                "digest_runs",
                "sessions",
                "source_subscriptions",
                "exploration_runs",
                "autonomous_experiences",
                "share_actions",
            ]
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
            counts["pending_inbox"] = conn.execute(
                "SELECT COUNT(*) FROM inbox_events WHERE status = 'pending'"
            ).fetchone()[0]
            counts["pending_shares"] = conn.execute(
                "SELECT COUNT(*) FROM pending_shares WHERE status = 'pending'"
            ).fetchone()[0]
        return {"db_path": str(self.db_path), **counts}

    def update_share_status(
        self, share_id: str, agent_id: str, status: str, reason: str | None = None
    ) -> dict[str, Any]:
        if status not in {"used", "deferred", "discarded"}:
            raise ValidationError("share status must be used, deferred or discarded")
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            row = conn.execute(
                "SELECT * FROM pending_shares WHERE id = ? AND agent_id = ?",
                (share_id, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Unknown pending share: {share_id}")
            stored_reason = reason or row["reason"]
            now = utc_now()
            persisted_status = "pending" if status == "deferred" else status
            decision_status = "waiting" if status == "deferred" else "closed"
            conn.execute(
                """
                UPDATE pending_shares
                SET status=?, reason=?, decision_status=?, decision_reason=?,
                    defer_count=defer_count + ?, last_outcome=?, updated_at=?
                WHERE id=? AND agent_id=?
                """,
                (
                    persisted_status,
                    stored_reason,
                    decision_status,
                    reason,
                    int(status == "deferred"),
                    status,
                    now,
                    share_id,
                    agent_id,
                ),
            )
            conn.execute(
                """
                INSERT INTO share_actions(
                  id, share_id, agent_id, action, reason, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, '{}', ?)
                """,
                (new_id("share_action"), share_id, agent_id, status, reason, now),
            )
        return self.get_share(share_id, agent_id)

    def get_share(self, share_id: str, agent_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pending_shares WHERE id=? AND agent_id=?",
                (share_id, agent_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown pending share: {share_id}")
        result = dict(row)
        result["source_refs"] = load(result.pop("source_refs_json"))
        return result

    def evaluate_share(
        self,
        *,
        share_id: str,
        agent_id: str,
        decision: str,
        reason: str,
        session_id: str | None = None,
        delivery_style: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if decision not in {"share_now", "wait", "discard"}:
            raise ValidationError("share decision must be share_now, wait or discard")
        now = utc_now()
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            row = conn.execute(
                "SELECT * FROM pending_shares WHERE id=? AND agent_id=?",
                (share_id, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Unknown pending share: {share_id}")
            if row["status"] != "pending":
                raise ValidationError(f"Share is no longer pending: {share_id}")
            if decision == "discard":
                conn.execute(
                    """
                    UPDATE pending_shares
                    SET status='discarded', decision_status='closed',
                        decision_reason=?, last_evaluated_at=?,
                        last_outcome='discarded', updated_at=?
                    WHERE id=?
                    """,
                    (reason, now, now, share_id),
                )
            elif decision == "share_now":
                conn.execute(
                    """
                    UPDATE pending_shares
                    SET decision_status='surfaced', decision_reason=?,
                        surface_count=surface_count + 1,
                        last_evaluated_at=?, last_surfaced_at=?,
                        last_outcome='surfaced', updated_at=?
                    WHERE id=?
                    """,
                    (reason, now, now, now, share_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE pending_shares
                    SET decision_status='waiting', decision_reason=?,
                        last_evaluated_at=?, last_outcome='wait', updated_at=?
                    WHERE id=?
                    """,
                    (reason, now, now, share_id),
                )
            conn.execute(
                """
                INSERT INTO share_actions(
                  id, share_id, agent_id, session_id, action, delivery_style,
                  reason, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("share_action"),
                    share_id,
                    agent_id,
                    session_id,
                    decision,
                    delivery_style,
                    reason,
                    dump(metadata or {}),
                    now,
                ),
            )
        return self.get_share(share_id, agent_id)

    def share_actions(
        self, agent_id: str, share_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            if share_id:
                rows = conn.execute(
                    """
                    SELECT * FROM share_actions
                    WHERE agent_id=? AND share_id=?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (agent_id, share_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM share_actions
                    WHERE agent_id=? ORDER BY created_at DESC LIMIT ?
                    """,
                    (agent_id, limit),
                ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["metadata"] = load(item.pop("metadata_json"))
            results.append(item)
        return results

    def proactive_share_count_since(self, agent_id: str, since: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM share_actions
                    WHERE agent_id=? AND action='share_now'
                      AND delivery_style='proactive' AND created_at>=?
                    """,
                    (agent_id, since),
                ).fetchone()[0]
            )

    def expire_pending_shares(self, agent_id: str, now: str | None = None) -> int:
        now = now or utc_now()
        with self.transaction() as conn:
            rows = conn.execute(
                """
                SELECT id FROM pending_shares
                WHERE agent_id=? AND status='pending'
                  AND expires_at IS NOT NULL AND expires_at<=?
                """,
                (agent_id, now),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    UPDATE pending_shares
                    SET status='discarded', decision_status='closed',
                        decision_reason='expired', last_outcome='discarded',
                        updated_at=?
                    WHERE id=?
                    """,
                    (now, row["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO share_actions(
                      id, share_id, agent_id, action, reason,
                      metadata_json, created_at
                    ) VALUES (?, ?, ?, 'discarded', 'expired', '{}', ?)
                    """,
                    (new_id("share_action"), row["id"], agent_id, now),
                )
        return len(rows)

    def get_service_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM service_state WHERE key = ?", (key,)
            ).fetchone()
        return default if row is None else load(row["value_json"])

    def set_service_state(self, key: str, value: Any) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO service_state(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  updated_at=excluded.updated_at
                """,
                (key, dump(value), utc_now()),
            )

    def latest_digest(self, agent_id: str) -> dict[str, Any] | None:
        runs = self.digest_runs(agent_id)
        return runs[0] if runs else None

    def backup(self, destination: str | Path) -> dict[str, Any]:
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            with sqlite3.connect(target) as dest:
                source.backup(dest)
        return {"source": str(self.db_path), "backup": str(target), "ok": True}

    def start_session(
        self,
        *,
        agent_id: str,
        user_id: str,
        host: str,
        briefing: dict[str, Any],
        external_session_id: str | None = None,
    ) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        if external_session_id:
            with self.connect() as conn:
                existing = conn.execute(
                    """
                    SELECT * FROM sessions
                    WHERE agent_id = ? AND host = ? AND external_session_id = ?
                    """,
                    (agent_id, host, external_session_id),
                ).fetchone()
            if existing:
                return self._session_row(existing)
        session_id = new_id("session")
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                  id, agent_id, user_id, host, external_session_id, status,
                  start_revision, start_briefing_json, created_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    session_id,
                    agent_id,
                    user_id,
                    host,
                    external_session_id,
                    agent["revision"],
                    dump(briefing),
                    utc_now(),
                ),
            )
        return self.get_session(session_id, agent_id)

    def find_session_by_external(
        self, agent_id: str, host: str, external_session_id: str
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM sessions
                WHERE agent_id=? AND host=? AND external_session_id=?
                """,
                (agent_id, host, external_session_id),
            ).fetchone()
        return self._session_row(row) if row else None

    @staticmethod
    def _session_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "user_id": row["user_id"],
            "host": row["host"],
            "external_session_id": row["external_session_id"],
            "status": row["status"],
            "start_revision": row["start_revision"],
            "start_briefing": load(row["start_briefing_json"]),
            "conversation": load(row["conversation_json"])
            if row["conversation_json"]
            else None,
            "reflection": load(row["reflection_json"])
            if row["reflection_json"]
            else None,
            "end_revision": row["end_revision"],
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
        }

    def get_session(self, session_id: str, agent_id: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            if agent_id:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ? AND agent_id = ?",
                    (session_id, agent_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?", (session_id,)
                ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown session: {session_id}")
        return self._session_row(row)

    def finish_session(
        self,
        *,
        session_id: str,
        agent_id: str,
        conversation: dict[str, Any],
        reflection: dict[str, Any],
        end_revision: int,
    ) -> dict[str, Any]:
        existing = self.get_session(session_id, agent_id)
        if existing["status"] == "closed":
            return existing
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM sessions WHERE id = ? AND agent_id = ?",
                (session_id, agent_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Unknown session: {session_id}")
            conn.execute(
                """
                UPDATE sessions
                SET status='closed', conversation_json=?, reflection_json=?,
                    end_revision=?, ended_at=?
                WHERE id=? AND agent_id=?
                """,
                (
                    dump(conversation),
                    dump(reflection),
                    end_revision,
                    utc_now(),
                    session_id,
                    agent_id,
                ),
            )
        return self.get_session(session_id, agent_id)

    def list_sessions(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions WHERE agent_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        return [self._session_row(row) for row in rows]

    def list_sources(self, agent_id: str, enabled_only: bool = True) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._agent_exists(conn, agent_id)
            sql = "SELECT * FROM source_subscriptions WHERE agent_id = ?"
            params: tuple[Any, ...] = (agent_id,)
            if enabled_only:
                sql += " AND enabled = 1"
            sql += " ORDER BY name, id"
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def add_source(
        self,
        agent_id: str,
        name: str,
        url: str,
        source_type: str = "rss",
    ) -> dict[str, Any]:
        name = name.strip()
        url = url.strip()
        if not name or not url:
            raise ValidationError("Source requires name and url")
        if source_type not in {"rss", "atom", "webpage"}:
            raise ValidationError("source_type must be rss, atom or webpage")
        now = utc_now()
        source_id = new_id("source")
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            conn.execute(
                """
                INSERT INTO source_subscriptions(
                  id, agent_id, name, url, source_type, enabled,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(agent_id, url) DO UPDATE SET
                  name=excluded.name, source_type=excluded.source_type,
                  enabled=1, updated_at=excluded.updated_at
                """,
                (source_id, agent_id, name, url, source_type, now, now),
            )
            row = conn.execute(
                "SELECT * FROM source_subscriptions WHERE agent_id=? AND url=?",
                (agent_id, url),
            ).fetchone()
        return dict(row)

    def known_experience_fingerprints(self, agent_id: str) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content_fingerprint FROM autonomous_experiences WHERE agent_id=?",
                (agent_id,),
            ).fetchall()
        return {row["content_fingerprint"] for row in rows}

    def record_exploration_run(
        self,
        *,
        run_id: str,
        agent_id: str,
        status: str,
        candidate_count: int,
        result: dict[str, Any],
        selected_url: str | None = None,
        selection_reason: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            conn.execute(
                """
                INSERT INTO exploration_runs(
                  id, agent_id, status, selected_url, selection_reason,
                  candidate_count, result_json, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  status=excluded.status,
                  selected_url=excluded.selected_url,
                  selection_reason=excluded.selection_reason,
                  candidate_count=excluded.candidate_count,
                  result_json=excluded.result_json,
                  error=excluded.error
                """,
                (
                    run_id,
                    agent_id,
                    status,
                    selected_url,
                    selection_reason,
                    candidate_count,
                    dump(result),
                    error,
                    utc_now(),
                ),
            )
        return self.get_exploration_run(run_id)

    def get_exploration_run(self, run_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM exploration_runs WHERE id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown exploration run: {run_id}")
        result = dict(row)
        result["result"] = load(result.pop("result_json"))
        return result

    def save_autonomous_experience(
        self,
        *,
        experience_id: str,
        agent_id: str,
        run_id: str,
        source_name: str,
        title: str,
        url: str,
        published_at: str | None,
        fetched_at: str,
        content_fingerprint: str,
        evidence: dict[str, Any],
        experience: dict[str, Any],
    ) -> dict[str, Any]:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO autonomous_experiences(
                  id, agent_id, run_id, source_name, title, url, published_at,
                  fetched_at, content_fingerprint, evidence_json,
                  experience_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experience_id,
                    agent_id,
                    run_id,
                    source_name,
                    title,
                    url,
                    published_at,
                    fetched_at,
                    content_fingerprint,
                    dump(evidence),
                    dump(experience),
                    utc_now(),
                ),
            )
        return self.get_autonomous_experience(experience_id, agent_id)

    def get_autonomous_experience(
        self, experience_id: str, agent_id: str
    ) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM autonomous_experiences
                WHERE id=? AND agent_id=?
                """,
                (experience_id, agent_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"Unknown autonomous experience: {experience_id}")
        result = dict(row)
        result["evidence"] = load(result.pop("evidence_json"))
        result["experience"] = load(result.pop("experience_json"))
        return result

    def list_autonomous_experiences(
        self, agent_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM autonomous_experiences
                WHERE agent_id=? ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["evidence"] = load(item.pop("evidence_json"))
            item["experience"] = load(item.pop("experience_json"))
            results.append(item)
        return results

    def list_exploration_runs(self, agent_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM exploration_runs
                WHERE agent_id=? ORDER BY created_at DESC LIMIT ?
                """,
                (agent_id, limit),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["result"] = load(item.pop("result_json"))
            results.append(item)
        return results

    def active_session_count(self, agent_id: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE agent_id=? AND status='active'",
                    (agent_id,),
                ).fetchone()[0]
            )

    def latest_exploration(self, agent_id: str) -> dict[str, Any] | None:
        runs = self.list_exploration_runs(agent_id, 1)
        return runs[0] if runs else None

    def exploration_count_since(self, agent_id: str, since: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM exploration_runs
                    WHERE agent_id=? AND created_at>=?
                    """,
                    (agent_id, since),
                ).fetchone()[0]
            )

    def commit_digest(
        self,
        *,
        run_id: str,
        agent_id: str,
        mode: str,
        input_refs: list[str],
        output: dict[str, Any],
        state_before: dict[str, Any],
        state_after: dict[str, Any],
    ) -> None:
        now = utc_now()
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            if input_refs:
                placeholders = ",".join("?" for _ in input_refs)
                rows = conn.execute(
                    f"""
                    SELECT id, status FROM inbox_events
                    WHERE agent_id = ? AND id IN ({placeholders})
                    """,
                    (agent_id, *input_refs),
                ).fetchall()
                statuses = {row["id"]: row["status"] for row in rows}
                missing = [ref for ref in input_refs if ref not in statuses]
                consumed = [ref for ref, status in statuses.items() if status != "pending"]
                if missing or consumed:
                    raise ValidationError(
                        f"Digest inputs changed before commit; missing={missing}, consumed={consumed}"
                    )

            for event in output["internal_events"]:
                conn.execute(
                    """
                    INSERT INTO internal_events(
                      id, agent_id, event_type, content, source,
                      source_refs_json, metadata_json, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["id"],
                        agent_id,
                        event["event_type"],
                        event["content"],
                        "digest",
                        dump(event["source_refs"]),
                        dump(event.get("metadata", {})),
                        event["fingerprint"],
                        now,
                    ),
                )

            for share in output["pending_shares"]:
                conn.execute(
                    """
                    INSERT INTO pending_shares(
                      id, agent_id, user_id, content, reason, share_mode,
                      urgency, relevance, novelty, status, source_refs_json,
                      created_at, expires_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                    """,
                    (
                        share["id"],
                        agent_id,
                        share["user_id"],
                        share["content"],
                        share.get("reason"),
                        share["share_mode"],
                        share["urgency"],
                        share["relevance"],
                        share["novelty"],
                        dump(share["source_refs"]),
                        now,
                        share.get("expires_at"),
                        now,
                    ),
                )

            revision = conn.execute(
                "SELECT revision FROM agent_state WHERE agent_id = ?", (agent_id,)
            ).fetchone()["revision"]
            conn.execute(
                """
                UPDATE agent_state
                SET state_json = ?, revision = ?, updated_at = ?
                WHERE agent_id = ?
                """,
                (
                    dump(state_after),
                    revision + int(output["changed"]),
                    now,
                    agent_id,
                ),
            )

            if input_refs:
                placeholders = ",".join("?" for _ in input_refs)
                conn.execute(
                    f"""
                    UPDATE inbox_events
                    SET status = 'processed', processed_at = ?
                    WHERE agent_id = ? AND id IN ({placeholders})
                    """,
                    (now, agent_id, *input_refs),
                )

            conn.execute(
                """
                INSERT INTO digest_runs(
                  id, agent_id, mode, input_refs_json, changed, reason, status,
                  output_json, error, state_before_json, state_after_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, NULL, ?, ?, ?)
                """,
                (
                    run_id,
                    agent_id,
                    mode,
                    dump(input_refs),
                    int(output["changed"]),
                    output["reason"],
                    dump(output),
                    dump(state_before),
                    dump(state_after),
                    now,
                ),
            )

    def record_failed_digest(
        self,
        *,
        run_id: str,
        agent_id: str,
        mode: str,
        input_refs: list[str],
        state_before: dict[str, Any],
        error: str,
        raw_output: dict[str, Any] | None = None,
    ) -> None:
        with self.transaction() as conn:
            self._agent_exists(conn, agent_id)
            conn.execute(
                """
                INSERT INTO digest_runs(
                  id, agent_id, mode, input_refs_json, changed, reason, status,
                  output_json, error, state_before_json, state_after_json, created_at
                ) VALUES (?, ?, ?, ?, 0, ?, 'failed', ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    agent_id,
                    mode,
                    dump(input_refs),
                    "digest failed validation or model execution",
                    dump(raw_output or {}),
                    error,
                    dump(state_before),
                    dump(state_before),
                    utc_now(),
                ),
            )
