from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .autonomous import AutonomousExperienceEngine
from .digest import run_from_settings
from .daemon import InnerLifeDaemon, ensure_default_agents
from .integrations import sync_continuity, sync_memoria
from .models import InnerLifeError, ValidationError
from .scenarios import run_scenarios
from .service import get_briefing, model_readiness, system_status
from .session import SessionLifecycle
from .storage import Storage


def _read_object(path: str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text.strip()}
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object or plain text")
    return value


def _print(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{key}: {json.dumps(item, ensure_ascii=False)}")
            else:
                print(f"{key}: {item}")
    else:
        print(value)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Output JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="innerlife")
    sub = parser.add_subparsers(dest="command", required=True)

    init_db = sub.add_parser("init-db")
    _add_json_flag(init_db)

    create = sub.add_parser("create-agent")
    create.add_argument("--profile", required=True)
    _add_json_flag(create)

    submit = sub.add_parser("submit-event")
    submit.add_argument("--agent", required=True)
    submit.add_argument(
        "--type",
        required=True,
        choices=["memoria_fact", "continuity_position", "afterthought"],
    )
    submit.add_argument("--source")
    submit.add_argument("--content-file", required=True)
    submit.add_argument("--event-id")
    submit.add_argument("--created-at")
    _add_json_flag(submit)

    digest = sub.add_parser("digest")
    digest.add_argument("--agent", required=True)
    digest.add_argument("--mode", choices=["light", "deep"], default="light")
    _add_json_flag(digest)

    state = sub.add_parser("state")
    state.add_argument("--agent", required=True)
    _add_json_flag(state)

    history = sub.add_parser("history")
    history.add_argument("--agent", required=True)
    history.add_argument("--limit", type=int, default=50)
    _add_json_flag(history)

    pending = sub.add_parser("pending")
    pending.add_argument("--agent", required=True)
    _add_json_flag(pending)

    runs = sub.add_parser("runs")
    runs.add_argument("--agent", required=True)
    _add_json_flag(runs)

    briefing = sub.add_parser("briefing")
    briefing.add_argument("--agent", required=True)
    _add_json_flag(briefing)

    inbox = sub.add_parser("inbox")
    inbox.add_argument("--agent", required=True)
    inbox.add_argument("--status")
    inbox.add_argument("--limit", type=int, default=100)
    _add_json_flag(inbox)

    mark = sub.add_parser("mark-share")
    mark.add_argument("--agent", required=True)
    mark.add_argument("--share-id", required=True)
    mark.add_argument(
        "--status", required=True, choices=["used", "deferred", "discarded"]
    )
    mark.add_argument("--reason")
    _add_json_flag(mark)

    daemon = sub.add_parser("daemon")
    daemon.add_argument("--once", action="store_true")
    _add_json_flag(daemon)

    sync_mem = sub.add_parser("sync-memoria")
    sync_mem.add_argument("--agent", required=True)
    sync_mem.add_argument("--limit", type=int, default=100)
    sync_mem.add_argument("--bootstrap-from-now", action="store_true")
    _add_json_flag(sync_mem)

    sync_con = sub.add_parser("sync-continuity")
    sync_con.add_argument("--agent", required=True)
    sync_con.add_argument("--limit", type=int, default=50)
    sync_con.add_argument("--bootstrap-from-now", action="store_true")
    _add_json_flag(sync_con)

    doctor = sub.add_parser("doctor")
    _add_json_flag(doctor)

    backup = sub.add_parser("backup")
    backup.add_argument("--output", required=True)
    _add_json_flag(backup)

    session_start = sub.add_parser("session-start")
    session_start.add_argument("--agent", required=True)
    session_start.add_argument("--user", default="zhouwei")
    session_start.add_argument("--host", required=True)
    session_start.add_argument("--external-session-id")
    _add_json_flag(session_start)

    session_end = sub.add_parser("session-end")
    session_end.add_argument("--agent", required=True)
    session_end.add_argument("--session-id", required=True)
    session_end.add_argument("--conversation-file", required=True)
    session_end.add_argument("--no-process", action="store_true")
    _add_json_flag(session_end)

    sessions = sub.add_parser("sessions")
    sessions.add_argument("--agent", required=True)
    sessions.add_argument("--limit", type=int, default=50)
    _add_json_flag(sessions)

    explore = sub.add_parser("explore")
    explore.add_argument("--agent", required=True)
    explore.add_argument("--no-process", action="store_true")
    _add_json_flag(explore)

    sources = sub.add_parser("sources")
    sources.add_argument("--agent", required=True)
    _add_json_flag(sources)

    source_add = sub.add_parser("source-add")
    source_add.add_argument("--agent", required=True)
    source_add.add_argument("--name", required=True)
    source_add.add_argument("--url", required=True)
    source_add.add_argument("--type", default="rss", choices=["rss", "webpage"])
    _add_json_flag(source_add)

    experiences = sub.add_parser("experiences")
    experiences.add_argument("--agent", required=True)
    experiences.add_argument("--limit", type=int, default=50)
    _add_json_flag(experiences)

    explorations = sub.add_parser("explorations")
    explorations.add_argument("--agent", required=True)
    explorations.add_argument("--limit", type=int, default=50)
    _add_json_flag(explorations)

    scenarios = sub.add_parser("run-scenarios")
    scenarios.add_argument("path")
    _add_json_flag(scenarios)

    return parser


