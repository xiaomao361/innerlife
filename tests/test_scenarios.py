from __future__ import annotations

from innerlife.config import PROJECT_ROOT
from innerlife.scenarios import run_scenarios


def test_all_phase0_scenarios_pass():
    result = run_scenarios(PROJECT_ROOT / "scenarios" / "phase0_cases.jsonl")
    assert result["ok"], result
    assert result["passed"] == 9
    assert result["total"] == 9
