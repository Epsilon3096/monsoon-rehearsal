"""Reporting and immutable-study checks; no hydraulic engine is invoked."""
from copy import deepcopy
import json

import pytest

from monsoon import policy_evaluation as evaluation
from monsoon import observed_policy as observed
from monsoon.observed_policy import METHODS, load_protocol


def rows_for(case_id, **overrides):
    rows = []
    for method in METHODS:
        row = {"scenario_id": case_id, "method": method, "status": "supported", "total_spill_m3": 10.,
               "reference_spill_m3": 10., "abstained": False, "duration_overrun": False,
               "deadline_failure": False}
        row.update(deepcopy(overrides) if method != "no_work" else {})
        if method == "no_work":
            row["abstained"] = True
        rows.append(row)
    return rows


def test_report_keeps_abstentions_ties_failures_and_overruns_distinct():
    rows = (rows_for("positive", total_spill_m3=5) + rows_for("tie", total_spill_m3=10.03)
            + rows_for("harmful_prefix", total_spill_m3=5, status="inadmissible")
            + rows_for("abstained", abstained=True)
            + rows_for("overrun", status="unresolved", total_spill_m3=None, duration_overrun=True))
    summary = evaluation.outcome_summary(rows, .05)
    for method in set(METHODS) - {"no_work"}:
        value = summary["by_method"][method]
        assert value["exclusive_outcomes"] == {"positive": 1, "tie": 1, "loss": 1, "abstention": 1, "unresolved": 1}
        assert value["paired_outcomes_including_abstention_ties"]["tie"] == 2
        assert value["duration_overrun_rows"] == 1
        assert sum(value["exclusive_outcomes"].values()) == value["event_rows"]
    assert summary["by_method"]["no_work"]["exclusive_outcomes"]["tie"] == 5
    assert summary["by_method"]["no_work"]["abstention_rows"] == 5


def test_freeze_cannot_be_overwritten_and_detects_source_change(tmp_path, monkeypatch):
    protocol = load_protocol()
    monkeypatch.setattr(evaluation, "engine_info", lambda: {"fixture": "no engine"})
    monkeypatch.setattr(evaluation, "source_fingerprints", lambda: {"example.py": "original"})
    frozen = evaluation.freeze_experiment(protocol, tmp_path)
    assert evaluation.validate_freeze(protocol, tmp_path) == frozen
    with pytest.raises(FileExistsError):
        evaluation.freeze_experiment(protocol, tmp_path)
    monkeypatch.setattr(evaluation, "source_fingerprints", lambda: {"example.py": "modified"})
    with pytest.raises(ValueError, match="Source or protocol differs"):
        evaluation.validate_freeze(protocol, tmp_path)


def test_altered_freeze_record_cannot_revalidate(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "engine_info", lambda: {"fixture": "no engine"})
    protocol = load_protocol()
    frozen = evaluation.freeze_experiment(protocol, tmp_path)
    frozen["statement"] = "altered"
    (tmp_path / "policy-freeze.json").write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(ValueError, match="freeze record was altered"):
        evaluation.validate_freeze(protocol, tmp_path)


def test_prespecified_computation_cap_leaves_missing_evidence_unresolved(tmp_path, monkeypatch):
    calls = []
    def fake(state, scenario, path):
        calls.append((state, scenario))
        return {"valid": True, "fixture": "arithmetic only"}
    monkeypatch.setattr(evaluation, "checked_state", fake)
    cache = evaluation.CheckedCache(tmp_path, 1)
    a = {"hydraulic": {"synthetic_input": 1}}
    b = {"hydraulic": {"synthetic_input": 2}}
    assert cache([], a) == cache([], a)
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="budget exhausted"):
        cache([], b)
    assert len(calls) == 1


def test_sealed_future_inputs_cannot_change_selected_policies(monkeypatch):
    # The protocol hash commits the entire experiment. Choices must depend on
    # its declared development projection, never on the sealed future rows.
    class ArithmeticEvidence:
        def __init__(self, case, callback):
            self.cache = {}
            self.settings = {"deadline_minutes": case["default_deadline_minutes"],
                             "travel_minutes": case["travel_minutes"], "already_completed": [],
                             "start_minute": 0, "start_location": "DEPOT"}

        def compare(self, state, scenario):
            return {"status": "passed", "total_spill_m3": 100 - 10 * len(state)}

    monkeypatch.setattr(observed, "_Evidence", ArithmeticEvidence)
    case, protocol = evaluation.load_case(), load_protocol()
    changed = deepcopy(protocol)
    for event in changed["evaluation_events"]:
        event["hydraulic"]["peak_a_cms"] = 999
        event["durations"] = {j["id"]: 1 for j in case["jobs"]}
    changed["protocol_sha256"] = observed.fingerprint({k: v for k, v in changed.items() if k != "protocol_sha256"})
    a = observed.freeze_observed_policy(case, protocol["observations"]["LOW"], None, None, protocol)
    b = observed.freeze_observed_policy(case, changed["observations"]["LOW"], None, None, changed)
    assert a["policies"] == b["policies"]
    assert a["screening_table"] == b["screening_table"]
    assert a["candidate_scores"] == b["candidate_scores"]


def test_evaluation_hydraulic_tuples_are_separate_from_development():
    case, protocol = evaluation.load_case(), load_protocol()
    development = set()
    for key in ("LOW", "HIGH"):
        development.update(observed.fingerprint(row["hydraulic"]) for row in
                           observed.condition_development(case, protocol["observations"][key], protocol))
    realised = [observed.fingerprint(row["hydraulic"]) for row in protocol["evaluation_events"]]
    assert not development.intersection(realised)
    assert len(realised) == len(set(realised))
