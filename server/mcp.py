#!/usr/bin/env python
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path = [
    path for path in sys.path if path and Path(path).resolve() != SERVER_DIR
]
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from innerlife.config import Settings
from innerlife.autonomous import AutonomousExperienceEngine
from innerlife.digest import run_from_settings
from innerlife.service import get_briefing, system_status
from innerlife.session import SessionLifecycle
from innerlife.storage import Storage

server = Server("innerlife", version="2.1.0")


def _agent(arguments: dict) -> str:
    agent_id = (arguments.get("agent_id") or os.environ.get("INNERLIFE_AGENT_ID", "")).strip()
    if not agent_id:
        raise ValueError(
            "agent_id required. Pass agent_id or set INNERLIFE_AGENT_ID."
        )
    return agent_id


def _json(value) -> list[TextContent]:
    return [
        TextContent(
            type="text", text=json.dumps(value, ensure_ascii=False, indent=2)
        )
    ]


TOOLS = [
    Tool(
        name="innerlife_explore",
        description="手动触发一次 Agent 自主经历探索。正常由后台调度；排查或明确要求时使用。",
        inputSchema={
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
        },
    ),
    Tool(
        name="innerlife_experiences",
        description="查看 Agent 已真实形成的自主经历及外部来源证据。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="innerlife_session_start",
        description="开始一次正式会话并返回进入时的内部状态。每个宿主会话开始时调用一次；相同 external_session_id 重复调用不会重复创建。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "user_id": {"type": "string"},
                "host": {"type": "string"},
                "external_session_id": {"type": "string"},
            },
            "required": ["user_id", "host", "external_session_id"],
        },
    ),
    Tool(
        name="innerlife_session_end",
        description="结束一次正式会话。提交实际对话内容后，InnerLife 自动判断是否有余韵、完成消化并关闭会话；不要由宿主自行编造 afterthought。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "session_id": {"type": "string"},
                "conversation": {"type": "object"},
                "process_now": {"type": "boolean", "default": True},
            },
            "required": ["session_id", "conversation"],
        },
    ),
    Tool(
        name="innerlife_sessions",
        description="查看 Agent 最近的 InnerLife 会话及闭环结果。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="innerlife_briefing",
        description="读取 Agent 当前内部状态、未完成问题、最近变化和待分享念头。不要机械播报。",
        inputSchema={
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
        },
    ),
    Tool(
        name="innerlife_record_afterthought",
        description="对话结束时提交 Agent 明确留下的余韵。只提交真实形成的感受、疑问或未完成问题。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "source_session": {"type": "string"},
                "conversation_summary": {"type": "string"},
                "agent_afterthought": {"type": "string"},
                "open_loops": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["source_session", "agent_afterthought"],
        },
    ),
    Tool(
        name="innerlife_submit_fact",
        description="显式提交一条可观察事实作为消化材料。事实本身仍属于 Memoria。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "source_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["source_id", "content"],
        },
    ),
    Tool(
        name="innerlife_submit_continuity",
        description="显式提交当前共同线位置作为消化材料。它是当前位置，不是客观事实。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "thread_id": {"type": "string"},
                "position": {"type": "string"},
                "next_step": {"type": "string"},
                "boundary_notes": {"type": "string"},
            },
            "required": ["thread_id", "position"],
        },
    ),
    Tool(
        name="innerlife_digest",
        description="手动触发一次内部消化。通常由后台自动处理；排查或明确要求时使用。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "mode": {"type": "string", "enum": ["light", "deep"], "default": "light"},
            },
        },
    ),
    Tool(
        name="innerlife_pending_shares",
        description="读取 Agent 尚未使用的待分享念头。可以返回空列表。",
        inputSchema={
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
        },
    ),
    Tool(
        name="innerlife_mark_share",
        description="将待分享念头标记为已使用、延后或放弃。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "share_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["used", "deferred", "discarded"],
                },
                "reason": {"type": "string"},
            },
            "required": ["share_id", "status"],
        },
    ),
    Tool(
        name="innerlife_history",
        description="查看 Agent 最近的内部变化历史及来源。",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    ),
    Tool(
        name="innerlife_status",
        description="查看 InnerLife 服务、Agent、排队内容和后台心跳状态。",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def list_tools():
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    settings = Settings.from_env()
    storage = Storage(settings.db_path)
    storage.init_db()
    try:
        if name == "innerlife_explore":
            result = AutonomousExperienceEngine(storage, settings).explore(
                _agent(arguments)
            )
        elif name == "innerlife_experiences":
            result = storage.list_autonomous_experiences(
                _agent(arguments), int(arguments.get("limit", 20))
            )
        elif name == "innerlife_session_start":
            result = SessionLifecycle(storage, settings).start(
                agent_id=_agent(arguments),
                user_id=arguments["user_id"],
                host=arguments["host"],
                external_session_id=arguments["external_session_id"],
            )
        elif name == "innerlife_session_end":
            result = SessionLifecycle(storage, settings).end(
                session_id=arguments["session_id"],
                agent_id=_agent(arguments),
                conversation=arguments["conversation"],
                process_now=arguments.get("process_now", True),
            )
        elif name == "innerlife_sessions":
            result = storage.list_sessions(
                _agent(arguments), int(arguments.get("limit", 20))
            )
        elif name == "innerlife_briefing":
            result = get_briefing(storage, _agent(arguments))
        elif name == "innerlife_record_afterthought":
            agent_id = _agent(arguments)
            result = storage.submit_event(
                agent_id,
                "afterthought",
                arguments["source_session"],
                {
                    "conversation_summary": arguments.get("conversation_summary", ""),
                    "text": arguments["agent_afterthought"],
                    "open_loops": arguments.get("open_loops", []),
                },
            )
        elif name == "innerlife_submit_fact":
            agent_id = _agent(arguments)
            result = storage.submit_event(
                agent_id,
                "memoria_fact",
                arguments["source_id"],
                {"text": arguments["content"]},
                event_id=f"memoria_{agent_id}_{arguments['source_id']}",
            )
        elif name == "innerlife_submit_continuity":
            agent_id = _agent(arguments)
            result = storage.submit_event(
                agent_id,
                "continuity_position",
                arguments["thread_id"],
                {
                    "position": arguments["position"],
                    "next_step": arguments.get("next_step", ""),
                    "boundary_notes": arguments.get("boundary_notes", ""),
                },
            )
        elif name == "innerlife_digest":
            agent_id = _agent(arguments)
            mode = arguments.get("mode", "light")
            result = run_from_settings(agent_id, mode, settings).to_dict()
        elif name == "innerlife_pending_shares":
            result = storage.pending_shares(_agent(arguments))
        elif name == "innerlife_mark_share":
            result = storage.update_share_status(
                arguments["share_id"],
                _agent(arguments),
                arguments["status"],
                arguments.get("reason"),
            )
        elif name == "innerlife_history":
            result = storage.recent_internal_events(
                _agent(arguments), int(arguments.get("limit", 20))
            )
        elif name == "innerlife_status":
            result = system_status(storage, settings)
        else:
            result = {"error": f"unknown tool: {name}"}
        return _json(result)
    except Exception as exc:
        return _json({"error": str(exc)})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
