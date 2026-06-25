from __future__ import annotations

import argparse
import signal
import time
from datetime import datetime, timezone
from threading import Event
from typing import Any

from .config import Settings
from .autonomous import AutonomousExperienceEngine
from .convergence import ConvergenceEngine
from .digest import DigestEngine, make_backend
from .integrations import sync_continuity, sync_memoria
from .sharing import ShareScheduler
from .storage import Storage, utc_now


def _seconds_since(timestamp: str | None) -> float:
    if not timestamp:
        return float("inf")
    value = datetime.fromisoformat(timestamp)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value).total_seconds())


def _is_future(timestamp: str | None) -> bool:
    if not timestamp:
        return False
    value = datetime.fromisoformat(timestamp)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value > datetime.now(timezone.utc)


class InnerLifeDaemon:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.storage.init_db()
        self.backend = make_backend(settings)
        self.engine = DigestEngine(self.storage, self.backend)
        self.autonomous = AutonomousExperienceEngine(
            self.storage, settings, self.backend
        )
        self.convergence = ConvergenceEngine(
            self.storage, settings, self.backend
        )
        self.shares = ShareScheduler(self.storage, settings, self.backend)
        self.stop_event = Event()

    def stop(self, *_: Any) -> None:
        self.stop_event.set()

    def sync_sources(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for agent_id in self.settings.memoria_sync_agents:
            results.append(
                sync_memoria(
                    self.storage,
                    self.settings.memoria_db_path,
                    agent_id,
                    bootstrap_from_now=True,
                )
            )
        for agent_id in self.settings.continuity_sync_agents:
            results.append(
                sync_continuity(
                    self.storage,
                    self.settings.continuity_db_path,
                    agent_id,
                    bootstrap_from_now=True,
                )
            )
        return results

    def process_once(self) -> dict[str, Any]:
        sync_results = self.sync_sources()
        processed: list[dict[str, Any]] = []
        deliveries: list[dict[str, Any]] = []
        explorations: list[dict[str, Any]] = []
        convergences: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for agent in self.storage.list_agents():
            agent_id = agent["agent_id"]
            self.storage.expire_pending_shares(agent_id)
            retry = self.storage.get_service_state(
                f"daemon.retry.{agent_id}", {"failures": 0, "retry_after": None}
            )
            retry_after = retry.get("retry_after")
            if _is_future(retry_after):
                continue
            pending = self.storage.pending_events(agent_id)
            latest = self.storage.latest_digest(agent_id)
            state = self.storage.get_agent(agent_id)["state"]
            mode: str | None = None
            if pending:
                mode = "light"
            elif any(
                isinstance(loop, dict) and loop.get("status", "open") == "open"
                for loop in state.get("open_loops", [])
            ):
                idle = _seconds_since(latest["created_at"] if latest else None)
                if idle >= self.settings.deep_idle_seconds:
                    mode = "deep"
                elif idle >= self.settings.light_idle_seconds:
                    mode = "light"
            if not mode:
                continue
            try:
                result = self.engine.run(
                    agent_id, mode, self.settings.model_for(mode)
                ).to_dict()
                processed.append(result)
                self.storage.set_service_state(
                    f"daemon.retry.{agent_id}",
                    {"failures": 0, "retry_after": None},
                )
            except Exception as exc:
                errors.append({"agent_id": agent_id, "error": str(exc)})
                failures = int(retry.get("failures", 0)) + 1
                delay = min(3600, 30 * (2 ** min(failures - 1, 7)))
                retry_time = datetime.fromtimestamp(
                    time.time() + delay, timezone.utc
                ).isoformat()
                self.storage.set_service_state(
                    f"daemon.retry.{agent_id}",
                    {
                        "failures": failures,
                        "retry_after": retry_time,
                        "last_error": str(exc),
                    },
                )
        for agent in self.storage.list_agents():
            agent_id = agent["agent_id"]
            try:
                queued = self.shares.evaluate_delivery(agent_id)
                if queued:
                    deliveries.append(
                        {"agent_id": agent_id, "queued": len(queued)}
                    )
            except Exception as exc:
                errors.append(
                    {"agent_id": agent_id, "stage": "delivery", "error": str(exc)}
                )
        if self.settings.autonomy_enabled:
            day_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()
            for agent in self.storage.list_agents():
                agent_id = agent["agent_id"]
                profile = self.storage.get_agent(agent_id)["profile"]
                autonomy = profile.get("autonomy") or {}
                if not autonomy.get("enabled", False):
                    continue
                if self.storage.active_session_count(agent_id):
                    continue
                max_daily = int(autonomy.get("max_explorations_per_day", 1))
                if self.storage.exploration_count_since(agent_id, day_start) >= max_daily:
                    continue
                latest_exploration = self.storage.latest_exploration(agent_id)
                min_seconds = float(autonomy.get("min_interval_hours", 24)) * 3600
                if latest_exploration and _seconds_since(
                    latest_exploration["created_at"]
                ) < min_seconds:
                    continue
                try:
                    explorations.append(self.autonomous.explore(agent_id))
                except Exception as exc:
                    errors.append(
                        {"agent_id": agent_id, "stage": "autonomous", "error": str(exc)}
                    )
        for agent in self.storage.list_agents():
            agent_id = agent["agent_id"]
            if self.storage.active_session_count(agent_id):
                continue
            if self.storage.pending_events(agent_id):
                continue
            if not self.convergence.needs_run(agent_id):
                continue
            policy = self.convergence.policy(agent_id)
            latest_runs = self.storage.list_convergence_runs(agent_id, 1)
            if latest_runs and _seconds_since(latest_runs[0]["created_at"]) < (
                float(policy["min_interval_hours"]) * 3600
            ):
                continue
            try:
                convergences.append(self.convergence.run(agent_id))
            except Exception as exc:
                errors.append(
                    {"agent_id": agent_id, "stage": "convergence", "error": str(exc)}
                )
        heartbeat = {
            "pid": __import__("os").getpid(),
            "time": utc_now(),
            "backend": self.settings.backend,
            "models": {
                "light": self.settings.light_model,
                "deep": self.settings.deep_model,
            },
            "sync": sync_results,
            "processed": len(processed),
            "deliveries": len(deliveries),
            "explorations": len(explorations),
            "convergences": len(convergences),
            "errors": errors,
        }
        self.storage.set_service_state("daemon.heartbeat", heartbeat)
        return {
            "heartbeat": heartbeat,
            "results": processed,
            "deliveries": deliveries,
            "explorations": explorations,
            "convergences": convergences,
        }

    def run(self, once: bool = False) -> int:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.storage.set_service_state(
            "daemon.status", {"status": "running", "started_at": utc_now()}
        )
        try:
            while not self.stop_event.is_set():
                self.process_once()
                if once:
                    break
                self.stop_event.wait(self.settings.poll_seconds)
            return 0
        finally:
            self.storage.set_service_state(
                "daemon.status", {"status": "stopped", "stopped_at": utc_now()}
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="innerlife-daemon")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    return InnerLifeDaemon(Settings.from_env()).run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
