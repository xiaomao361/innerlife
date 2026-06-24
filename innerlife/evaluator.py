from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from .models import ValidationError


ALLOWED_EVENT_TYPES = {
    "new_insight",
    "new_question",
    "interest_shift",
    "self_revision",
    "relationship_reflection",
    "share_desire",
}
ALLOWED_SHARE_MODES = {
    "when_relevant",
    "on_user_asks",
    "proactive_allowed",
    "never_push",
}
REALITY_CLAIM_PATTERNS = [
    r"我今天(?:去)?散步",
    r"我刚刚看(?:了|到)夕阳",
    r"我今天(?:去)?游泳",
    r"我刚吃(?:了)?",
    r"我(?:正在|刚刚)开车",
    r"\bi (?:went|just went) for a walk\b",
    r"\bi (?:just )?watched the sunset\b",
]


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} must be a list")
    return value


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def fingerprint(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def _is_duplicate(content: str, recent: list[dict[str, Any]]) -> bool:
    normalized = _normalize_text(content)
    fp = fingerprint(content)
    for item in recent:
        if item.get("fingerprint") == fp:
            return True
        previous = _normalize_text(str(item.get("content", "")))
        if previous and SequenceMatcher(None, normalized, previous).ratio() >= 0.92:
            return True
    return False


def _contains_reality_claim(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in REALITY_CLAIM_PATTERNS)


def _validate_refs(refs: Any, allowed_refs: set[str], field: str) -> list[str]:
    values = _list(refs, field)
    normalized: list[str] = []
    for value in values:
        ref = _text(value, field)
        if ref not in allowed_refs:
            # Allow memoria-prefixed refs (real system entries, may predate current batch)
            if not (ref.startswith("memoria_") and _is_likely_uuid_ref(ref)):
                raise ValidationError(f"{field} contains unavailable source ref: {ref}")
        if ref not in normalized:
            normalized.append(ref)
    if not normalized:
        raise ValidationError(f"{field} must contain at least one source ref")
    return normalized


def _is_likely_uuid_ref(ref: str) -> bool:
    """Check if ref looks like a valid memoria-style ID: memoria_agent_uuid"""
    import re
    return bool(re.match(r"^memoria_\w+_[0-9a-f]{8}", ref))


def _score(value: Any, field: str) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} must be a number") from exc
    if score < 0 or score > 1:
        raise ValidationError(f"{field} must be between 0 and 1")
    return score


