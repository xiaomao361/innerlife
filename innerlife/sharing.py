from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import PROJECT_ROOT, Settings
from .digest import make_backend
from .models import ValidationError, active_state_view
from .storage import Storage


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hours_since(value: str | None, now: datetime) -> float:
    parsed = _parse(value)
    if parsed is None:
        return float("inf")
    return max(0.0, (now - parsed).total_seconds() / 3600)


def _prompt() -> str:
    return (PROJECT_ROOT / "prompts" / "share_decision.md").read_text(
        encoding="utf-8"
    )


class ShareScheduler:
    def __init__(self, storage: Storage, settings: Settings, backend=None):
        self.storage = storage
        self.settings = settings
        self.backend = backend or make_backend(settings)

    def _candidates(
        self,
        agent_id: str,
        user_id: str,
        context: dict[str, Any] | None,
        session_id: str | None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        now = _now()
        agent = self.storage.get_agent(agent_id)
        policy = agent["profile"].get("share_policy") or {}
        proactive_after = float(policy.get("proactive_after_hours", 12))
        cooldown = float(policy.get("repeat_cooldown_hours", 24))
        stale_after = float(policy.get("stale_after_days", 7)) * 24
        max_defer = int(policy.get("max_defer_count", 3))
        max_daily = int(policy.get("max_proactive_per_day", 1))
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        proactive_remaining = max(
            0,
            max_daily
            - self.storage.proactive_share_count_since(agent_id, day_start),
        )
        candidates = []
        for share in self.storage.pending_shares(agent_id):
            if share["user_id"] != user_id or share["share_mode"] == "never_push":
                continue
            age_hours = _hours_since(share["created_at"], now)
            surfaced_hours = _hours_since(share["last_surfaced_at"], now)
            if surfaced_hours < cooldown:
                continue
            if context is None and _hours_since(
                share["last_evaluated_at"], now
            ) < min(6.0, cooldown):
                continue
            if session_id and any(
                action["session_id"] == session_id
                for action in self.storage.share_actions(
                    agent_id, share["id"], 20
                )
            ):
                continue
            stale = age_hours >= stale_after or share["defer_count"] >= max_defer
            allowed_styles: list[str] = []
            if context is not None and share["share_mode"] in {
                "when_relevant",
                "on_user_asks",
                "proactive_allowed",
            }:
                allowed_styles.append("natural")
            if (
                context is None
                and share["share_mode"] == "proactive_allowed"
                and proactive_remaining > 0
                and (age_hours >= proactive_after or share["urgency"] >= 0.8)
            ):
                allowed_styles.append("proactive")
            if not allowed_styles and not stale:
                continue
            if (
                not allowed_styles
                and _hours_since(share["last_evaluated_at"], now) < 24
            ):
                continue
            candidates.append(
                {
                    **share,
                    "age_hours": round(age_hours, 2),
                    "stale": stale,
                    "can_share_now": bool(allowed_styles),
                    "allowed_delivery_styles": allowed_styles,
                }
            )
        return candidates[:20], {
            "max_proactive_per_day": max_daily,
            "proactive_remaining_today": proactive_remaining,
            "repeat_cooldown_hours": cooldown,
            "stale_after_hours": stale_after,
            "max_defer_count": max_defer,
        }

    def check(
        self,
        *,
        agent_id: str,
        user_id: str,
        session_id: str | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.storage.expire_pending_shares(agent_id)
        candidates, policy = self._candidates(
            agent_id, user_id, conversation_context, session_id
        )
        if not candidates:
            return {
                "selected": False,
                "decision": "wait",
                "reason": "当前没有达到重新判断条件的待分享内容",
                "share": None,
                "delivery_style": None,
                "suggested_opening": "",
            }
        agent = self.storage.get_agent(agent_id)
        payload = {
            "agent_id": agent_id,
            "user_id": user_id,
            "profile": agent["profile"],
            "state": active_state_view(agent["state"]),
            "policy": policy,
            "conversation_context": conversation_context,
            "candidate_shares": candidates,
        }
        raw = None
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = _prompt()
            if attempt:
                prompt += "\n\n上一次输出无法读取。不要解释，只返回指定 JSON。"
            try:
                raw = self.backend.generate(
                    system_prompt=prompt,
                    payload=payload,
                    model=self.settings.model_for("light"),
                )
                if not isinstance(raw, dict):
                    raise ValidationError("share decision must be an object")
                break
            except Exception as exc:
                last_error = exc
        if raw is None:
            raise ValidationError(f"share decision failed after retry: {last_error}")
        selected = raw.get("selected")
        if not isinstance(selected, bool):
            raise ValidationError("share decision requires selected boolean")
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise ValidationError("share decision requires reason")
        if not selected:
            for candidate in candidates:
                self.storage.evaluate_share(
                    share_id=candidate["id"],
                    agent_id=agent_id,
                    decision="wait",
                    reason=reason,
                    session_id=session_id,
                    metadata={"conversation_context": conversation_context},
                )
            return {
                "selected": False,
                "decision": "wait",
                "reason": reason,
                "share": None,
                "delivery_style": None,
                "suggested_opening": "",
            }
        share_id = str(raw.get("share_id") or "")
        candidate = next((item for item in candidates if item["id"] == share_id), None)
        if candidate is None:
            raise ValidationError("model selected an unavailable pending share")
        decision = str(raw.get("decision") or "")
        if decision not in {"share_now", "wait", "discard"}:
            raise ValidationError("unsupported share decision")
        delivery_style = raw.get("delivery_style")
        if decision == "share_now":
            if delivery_style not in candidate["allowed_delivery_styles"]:
                raise ValidationError("share decision used a disallowed delivery style")
            opening = str(raw.get("suggested_opening") or "").strip()
            if not opening:
                raise ValidationError("share_now requires suggested_opening")
        else:
            delivery_style = None
            opening = ""
        updated = self.storage.evaluate_share(
            share_id=share_id,
            agent_id=agent_id,
            decision=decision,
            reason=reason,
            session_id=session_id,
            delivery_style=delivery_style,
            metadata={"conversation_context": conversation_context},
        )
        for other in candidates:
            if other["id"] == share_id:
                continue
            self.storage.evaluate_share(
                share_id=other["id"],
                agent_id=agent_id,
                decision="wait",
                reason="本次选择了另一条更适合的内容",
                session_id=session_id,
                metadata={"conversation_context": conversation_context},
            )
        return {
            "selected": decision == "share_now",
            "decision": decision,
            "reason": reason,
            "share": updated if decision == "share_now" else None,
            "delivery_style": delivery_style,
            "suggested_opening": opening,
        }
