from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, Settings
from .digest import DigestEngine, make_backend
from .models import ValidationError
from .service import get_briefing
from .storage import Storage


def _reflection_prompt() -> str:
    return (PROJECT_ROOT / "prompts" / "session_reflection.md").read_text(
        encoding="utf-8"
    )


def _validate_reflection(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("has_afterthought"), bool):
        raise ValidationError("session reflection requires has_afterthought boolean")
    reason = str(value.get("reason") or "").strip()
    if not reason:
        raise ValidationError("session reflection requires reason")
    summary = str(value.get("conversation_summary") or "").strip()
    afterthought = str(value.get("agent_afterthought") or "").strip()
    loops = value.get("open_loops") or []
    if not isinstance(loops, list) or not all(isinstance(item, str) for item in loops):
        raise ValidationError("session reflection open_loops must be strings")
    if not value["has_afterthought"]:
        return {
            "has_afterthought": False,
            "reason": reason,
            "conversation_summary": summary,
            "agent_afterthought": "",
            "open_loops": [],
        }
    if not afterthought:
        raise ValidationError("has_afterthought=true requires agent_afterthought")
    return {
        "has_afterthought": True,
        "reason": reason,
        "conversation_summary": summary,
        "agent_afterthought": afterthought,
        "open_loops": [item.strip() for item in loops if item.strip()],
    }


class SessionLifecycle:
    def __init__(self, storage: Storage, settings: Settings, backend=None):
        self.storage = storage
        self.settings = settings
        self.backend = backend or make_backend(settings)

    def start(
        self,
        *,
        agent_id: str,
        user_id: str,
        host: str,
        external_session_id: str | None = None,
    ) -> dict[str, Any]:
        user_id = user_id.strip()
        if not user_id:
            raise ValidationError("user_id is required")
        profile = self.storage.get_agent(agent_id)["profile"]
        allowed_users = profile.get("boundaries", {}).get("can_access_users", [])
        if allowed_users and user_id not in allowed_users:
            raise ValidationError(
                f"user_id {user_id!r} is not allowed by agent {agent_id!r}"
            )
        briefing = get_briefing(self.storage, agent_id)
        session = self.storage.start_session(
            agent_id=agent_id,
            user_id=user_id,
            host=host,
            briefing=briefing,
            external_session_id=external_session_id,
        )
        return {
            "session": session,
            "briefing": session["start_briefing"],
            "instruction": (
                "把 briefing 作为 Agent 的内在背景，不机械播报。"
                "会话结束时把实际对话内容交回 session-end。"
            ),
        }

    def end(
        self,
        *,
        session_id: str,
        agent_id: str,
        conversation: dict[str, Any],
        process_now: bool = True,
    ) -> dict[str, Any]:
        session = self.storage.get_session(session_id, agent_id)
        if session["status"] == "closed":
            return {
                "session": session,
                "reflection": session["reflection"],
                "digest": None,
                "idempotent": True,
            }
        current_briefing = get_briefing(self.storage, agent_id)
        state_changed_during_session = (
            current_briefing["revision"] != session["start_revision"]
        )
        payload = {
            "agent_id": agent_id,
            "profile": self.storage.get_agent(agent_id)["profile"],
            "start_briefing": session["start_briefing"],
            "current_briefing": current_briefing,
            "state_changed_during_session": state_changed_during_session,
            "conversation": conversation,
        }
        reflection = None
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = _reflection_prompt()
            if attempt:
                prompt += (
                    "\n\n上一次输出无法读取。不要解释，不要使用 Markdown，"
                    "只返回符合指定字段的 JSON 对象。"
                )
            try:
                raw = self.backend.generate(
                    system_prompt=prompt,
                    payload=payload,
                    model=self.settings.model_for("light"),
                )
                reflection = _validate_reflection(raw)
                break
            except Exception as exc:
                last_error = exc
        if reflection is None:
            raise ValidationError(
                f"session reflection failed after retry: {last_error}"
            )
        submitted = None
        digest = None
        if reflection["has_afterthought"]:
            submitted = self.storage.submit_event(
                agent_id,
                "afterthought",
                session_id,
                {
                    "conversation_summary": reflection["conversation_summary"],
                    "text": reflection["agent_afterthought"],
                    "open_loops": reflection["open_loops"],
                    "session_id": session_id,
                },
                event_id=f"afterthought_{session_id}",
            )
            if process_now:
                digest = DigestEngine(self.storage, self.backend).run(
                    agent_id,
                    "light",
                    self.settings.model_for("light"),
                ).to_dict()
        agent = self.storage.get_agent(agent_id)
        closed = self.storage.finish_session(
            session_id=session_id,
            agent_id=agent_id,
            conversation=conversation,
            reflection=reflection,
            end_revision=agent["revision"],
        )
        return {
            "session": closed,
            "reflection": reflection,
            "submitted_event": submitted,
            "digest": digest,
            "state_changed_during_session": state_changed_during_session,
            "idempotent": False,
        }
