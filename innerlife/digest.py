from __future__ import annotations

import json
import re as _re
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, Settings
from .evaluator import evaluate_output
from .llm import (
    AnthropicCompatibleBackend,
    Backend,
    FakeBackend,
    OpenAICompatibleBackend,
)
from .models import DigestResult, InnerLifeError, ValidationError, active_state_view
from .storage import Storage, new_id


def load_prompt(path: str | Path | None = None) -> str:
    prompt_path = Path(path) if path else PROJECT_ROOT / "prompts" / "digest.md"
    return prompt_path.read_text(encoding="utf-8")


def make_backend(settings: Settings) -> Backend:
    if settings.backend == "fake":
        return FakeBackend()
    if settings.backend in {"openai_compatible", "local"}:
        return OpenAICompatibleBackend(
            settings.base_url,
            settings.api_key,
            settings.timeout_seconds,
        )
    if settings.backend == "anthropic_compatible":
        return AnthropicCompatibleBackend(
            settings.base_url,
            settings.api_key,
            settings.timeout_seconds,
        )
    raise ValidationError(f"Unsupported LLM backend: {settings.backend}")


class DigestEngine:
    def __init__(
        self,
        storage: Storage,
        backend: Backend,
        *,
        system_prompt: str | None = None,
    ):
        self.storage = storage
        self.backend = backend
        self.system_prompt = system_prompt or load_prompt()

    def run(self, agent_id: str, mode: str = "light", model: str = "fake") -> DigestResult:
        if mode not in {"light", "deep"}:
            raise ValidationError("mode must be light or deep")
        agent = self.storage.get_agent(agent_id)
        pending = self.storage.pending_events(agent_id)
        recent = self.storage.recent_internal_events(agent_id)
        recent_experiences = self.storage.list_autonomous_experiences(agent_id, limit=20)
        input_refs = [item["id"] for item in pending]
        run_id = new_id("digest")
        payload = {
            "agent_id": agent_id,
            "mode": mode,
            "profile": agent["profile"],
            "state": active_state_view(agent["state"]),
            "pending_inbox_events": pending,
            "recent_internal_events": recent,
        }
        raw_output: dict[str, Any] | None = None
        try:
            raw_output = self.backend.generate(
                system_prompt=self.system_prompt,
                payload=payload,
                model=model,
            )
            allowed_refs = set(input_refs)
            allowed_refs.update(
                item["id"] for item in recent if isinstance(item.get("id"), str)
            )
            allowed_refs.update(
                item["id"]
                for item in recent_experiences
                if isinstance(item.get("id"), str)
            )
            allowed_refs.update(
                str(loop["id"])
                for loop in agent["state"].get("open_loops", [])
                if isinstance(loop, dict) and loop.get("id")
            )
            # Allow truncated memoria-style refs (LLM often writes "memoria_lara_abc12345"
            # — first 8 chars of UUID — instead of the full inbox event ID)
            for ref in input_refs:
                m = _re.match(r"(memoria_\w+)_([0-9a-f]{8})", ref)
                if m:
                    allowed_refs.add(f"{m.group(1)}_{m.group(2)}")
            normalized, state_after = evaluate_output(
                raw_output=raw_output,
                agent_id=agent_id,
                profile=agent["profile"],
                state_before=agent["state"],
                allowed_refs=allowed_refs,
                recent_internal_events=recent,
            )
            self.storage.commit_digest(
                run_id=run_id,
                agent_id=agent_id,
                mode=mode,
                input_refs=input_refs,
                output=normalized,
                state_before=agent["state"],
                state_after=state_after,
            )
        except Exception as exc:
            try:
                self.storage.record_failed_digest(
                    run_id=run_id,
                    agent_id=agent_id,
                    mode=mode,
                    input_refs=input_refs,
                    state_before=agent["state"],
                    error=str(exc),
                    raw_output=raw_output,
                )
            except InnerLifeError:
                pass
            raise

        return DigestResult(
            run_id=run_id,
            agent_id=agent_id,
            mode=mode,
            changed=normalized["changed"],
            reason=normalized["reason"],
            internal_events=normalized["internal_events"],
            state=state_after,
            pending_shares=normalized["pending_shares"],
            input_refs=input_refs,
        )


def run_from_settings(agent_id: str, mode: str, settings: Settings) -> DigestResult:
    storage = Storage(settings.db_path)
    backend = make_backend(settings)
    return DigestEngine(storage, backend).run(
        agent_id,
        mode,
        settings.model_for(mode),
    )


def compact_result(result: DigestResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
