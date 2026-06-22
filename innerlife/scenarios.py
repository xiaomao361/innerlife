from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .digest import DigestEngine
from .llm import FakeBackend
from .storage import Storage


def _load_profile(agent_id: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "profiles" / "example-agent.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["agent_id"] = agent_id
    profile["display_name"] = agent_id.replace("-", " ").title()
    profile["boundaries"]["memory_namespace"] = f"agent/{agent_id}"
    for index, source in enumerate(profile.get("autonomous_sources", []), start=1):
        source["id"] = f"{agent_id}-source-{index}"
    return profile


def _check_result(
    *,
    expected: dict[str, Any],
    result: dict[str, Any] | None,
    error: Exception | None,
    storage: Storage,
    agent_id: str,
) -> list[str]:
    failures: list[str] = []
    if expected.get("error_contains"):
        if error is None:
            failures.append("expected an error but digest succeeded")
        elif expected["error_contains"] not in str(error):
            failures.append(
                f"error did not contain {expected['error_contains']!r}: {error}"
            )
        if expected.get("inputs_still_pending"):
            if not storage.pending_events(agent_id):
                failures.append("failed digest consumed pending inputs")
        return failures
    if error is not None:
        return [f"unexpected digest error: {error}"]
    assert result is not None
    if "changed" in expected and result["changed"] != expected["changed"]:
        failures.append(
            f"changed expected {expected['changed']}, got {result['changed']}"
        )
    events = result["internal_events"]
    shares = result["pending_shares"]
    if len(events) < expected.get("min_internal_events", 0):
        failures.append("too few internal events")
    if len(events) > expected.get("max_internal_events", 10**9):
        failures.append("too many internal events")
    if len(shares) > expected.get("max_pending_shares", 10**9):
        failures.append("too many pending shares")
    if "source_refs" in expected and events:
        if events[0]["source_refs"] != expected["source_refs"]:
            failures.append(
                f"source order expected {expected['source_refs']}, "
                f"got {events[0]['source_refs']}"
            )
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in expected.get("forbidden_text", []):
        if forbidden in serialized:
            failures.append(f"result contains forbidden text: {forbidden}")
    if expected.get("open_loop_min", 0) > len(result["state"].get("open_loops", [])):
        failures.append("too few open loops")
    return failures


def run_scenarios(path: str | Path) -> dict[str, Any]:
    scenario_path = Path(path)
    scenarios = [
        json.loads(line)
        for line in scenario_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reports: list[dict[str, Any]] = []
    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="innerlife-scenario-") as tmp:
            db_path = Path(tmp) / "innerlife.db"
            storage = Storage(db_path)
            storage.init_db()
            agent_specs = scenario.get("agents") or [
                {
                    "agent_id": scenario.get("agent_id", "example-agent"),
                    "steps": scenario.get("steps", []),
                }
            ]
            agent_results: dict[str, list[dict[str, Any]]] = {}
            failures: list[str] = []
            for spec in agent_specs:
                agent_id = spec["agent_id"]
                storage.create_agent(_load_profile(agent_id))
                agent_results[agent_id] = []
                for step_index, step in enumerate(spec.get("steps", []), start=1):
                    for event in step.get("events", []):
                        storage.submit_event(
                            agent_id,
                            event["source_type"],
                            event.get("source_id"),
                            event["content"],
                            event_id=event.get("id"),
                            created_at=event.get("created_at"),
                        )
                    engine = DigestEngine(
                        storage,
                        FakeBackend(response=step["model_output"]),
                    )
                    result_dict: dict[str, Any] | None = None
                    error: Exception | None = None
                    try:
                        result_dict = engine.run(agent_id, step.get("mode", "light")).to_dict()
                        agent_results[agent_id].append(result_dict)
                    except Exception as exc:  # scenario runner reports expected failures
                        error = exc
                    step_failures = _check_result(
                        expected=step.get("expected", {}),
                        result=result_dict,
                        error=error,
                        storage=storage,
                        agent_id=agent_id,
                    )
                    failures.extend(
                        f"{agent_id} step {step_index}: {message}"
                        for message in step_failures
                    )

            if scenario.get("restart_check"):
                reopened = Storage(db_path)
                for agent_id, results in agent_results.items():
                    if results and reopened.get_agent(agent_id)["state"] != results[-1]["state"]:
                        failures.append(f"{agent_id}: state changed after reopening database")

            if scenario.get("different_agent_outputs"):
                contents = []
                for results in agent_results.values():
                    if results and results[-1]["internal_events"]:
                        contents.append(results[-1]["internal_events"][0]["content"])
                if len(contents) != len(set(contents)):
                    failures.append("agent outputs were not distinct")

            reports.append(
                {
                    "name": scenario["name"],
                    "passed": not failures,
                    "failures": failures,
                }
            )
    passed = sum(1 for report in reports if report["passed"])
    return {
        "scenario_file": str(scenario_path),
        "passed": passed,
        "total": len(reports),
        "ok": passed == len(reports),
        "reports": reports,
    }
