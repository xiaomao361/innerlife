from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from innerlife.config import Settings
from innerlife.autonomous import AutonomousExperienceEngine
from innerlife.convergence import ConvergenceEngine
from innerlife.digest import run_from_settings
from innerlife.service import get_briefing, system_status
from innerlife.session import SessionLifecycle
from innerlife.storage import Storage

app = FastAPI(title="InnerLife", version="2.3.0")
STATIC_DIR = SERVER_DIR / "static"


def store() -> Storage:
    storage = Storage(Settings.from_env().db_path)
    storage.init_db()
    return storage


class EventRequest(BaseModel):
    source_type: str
    source_id: str | None = None
    content: dict[str, Any]


class DigestRequest(BaseModel):
    mode: str = "light"


class ShareRequest(BaseModel):
    status: str
    reason: str | None = None


class SessionStartRequest(BaseModel):
    user_id: str
    host: str
    external_session_id: str | None = None


class SessionEndRequest(BaseModel):
    conversation: dict[str, Any]
    process_now: bool = True


class ShareCheckRequest(BaseModel):
    conversation_context: dict[str, Any]


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
async def status():
    return system_status(store(), Settings.from_env())


@app.get("/api/agents")
async def agents():
    return {"agents": store().list_agents()}


@app.get("/api/agents/{agent_id}/briefing")
async def briefing(agent_id: str):
    try:
        return get_briefing(store(), agent_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/agents/{agent_id}/inbox")
async def inbox(
    agent_id: str,
    status: str | None = None,
    limit: int = Query(default=100, le=500),
):
    return {"events": store().list_inbox(agent_id, status, limit)}


@app.get("/api/agents/{agent_id}/history")
async def history(
    agent_id: str,
    limit: int = Query(default=50, le=500),
    include_archived: bool = False,
):
    return {
        "events": store().recent_internal_events(
            agent_id, limit, include_archived
        )
    }


@app.get("/api/agents/{agent_id}/runs")
async def runs(agent_id: str):
    return {"runs": store().digest_runs(agent_id)}


@app.post("/api/agents/{agent_id}/events")
async def submit_event(agent_id: str, request: EventRequest):
    try:
        return store().submit_event(
            agent_id, request.source_type, request.source_id, request.content
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/digest")
async def digest(agent_id: str, request: DigestRequest):
    try:
        return run_from_settings(
            agent_id, request.mode, Settings.from_env()
        ).to_dict()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/shares/{share_id}")
async def mark_share(agent_id: str, share_id: str, request: ShareRequest):
    try:
        return store().update_share_status(
            share_id, agent_id, request.status, request.reason
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/sessions/start")
async def session_start(agent_id: str, request: SessionStartRequest):
    try:
        settings = Settings.from_env()
        return SessionLifecycle(store(), settings).start(
            agent_id=agent_id,
            user_id=request.user_id,
            host=request.host,
            external_session_id=request.external_session_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/sessions/{session_id}/end")
async def session_end(agent_id: str, session_id: str, request: SessionEndRequest):
    try:
        settings = Settings.from_env()
        return SessionLifecycle(store(), settings).end(
            session_id=session_id,
            agent_id=agent_id,
            conversation=request.conversation,
            process_now=request.process_now,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/sessions/{session_id}/shares/check")
async def share_check(
    agent_id: str, session_id: str, request: ShareCheckRequest
):
    try:
        settings = Settings.from_env()
        return SessionLifecycle(store(), settings).check_shares(
            session_id=session_id,
            agent_id=agent_id,
            conversation_context=request.conversation_context,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/agents/{agent_id}/sessions")
async def sessions(agent_id: str, limit: int = Query(default=50, le=500)):
    return {"sessions": store().list_sessions(agent_id, limit)}


@app.post("/api/agents/{agent_id}/explore")
async def explore(agent_id: str):
    try:
        settings = Settings.from_env()
        return AutonomousExperienceEngine(store(), settings).explore(agent_id)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/agents/{agent_id}/experiences")
async def experiences(
    agent_id: str,
    limit: int = Query(default=50, le=500),
    include_archived: bool = False,
):
    return {
        "experiences": store().list_autonomous_experiences(
            agent_id, limit, include_archived
        )
    }


@app.get("/api/agents/{agent_id}/explorations")
async def explorations(agent_id: str, limit: int = Query(default=50, le=500)):
    return {"explorations": store().list_exploration_runs(agent_id, limit)}


@app.get("/api/agents/{agent_id}/sources")
async def sources(agent_id: str):
    return {"sources": store().list_sources(agent_id, False)}


@app.get("/api/agents/{agent_id}/share-actions")
async def share_actions(
    agent_id: str,
    share_id: str | None = None,
    limit: int = Query(default=100, le=500),
):
    return {"actions": store().share_actions(agent_id, share_id, limit)}


@app.post("/api/agents/{agent_id}/converge")
async def converge(agent_id: str, force: bool = False):
    try:
        settings = Settings.from_env()
        return ConvergenceEngine(store(), settings).run(agent_id, force=force)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/agents/{agent_id}/summaries")
async def summaries(agent_id: str, limit: int = Query(default=20, le=200)):
    return {"summaries": store().list_inner_summaries(agent_id, limit)}


@app.get("/api/agents/{agent_id}/convergence-runs")
async def convergence_runs(
    agent_id: str, limit: int = Query(default=50, le=500)
):
    storage = store()
    return {
        "runs": storage.list_convergence_runs(agent_id, limit),
        "pressure": storage.convergence_pressure(agent_id),
    }


def main():
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
