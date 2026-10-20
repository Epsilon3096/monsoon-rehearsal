"""Frozen synthetic reference case; never a surveyed township or rainfall forecast."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "reference_case.json"


def load_case() -> dict:
    case = json.loads(DATA.read_text(encoding="utf-8"))
    case["case_sha256"] = hashlib.sha256(DATA.read_bytes()).hexdigest()
    return copy.deepcopy(case)


def get_scenario(scenario_id: str) -> dict:
    for scenario in load_case()["scenarios"]:
        if scenario["id"] == scenario_id:
            return scenario
    raise ValueError(f"Unknown scenario: {scenario_id}")
