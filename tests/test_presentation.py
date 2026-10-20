"""Display contracts use arithmetic gate fixtures and retained compact evidence.

No hydraulic engine, planner, validator or ticket store is run by these tests.
The supplied gate dictionaries model validator responses, not fresh approval.
"""
import builtins
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

from monsoon.presentation import audit_case_options, audit_location_rows, decision_verdict


ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sealed_fixture(queue=("J1",), cases=None):
    cases = deepcopy(cases if cases is not None else [{"scenario_id": "P1", "status": "passed", "violations": []}])
    counts = {status: sum(case["status"] == status for case in cases) for status in ("passed", "failed", "unresolved")}
    status = "unresolved" if counts["unresolved"] else "failed" if counts["failed"] else "passed"
    subject = {"queue": list(queue), "origin": "ARITHMETIC PRESENTATION FIXTURE"}
    audit = {"subject": subject, "subject_sha256": digest(subject), "status": status,
             "approval_allowed": status == "passed", "cases": cases, "counts": counts,
             "violations": [row for case in cases for row in case.get("violations", [])]}
    audit["audit_sha256"] = digest(audit)
    gate = {"valid": True, "approval_allowed": status == "passed", "status": status,
            "audit_sha256": audit["audit_sha256"], "subject_sha256": audit["subject_sha256"], "reasons": []}
    return {"queue": list(queue), "status": "supported", "admissible": True}, audit, gate


def test_candidate_acknowledges_existing_prefix_checks_without_approval():
    plan, _, _ = sealed_fixture()
    verdict = decision_verdict(plan)
    assert verdict["status"] == "candidate" and verdict["level"] == "warning"
    assert "completed-work prefixes passed" in verdict["explanation"]
    assert "outstanding" in verdict["explanation"] and "approval remain blocked" in verdict["explanation"]
    assert decision_verdict(None)["status"] == "not_rehearsed"
    assert decision_verdict({"queue": []})["level"] != "success"


@pytest.mark.parametrize("empty", [True, False])
def test_exact_pass_is_scoped_and_empty_never_claims_other_queues_or_safety(empty):
    plan, audit, gate = sealed_fixture(() if empty else ("J1",))
    verdict = decision_verdict(plan, audit, gate)
    assert verdict["status"] == ("passed_empty" if empty else "passed")
    assert verdict["level"] == "success"
    assert "approval" in verdict["explanation"]
    assert "safe abstention" not in str(verdict).lower()
    assert "all nonempty" not in str(verdict).lower()
    if empty:
        assert "baseline flood risk remains" in verdict["explanation"]
        assert "No work ticket" in verdict["explanation"]


def test_unverified_condition_and_staleness_override_a_historical_pass():
    plan, audit, gate = sealed_fixture()
    unknown = decision_verdict(plan, audit, gate, stale=True, condition_unknown=True)
    assert unknown["status"] == "condition_unknown" and unknown["level"] != "success"
    assert "unverified" in unknown["explanation"] and "blocked pending verification" in unknown["explanation"]
    assert "pre-work geometry" not in unknown["explanation"]
    assert decision_verdict(plan, audit, gate, stale=True)["status"] == "stale"


@pytest.mark.parametrize("change", [
    "missing_gate", "invalid_gate", "truthy_valid", "different_audit", "different_subject",
    "different_queue", "changed_audit", "conflicting_status", "offline", "truthy_approval",
])
def test_detached_changed_or_offline_pass_cannot_render_success(change):
    plan, audit, gate = sealed_fixture()
    if change == "missing_gate":
        gate = None
    elif change == "invalid_gate":
        gate.update(valid=False, reasons=["Raw evidence changed"])
    elif change == "truthy_valid":
        gate["valid"] = 1
    elif change == "different_audit":
        gate["audit_sha256"] = "0" * 64
    elif change == "different_subject":
        gate["subject_sha256"] = "1" * 64
    elif change == "different_queue":
        plan["queue"] = []
    elif change == "changed_audit":
        audit["cases"][0]["title"] = "Changed after validation"
    elif change == "conflicting_status":
        gate["status"] = "failed"
    elif change == "offline":
        gate.update(approval_allowed=False, reasons=["Offline inspection cannot approve work."])
    elif change == "truthy_approval":
        gate["approval_allowed"] = 1
    verdict = decision_verdict(plan, audit, gate)
    assert verdict["status"] == "invalid_evidence" and verdict["level"] != "success"
    assert "Approval blocked" in verdict["title"]


