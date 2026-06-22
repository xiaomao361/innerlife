from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


class InnerLifeError(Exception):
    """Base error for expected InnerLife failures."""


class NotFoundError(InnerLifeError):
    pass


class ValidationError(InnerLifeError):
    pass


class ModelError(InnerLifeError):
    pass


DEFAULT_STATE: dict[str, Any] = {
    "current_interests": [],
    "open_loops": [],
    "recent_mood": None,
    "recent_focus": None,
}


@dataclass(frozen=True)
class DigestResult:
    run_id: str
    agent_id: str
    mode: str
    changed: bool
    reason: str
    internal_events: list[dict[str, Any]]
    state: dict[str, Any]
    pending_shares: list[dict[str, Any]]
    input_refs: list[str]
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "mode": self.mode,
            "changed": self.changed,
            "reason": self.reason,
            "internal_events": self.internal_events,
            "state": self.state,
            "pending_shares": self.pending_shares,
            "input_refs": self.input_refs,
            "status": self.status,
        }


def json_object(value: str | bytes | dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValidationError("Expected a JSON object")
    return parsed
