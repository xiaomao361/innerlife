from __future__ import annotations

import json
import urllib.request
from typing import Any

from .config import Settings
from .storage import Storage


def get_briefing(storage: Storage, agent_id: str, event_limit: int = 8) -> dict[str, Any]:
    agent = storage.get_agent(agent_id)
    events = storage.recent_internal_events(agent_id, event_limit)
    shares = storage.pending_shares(agent_id)
    experiences = storage.list_autonomous_experiences(agent_id, 5)
    summaries = storage.list_inner_summaries(agent_id, 5)
    state = agent["state"]
    active_loops = [
        loop
        for loop in state.get("open_loops", [])
        if isinstance(loop, dict) and loop.get("status", "open") == "open"
    ]
    return {
        "agent_id": agent_id,
        "display_name": agent["profile"]["display_name"],
        "current_interests": state.get("current_interests", []),
        "open_loops": active_loops,
        "recent_mood": state.get("recent_mood"),
        "recent_focus": state.get("recent_focus"),
        "recent_internal_events": events,
        "pending_shares": shares,
        "recent_autonomous_experiences": [
            {
                "id": item["id"],
                "title": item["title"],
                "url": item["url"],
                "source_name": item["source_name"],
                "fetched_at": item["fetched_at"],
                "experience": item["experience"],
            }
            for item in experiences
        ],
        "stable_summaries": summaries,
        "active_context_counts": storage.convergence_pressure(agent_id),
        "guidance": (
            "这些是 Agent 的内部状态，不是必须播报的通知。"
            "待分享内容必须经过 share_plan 或 share_check 的二次判断；"
            "宿主表达后应回报 used、deferred 或 discarded。"
        ),
        "revision": agent["revision"],
        "updated_at": agent["updated_at"],
    }


def model_readiness(settings: Settings) -> dict[str, Any]:
    if settings.backend == "fake":
        return {"ready": False, "message": "当前是测试模型，不能用于正式后台。"}
    if settings.backend in {"openai_compatible", "local"} and any(
        host in settings.base_url for host in ("127.0.0.1", "localhost")
    ):
        try:
            with urllib.request.urlopen(
                f"{settings.base_url.rstrip('/')}/models", timeout=3
            ) as response:
                models = {
                    item.get("id")
                    for item in json.loads(response.read().decode("utf-8")).get(
                        "data", []
                    )
                }
            missing = [
                model
                for model in (settings.light_model, settings.deep_model)
                if model not in models
            ]
            if missing:
                return {
                    "ready": False,
                    "message": f"本地模型尚未安装：{', '.join(missing)}",
                    "available_models": sorted(model for model in models if model),
                }
        except Exception as exc:
            return {"ready": False, "message": f"本地模型服务不可用：{exc}"}
    if settings.backend == "anthropic_compatible" and not settings.api_key:
        return {"ready": False, "message": "尚未配置模型密钥。"}
    return {
        "ready": True,
        "message": "模型已配置。",
        "backend": settings.backend,
        "light_model": settings.light_model,
        "deep_model": settings.deep_model,
    }


def system_status(
    storage: Storage, settings: Settings | None = None
) -> dict[str, Any]:
    result = {
        "stats": storage.stats(),
        "agents": storage.list_agents(),
        "daemon": storage.get_service_state("daemon.status", {"status": "unknown"}),
        "heartbeat": storage.get_service_state("daemon.heartbeat"),
    }
    if settings:
        result["model"] = model_readiness(settings)
    return result