def test_unresolved_precedence_keeps_separate_resolved_harm():
    cases = [{"scenario_id": "S_STAGE", "status": "unresolved", "violations": []},
             {"scenario_id": "H1", "status": "failed", "violations": [{"node_id": "B2"}]}]
    verdict = decision_verdict(*sealed_fixture(cases=cases))
    assert verdict["status"] == "unresolved"
    assert "1 required case(s) unresolved" in verdict["title"]
    assert "Separately resolved protected-location" in verdict["explanation"]


def test_unresolved_default_violation_is_not_mislabelled_resolved_harm():
    cases = [{"scenario_id": "X", "status": "unresolved", "violations": [{"node_id": "B2"}]}]
    verdict = decision_verdict(*sealed_fixture(cases=cases))
    assert verdict["status"] == "unresolved"
    assert "Separately resolved" not in verdict["explanation"]


def test_harm_in_a_resolved_prefix_of_an_unresolved_case_stays_visible():
    cases = [{"scenario_id": "X", "status": "unresolved", "violations": [],
              "states": [{"status": "failed", "violations": [{"node_id": "B2"}]},
                         {"status": "unresolved", "violations": []}]}]
    assert "Separately resolved" in decision_verdict(*sealed_fixture(cases=cases))["explanation"]


def test_case_options_are_stable_copies_and_keep_stress_cases_separate_from_planning():
    audit = {"cases": [{"scenario_id": "P1", "status": "passed"},
                       {"scenario_id": "S_STAGE", "status": "unresolved"},
                       {"scenario_id": "H2", "status": "failed"},
                       {"scenario_id": "S_COMPOUND", "status": "failed"},
                       {"scenario_id": "P2", "status": "passed"}]}
    copied = deepcopy(audit)
    options = audit_case_options(audit)
    assert [case["scenario_id"] for case in options] == ["H2", "S_COMPOUND", "S_STAGE", "P1", "P2"]
    options[0]["title"] = "UI annotation"
    assert audit == copied
    assert audit_case_options(None) == []


def test_location_rows_keep_every_prefix_and_actual_missing_values():
    first = {"node_id": "B2", "reference_spill_m3": 3.0, "spill_m3": 4.5,
             "increase_m3": 1.5, "tolerance_m3": .05}
    second = {"node_id": "B2", "reference_spill_m3": None, "spill_m3": float("nan"),
              "increase_m3": True, "tolerance_m3": None}
    audit = {"cases": [{"scenario_id": "H1", "status": "unresolved", "states": [
        {"prefix_index": 1, "stage": "prefix", "completed_jobs": ["J2"], "status": "failed",
         "run_id": "first", "reference_run_id": "baseline", "evidence_key": "key1", "violations": [first]},
        {"prefix_index": 2, "stage": "final", "completed_jobs": ["J2", "J3"], "status": "unresolved",
         "run_id": "second", "reference_run_id": "baseline", "violations": [second]}],
        "violations": [first, second]}], "violations": [first, second]}
    rows = audit_location_rows(audit, "H1")
    assert len(rows) == 2
    assert [row["Completed jobs"] for row in rows] == ["J2", "J2, J3"]
    assert [row["Prefix"] for row in rows] == [1, 2]
    assert rows[0]["Change (m³)"] == 1.5 and rows[0]["Evidence key"] == "key1"
    assert rows[0]["Result run ID"] == "first" and rows[1]["Result run ID"] == "second"
    assert all(rows[1][column] is None for column in (
        "Baseline spill (m³)", "Resulting spill (m³)", "Change (m³)", "Limit (m³)"))
    assert audit_location_rows(audit, "unknown") == []
    json.dumps(rows, allow_nan=False)