def _merge_state(
    state_before: dict[str, Any],
    state_update: dict[str, Any],
    allowed_refs: set[str],
) -> dict[str, Any]:
    if not isinstance(state_update, dict):
        raise ValidationError("state_update must be an object")
    allowed_fields = {
        "current_interests",
        "open_loops",
        "resolved_loop_ids",
        "recent_mood",
        "recent_focus",
    }
    unknown = sorted(set(state_update) - allowed_fields)
    if unknown:
        raise ValidationError(f"state_update contains unsupported fields: {unknown}")
    result = copy.deepcopy(state_before)

    if "current_interests" in state_update:
        interests = [
            _text(item, "current_interests item")
            for item in _list(state_update["current_interests"], "current_interests")
        ]
        result["current_interests"] = list(dict.fromkeys(interests))

    loops = [
        copy.deepcopy(loop)
        for loop in result.get("open_loops", [])
        if isinstance(loop, dict)
    ]
    resolved = set(state_update.get("resolved_loop_ids") or [])
    if resolved:
        known_loop_ids = {str(loop.get("id")) for loop in loops if loop.get("id")}
        unknown_resolved = resolved - known_loop_ids
        if unknown_resolved:
            raise ValidationError(
                f"resolved_loop_ids contains unavailable loops: {sorted(unknown_resolved)}"
            )
        loops = [loop for loop in loops if str(loop.get("id")) not in resolved]

    existing_loop_text = {
        _normalize_text(str(loop.get("content", ""))) for loop in loops
    }
    for item in _list(state_update.get("open_loops", []), "open_loops"):
        if not isinstance(item, dict):
            raise ValidationError("open_loops items must be objects")
        content = _text(item.get("content"), "open_loop.content")
        refs = _validate_refs(
            item.get("source_refs"), allowed_refs, "open_loop.source_refs"
        )
        if _normalize_text(content) in existing_loop_text:
            continue
        loops.append(
            {
                "id": item.get("id") or f"loop_{uuid.uuid4().hex}",
                "content": content,
                "source_refs": refs,
                "status": item.get("status", "open"),
                "created_at": item.get("created_at")
                or datetime.now(timezone.utc).isoformat(),
                "last_reinforced_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        existing_loop_text.add(_normalize_text(content))
    result["open_loops"] = loops

    for key in ("recent_mood", "recent_focus"):
        if key in state_update:
            value = state_update[key]
            result[key] = None if value is None else _text(value, key)
    return result


def evaluate_output(
    *,
    raw_output: dict[str, Any],
    agent_id: str,
    profile: dict[str, Any],
    state_before: dict[str, Any],
    allowed_refs: set[str],
    recent_internal_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw_output, dict):
        raise ValidationError("Model output must be an object")
    if not isinstance(raw_output.get("changed"), bool):
        raise ValidationError("changed must be true or false")

    reason = _text(raw_output.get("reason"), "reason")
    raw_events = _list(raw_output.get("internal_events") or [], "internal_events")
    raw_shares = _list(raw_output.get("pending_shares") or [], "pending_shares")
    state_update = raw_output.get("state_update") or {}
    if not isinstance(state_update, dict):
        raise ValidationError("state_update must be an object")

    if not raw_output["changed"]:
        if raw_events or raw_shares or state_update:
            raise ValidationError(
                "changed=false requires empty internal_events, state_update and pending_shares"
            )
        return (
            {
                "changed": False,
                "reason": reason,
                "internal_events": [],
                "state_update": {},
                "pending_shares": [],
            },
            copy.deepcopy(state_before),
        )

    normalized_events: list[dict[str, Any]] = []
    for item in raw_events:
        if not isinstance(item, dict):
            raise ValidationError("internal_events items must be objects")
        event_type = _text(item.get("event_type"), "event_type")
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValidationError(f"Unsupported event_type: {event_type}")
        content = _text(item.get("content"), "internal_event.content")
        if _contains_reality_claim(content):
            raise ValidationError("Internal event contains an unsupported reality claim")
        refs = _validate_refs(
            item.get("source_refs"), allowed_refs, "internal_event.source_refs"
        )
        if _is_duplicate(content, recent_internal_events + normalized_events):
            continue
        normalized_events.append(
            {
                "id": f"internal_{uuid.uuid4().hex}",
                "event_type": event_type,
                "content": content,
                "source_refs": refs,
                "metadata": item.get("metadata") or {},
                "fingerprint": fingerprint(content),
            }
        )

    normalized_shares: list[dict[str, Any]] = []
    event_contents = {_normalize_text(item["content"]) for item in normalized_events}
    default_users = profile.get("boundaries", {}).get("can_access_users", [])
    default_user = default_users[0] if default_users else "default"
    for item in raw_shares:
        if not isinstance(item, dict):
            raise ValidationError("pending_shares items must be objects")
        content = _text(item.get("content"), "pending_share.content")
        if _contains_reality_claim(content):
            raise ValidationError("Pending share contains an unsupported reality claim")
        if _normalize_text(content) in event_contents:
            raise ValidationError(
                "Pending share must not copy an internal event word for word"
            )
        refs = _validate_refs(
            item.get("source_refs"), allowed_refs, "pending_share.source_refs"
        )
        mode = item.get("share_mode", "when_relevant")
        if mode not in ALLOWED_SHARE_MODES:
            raise ValidationError(f"Unsupported share_mode: {mode}")
        normalized_shares.append(
            {
                "id": f"share_{uuid.uuid4().hex}",
                "user_id": item.get("user_id") or default_user,
                "content": content,
                "reason": item.get("reason"),
                "share_mode": mode,
                "urgency": _score(item.get("urgency", 0), "urgency"),
                "relevance": _score(item.get("relevance", 0), "relevance"),
                "novelty": _score(item.get("novelty", 0), "novelty"),
                "source_refs": refs,
                "expires_at": item.get("expires_at"),
            }
        )

    if not normalized_events:
        return (
            {
                "changed": False,
                "reason": "候选变化与已有内容重复，没有形成新的内部变化",
                "internal_events": [],
                "state_update": {},
                "pending_shares": [],
            },
            copy.deepcopy(state_before),
        )

    state_after = _merge_state(state_before, state_update, allowed_refs)
    normalized = {
        "changed": True,
        "reason": reason,
        "internal_events": normalized_events,
        "state_update": state_update,
        "pending_shares": normalized_shares,
    }
    return normalized, state_after


def output_as_text(output: dict[str, Any]) -> str:
    return json.dumps(output, ensure_ascii=False, sort_keys=True)
