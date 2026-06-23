from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from .models import ModelError


class Backend(Protocol):
    def generate(
        self, *, system_prompt: str, payload: dict[str, Any], model: str
    ) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ModelError("Model response did not contain a JSON object")
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ModelError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelError("Model response must be a JSON object")
    return value


class FakeBackend:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        responder: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.response = response
        self.responder = responder

    def generate(
        self, *, system_prompt: str, payload: dict[str, Any], model: str
    ) -> dict[str, Any]:
        if self.responder:
            return self.responder(payload)
        if self.response is not None:
            return json.loads(json.dumps(self.response, ensure_ascii=False))
        if "conversation" in payload:
            return {
                "has_afterthought": False,
                "reason": "The fake backend does not infer an afterthought.",
                "conversation_summary": "Fake-backend acceptance conversation.",
                "agent_afterthought": "",
                "open_loops": [],
            }
        if "candidate_shares" in payload:
            return {
                "selected": False,
                "share_id": None,
                "decision": "wait",
                "delivery_style": None,
                "reason": "The fake backend does not surface pending shares.",
                "suggested_opening": "",
            }
        events = payload.get("pending_inbox_events", [])
        if not events:
            return {
                "changed": False,
                "reason": "没有新的输入材料",
                "internal_events": [],
                "state_update": {},
                "pending_shares": [],
            }
        latest = events[-1]
        content = latest.get("content", {})
        text = str(content.get("text") or content.get("summary") or "").strip()
        if not text:
            return {
                "changed": False,
                "reason": "输入没有提供可消化的内容",
                "internal_events": [],
                "state_update": {},
                "pending_shares": [],
            }
        return {
            "changed": True,
            "reason": "新的输入形成了一个仍需继续思考的问题",
            "internal_events": [
                {
                    "event_type": "new_question",
                    "content": f"我还需要继续想清楚：{text}",
                    "source_refs": [latest["id"]],
                }
            ],
            "state_update": {
                "recent_focus": text,
                "open_loops": [
                    {
                        "content": text,
                        "source_refs": [latest["id"]],
                        "status": "open",
                    }
                ],
            },
            "pending_shares": [],
        }


class OpenAICompatibleBackend:
    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(
        self, *, system_prompt: str, payload: dict[str, Any], model: str
    ) -> dict[str, Any]:
        request_body = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, indent=2),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelError(f"Model request failed: {exc}") from exc
        try:
            message = body["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Model response did not use the expected chat format") from exc
        if isinstance(content, list):
            text = "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
            )
        else:
            text = str(content or "")
        if not text.strip():
            raise ModelError("Model response contained no final text")
        return _extract_json(text)


class AnthropicCompatibleBackend:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def generate(
        self, *, system_prompt: str, payload: dict[str, Any], model: str
    ) -> dict[str, Any]:
        endpoint = (
            f"{self.base_url}/messages"
            if self.base_url.endswith("/v1")
            else f"{self.base_url}/v1/messages"
        )
        request_body = {
            "model": model,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, indent=2),
                }
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ModelError(f"Model request failed: {exc}") from exc
        try:
            text = next(
                block["text"]
                for block in body["content"]
                if block.get("type") == "text"
            )
        except (KeyError, StopIteration, TypeError) as exc:
            raise ModelError("Model response did not contain a text block") from exc
        return _extract_json(text)