def execute(args: argparse.Namespace, settings: Settings) -> Any:
    storage = Storage(settings.db_path)
    storage.init_db()
    if args.command == "init-db":
        return storage.init_db()
    if args.command == "create-agent":
        return storage.create_agent(_read_object(args.profile))
    if args.command == "submit-event":
        return storage.submit_event(
            args.agent,
            args.type,
            args.source,
            _read_object(args.content_file),
            event_id=args.event_id,
            created_at=args.created_at,
        )
    if args.command == "digest":
        return run_from_settings(args.agent, args.mode, settings).to_dict()
    if args.command == "state":
        return storage.get_agent(args.agent)
    if args.command == "history":
        return {
            "agent_id": args.agent,
            "internal_events": storage.recent_internal_events(args.agent, args.limit),
        }
    if args.command == "pending":
        return {
            "agent_id": args.agent,
            "pending_shares": storage.pending_shares(args.agent),
        }
    if args.command == "runs":
        return {"agent_id": args.agent, "digest_runs": storage.digest_runs(args.agent)}
    if args.command == "briefing":
        return get_briefing(storage, args.agent)
    if args.command == "inbox":
        return {
            "agent_id": args.agent,
            "events": storage.list_inbox(args.agent, args.status, args.limit),
        }
    if args.command == "mark-share":
        return storage.update_share_status(
            args.share_id, args.agent, args.status, args.reason
        )
    if args.command == "daemon":
        result = InnerLifeDaemon(settings).process_once() if args.once else None
        if args.once:
            return result
        return InnerLifeDaemon(settings).run()
    if args.command == "sync-memoria":
        return sync_memoria(
            storage,
            settings.memoria_db_path,
            args.agent,
            limit=args.limit,
            bootstrap_from_now=args.bootstrap_from_now,
        )
    if args.command == "sync-continuity":
        return sync_continuity(
            storage,
            settings.continuity_db_path,
            args.agent,
            limit=args.limit,
            bootstrap_from_now=args.bootstrap_from_now,
        )
    if args.command == "doctor":
        storage.init_db()
        ensure_default_agents(storage)
        status = system_status(storage, settings)
        status["configuration"] = {
            "root": str(settings.root),
            "backend": settings.backend,
            "light_model": settings.light_model,
            "deep_model": settings.deep_model,
            "memoria_db_exists": settings.memoria_db_path.exists(),
            "continuity_db_exists": settings.continuity_db_path.exists(),
            "memoria_sync_agents": settings.memoria_sync_agents,
            "continuity_sync_agents": settings.continuity_sync_agents,
        }
        readiness = model_readiness(settings)
        warnings = [] if readiness["ready"] else [readiness["message"]]
        status["warnings"] = warnings
        return status
    if args.command == "backup":
        return storage.backup(args.output)
    if args.command == "session-start":
        return SessionLifecycle(storage, settings).start(
            agent_id=args.agent,
            user_id=args.user,
            host=args.host,
            external_session_id=args.external_session_id,
        )
    if args.command == "session-end":
        return SessionLifecycle(storage, settings).end(
            session_id=args.session_id,
            agent_id=args.agent,
            conversation=_read_object(args.conversation_file),
            process_now=not args.no_process,
        )
    if args.command == "sessions":
        return {
            "agent_id": args.agent,
            "sessions": storage.list_sessions(args.agent, args.limit),
        }
    if args.command == "explore":
        return AutonomousExperienceEngine(storage, settings).explore(
            args.agent, process_now=not args.no_process
        )
    if args.command == "sources":
        return {"agent_id": args.agent, "sources": storage.list_sources(args.agent, False)}
    if args.command == "source-add":
        return storage.add_source(args.agent, args.name, args.url, args.type)
    if args.command == "experiences":
        return {
            "agent_id": args.agent,
            "experiences": storage.list_autonomous_experiences(args.agent, args.limit),
        }
    if args.command == "explorations":
        return {
            "agent_id": args.agent,
            "explorations": storage.list_exploration_runs(args.agent, args.limit),
        }
    if args.command == "run-scenarios":
        result = run_scenarios(args.path)
        if not result["ok"]:
            raise ValidationError(
                f"Only {result['passed']} of {result['total']} scenarios passed"
            )
        return result
    raise ValidationError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args, Settings.from_env())
        _print(result, getattr(args, "json", False))
        return 0
    except (InnerLifeError, OSError, json.JSONDecodeError) as exc:
        error = {"ok": False, "error": str(exc)}
        if getattr(args, "json", False):
            print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
