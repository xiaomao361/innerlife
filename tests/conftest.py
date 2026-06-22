from __future__ import annotations

import json
from pathlib import Path

import pytest

from innerlife.config import PROJECT_ROOT
from innerlife.storage import Storage


def load_profile(agent_id: str) -> dict:
    profile = json.loads(
        (PROJECT_ROOT / "profiles" / "example-agent.json").read_text(encoding="utf-8")
    )
    profile["agent_id"] = agent_id
    profile["display_name"] = agent_id.replace("-", " ").title()
    profile["identity"]["self_description"] = f"I am {profile['display_name']}."
    profile["boundaries"]["memory_namespace"] = f"agent/{agent_id}"
    profile["boundaries"]["can_access_users"] = ["user-1"]
    for index, source in enumerate(profile["autonomous_sources"], start=1):
        source["id"] = f"{agent_id}-source-{index}"
    return profile


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    store = Storage(tmp_path / "innerlife.db")
    store.init_db()
    store.create_agent(load_profile("agent-a"))
    store.create_agent(load_profile("agent-b"))
    return store
