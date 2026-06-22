from __future__ import annotations

import json
from pathlib import Path

import pytest

from innerlife.config import PROJECT_ROOT
from innerlife.storage import Storage


def load_profile(agent_id: str) -> dict:
    return json.loads(
        (PROJECT_ROOT / "profiles" / f"{agent_id}.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    store = Storage(tmp_path / "innerlife.db")
    store.init_db()
    store.create_agent(load_profile("clara"))
    store.create_agent(load_profile("lara"))
    return store