def test_real_compact_census_keeps_h2_identity_and_unresolved_h1_prefix_harm():
    census = json.loads((ROOT / "evidence/assurance-development-census.json").read_bytes())
    robust = next(row for row in census["queues"] if row["queue"] == ["J4", "J1", "J3", "J2"])
    h2 = audit_location_rows(robust, "H2")
    assert len(h2) == 1
    assert h2[0]["Location"] == "B2" and h2[0]["Completed jobs"] == "J3, J4"
    assert h2[0]["Baseline spill (m³)"] == 280.77690219892827
    assert h2[0]["Resulting spill (m³)"] == 810.7718106724424
    assert h2[0]["Change (m³)"] == 529.9949084735141
    assert h2[0]["Limit (m³)"] == .05
    assert h2[0]["Result run ID"] == "033b27be259f641007ed48f427b6724ec8bf6bb7ad8058bc63fde57066480c58"
    uncertain = next(row for row in census["queues"] if row["queue"] == ["J2", "J1", "J3"])
    options = audit_case_options(uncertain)
    assert next(row for row in options if row["scenario_id"] == "S_STAGE")["status"] == "unresolved"
    h1 = audit_location_rows(uncertain, "H1")
    assert [(row["Completed jobs"], row["Change (m³)"]) for row in h1] == [
        ("J2", 1.918316208363585), ("J2, J3", 39.34922632717077)]
    assert audit_location_rows(uncertain, "S_STAGE") == []  # no invented harm row for a numerical failure


def test_retained_full_audits_work_with_explicit_validator_response_fixtures():
    planning = json.loads((ROOT / "evidence/planning.json").read_bytes())
    for filename, expected in (("assurance-reference.json", "blocked"), ("assurance-no-work.json", "passed_empty")):
        audit = json.loads((ROOT / "evidence" / filename).read_bytes())
        plan = next(row for row in planning["plans"] if row["queue"] == audit["subject"]["queue"])
        gate = {"valid": True, "status": audit["status"], "approval_allowed": audit["approval_allowed"],
                "audit_sha256": audit["audit_sha256"], "subject_sha256": audit["subject_sha256"]}
        assert decision_verdict(plan, audit, gate)["status"] == expected
        assert decision_verdict(plan, audit)["level"] != "success"
        altered = deepcopy(plan)
        altered["mean_spill_m3"] += 1
        assert decision_verdict(altered, audit, gate)["status"] == "invalid_evidence"
        assert decision_verdict({"queue": plan["queue"]}, audit, gate)["status"] == "invalid_evidence"


def test_changed_snapshot_context_is_not_covered_by_a_queue_match():
    plan, audit, gate = sealed_fixture()
    plan["state_version"] = 2
    assert decision_verdict(plan, audit, gate)["status"] == "invalid_evidence"


def test_missing_or_malformed_row_containers_do_not_create_spill_values():
    audit = {"cases": [{"scenario_id": "X", "states": None, "violations": None}]}
    assert audit_location_rows(audit, "X") == []
    assert audit_location_rows({"violations": None}, "X") == []


def test_fresh_helpers_need_no_engine_application_or_workflow_imports(monkeypatch):
    original_import = builtins.__import__

    def standard_only(name, *args, **kwargs):
        if name.split(".")[0] in {"monsoon", "swmm", "streamlit"}:
            raise AssertionError(f"Unexpected application or engine import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", standard_only)
    spec = importlib.util.spec_from_file_location("standalone_presentation", ROOT / "monsoon/presentation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.decision_verdict(None)["status"] == "not_rehearsed"
    assert module.audit_case_options(None) == []
    assert module.audit_location_rows(None, "H2") == []
