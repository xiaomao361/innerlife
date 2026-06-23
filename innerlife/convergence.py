from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import PROJECT_ROOT, Settings
from .digest import make_backend
from .models import ValidationError
from .storage import Storage, new_id


def _prompt() -> str:
    return (PROJECT_ROOT / "prompts" / "convergence.md").read_text(
        encoding="utf-8"
    )


class ConvergenceEngine:
    def __init__(self, storage: Storage, settings: Settings, backend=None):
        self.storage = storage
        self.settings = settings
        self.backend = backend or make_backend(settings)

    def policy(self, agent_id: str) -> dict[str, int | float | bool]:
        profile = self.storage.get_agent(agent_id)["profile"]
        configured = profile.get("convergence") or {}
        return {
            "enabled": bool(configured.get("enabled", True)),
            "max_active_internal_events": int(
                configured.get("max_active_internal_events", 40)
            ),
            "max_active_experiences": int(
                configured.get("max_active_experiences", 20)
            ),
            "max_active_open_loops": int(
                configured.get("max_active_open_loops", 12)
            ),
            "min_interval_hours": float(
                configured.get("min_interval_hours", 24)
            ),
            "max_archive_events_per_run": int(
                configured.get("max_archive_events_per_run", 20)
            ),
            "max_archive_experiences_per_run": int(
                configured.get("max_archive_experiences_per_run", 10)
            ),
        }

    def needs_run(self, agent_id: str) -> bool:
        policy = self.policy(agent_id)
        if not policy["enabled"]:
            return False
        pressure = self.storage.convergence_pressure(agent_id)
        return (
            pressure["active_internal_events"]
            > policy["max_active_internal_events"]
            or pressure["active_experiences"] > policy["max_active_experiences"]
            or pressure["active_open_loops"] > policy["max_active_open_loops"]
        )

    def run(self, agent_id: str, force: bool = False) -> dict[str, Any]:
        run_id = new_id("convergence")
        policy = self.policy(agent_id)
        pressure = self.storage.convergence_pressure(agent_id)
        if not force and not self.needs_run(agent_id):
            return {
                "run_id": run_id,
                "changed": False,
                "reason": "活跃状态仍在阈值内",
                "pressure": pressure,
            }
        events = self.storage.recent_internal_events(agent_id, 500)
        experiences = self.storage.list_autonomous_experiences(agent_id, 500)
        agent = self.storage.get_agent(agent_id)
        active_loops = [
            loop
            for loop in agent["state"].get("open_loops", [])
            if isinstance(loop, dict) and loop.get("status", "open") == "open"
        ]
        event_excess = max(
            0,
            len(events) - int(policy["max_active_internal_events"]),
        )
        experience_excess = max(
            0,
            len(experiences) - int(policy["max_active_experiences"]),
        )
        event_count = min(
            max(event_excess, 1 if force and events else 0),
            int(policy["max_archive_events_per_run"]),
        )
        experience_count = min(
            max(experience_excess, 1 if force and experiences else 0),
            int(policy["max_archive_experiences_per_run"]),
        )
        archive_events = list(reversed(events))[:event_count]
        archive_experiences = list(reversed(experiences))[:experience_count]
        archive_event_ids = {item["id"] for item in archive_events}
        archive_experience_ids = {item["id"] for item in archive_experiences}
        protected_events = [
            item for item in events if item["id"] not in archive_event_ids
        ][: int(policy["max_active_internal_events"])]
        protected_experiences = [
            item
            for item in experiences
            if item["id"] not in archive_experience_ids
        ][: int(policy["max_active_experiences"])]
        loop_candidates = active_loops
        if len(active_loops) <= int(policy["max_active_open_loops"]) and not force:
            loop_candidates = []
        allowed_event_ids = {item["id"] for item in archive_events}
        allowed_experience_ids = {item["id"] for item in archive_experiences}
        allowed_loop_ids = {
            str(item["id"]) for item in loop_candidates if item.get("id")
        }
        payload = {
            "agent_id": agent_id,
            "profile": agent["profile"],
            "state": agent["state"],
            "policy": policy,
            "pressure": pressure,
            "active_summaries": self.storage.list_inner_summaries(agent_id, 10),
            "archive_candidates": {
                "internal_events": archive_events,
                "autonomous_experiences": archive_experiences,
            },
            "loop_candidates": loop_candidates,
            "protected_recent": {
                "internal_event_ids": [item["id"] for item in protected_events],
                "experience_ids": [item["id"] for item in protected_experiences],
            },
        }
        raw: dict[str, Any] | None = None
        last_error: Exception | None = None
        try:
            for attempt in range(2):
                prompt = _prompt()
                if attempt:
                    prompt += "\n\n上一次输出无法读取。不要解释，只返回指定 JSON。"
                try:
                    value = self.backend.generate(
                        system_prompt=prompt,
                        payload=payload,
                        model=self.settings.model_for("deep"),
                    )
                    if not isinstance(value, dict):
                        raise ValidationError("convergence output must be an object")
                    raw = value
                    break
                except Exception as exc:
                    last_error = exc
            if raw is None:
                raise ValidationError(f"convergence failed after retry: {last_error}")
            if not isinstance(raw.get("changed"), bool):
                raise ValidationError("convergence requires changed boolean")
            reason = str(raw.get("reason") or "").strip()
            if not reason:
                raise ValidationError("convergence requires reason")
            event_ids = list(raw.get("archive_internal_event_ids") or [])
            experience_ids = list(raw.get("archive_experience_ids") or [])
            dormant_ids = list(raw.get("dormant_loop_ids") or [])
            resolved_ids = list(raw.get("resolved_loop_ids") or [])
            if not set(event_ids) <= allowed_event_ids:
                raise ValidationError("convergence selected protected internal events")
            if not set(experience_ids) <= allowed_experience_ids:
                raise ValidationError("convergence selected protected experiences")
            if not (set(dormant_ids) | set(resolved_ids)) <= allowed_loop_ids:
                raise ValidationError("convergence selected unavailable loops")
            if set(dormant_ids) & set(resolved_ids):
                raise ValidationError("loop cannot be dormant and resolved together")
            summary_raw = raw.get("summary")
            summary = None
            archived_refs = set(event_ids) | set(experience_ids)
            if event_ids or experience_ids:
                if not isinstance(summary_raw, dict):
                    raise ValidationError("archiving requires a convergence summary")
            if isinstance(summary_raw, dict):
                title = str(summary_raw.get("title") or "").strip()
                content = str(summary_raw.get("content") or "").strip()
                refs = list(summary_raw.get("source_refs") or [])
                allowed_refs = (
                    allowed_event_ids | allowed_experience_ids | allowed_loop_ids
                )
                if not title or not content or not refs or not set(refs) <= allowed_refs:
                    raise ValidationError("convergence summary is incomplete or ungrounded")
                if archived_refs and not archived_refs <= set(refs):
                    raise ValidationError("summary must reference every archived item")
                summary = {
                    "id": new_id("summary"),
                    "title": title,
                    "content": content,
                    "source_refs": refs,
                }
            changed = bool(
                summary or event_ids or experience_ids or dormant_ids or resolved_ids
            )
            if raw["changed"] != changed:
                raise ValidationError("convergence changed flag does not match actions")
            result = {
                "changed": changed,
                "reason": reason,
                "summary": summary,
                "archive_internal_event_ids": event_ids,
                "archive_experience_ids": experience_ids,
                "dormant_loop_ids": dormant_ids,
                "resolved_loop_ids": resolved_ids,
            }
            run = self.storage.commit_convergence(
                run_id=run_id,
                agent_id=agent_id,
                reason=reason,
                input_counts=pressure,
                summary=summary,
                archive_event_ids=event_ids,
                archive_experience_ids=experience_ids,
                dormant_loop_ids=dormant_ids,
                resolved_loop_ids=resolved_ids,
                result=result,
            )
            return {
                "run_id": run_id,
                **result,
                "pressure_before": pressure,
                "pressure_after": self.storage.convergence_pressure(agent_id),
                "run": run,
            }
        except Exception as exc:
            self.storage.record_failed_convergence(
                run_id=run_id,
                agent_id=agent_id,
                input_counts=pressure,
                error=str(exc),
                result=raw,
            )
            raise
