"""Adversarial assurance contracts. Arithmetic runs here are test doubles only.

The tiny files explicitly identify their test-only origin. They exercise the
same result/manifest integrity contract without pretending to validate SWMM.
The delivered development evidence is generated separately by checked_state.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from monsoon import assurance, planning
from monsoon.case import load_case
from monsoon.hydraulics import engine_info


def _monotone_nodes(case, state):
    nodes = {node["id"]: {"spill_m3": 0.0} for node in case["nodes"]}
    nodes["A1"]["spill_m3"] = 100.0 - 10.0 * len(state)
    nodes["B2"]["spill_m3"] = 1.0
    return nodes


def _plain(case, state, scenario):
    nodes = _monotone_nodes(case, state)
    return {"valid": True, "status": "succeeded", "run_id": scenario["id"] + ":" + "+".join(state),
            "nodes": nodes, "total_spill_m3": sum(n["spill_m3"] for n in nodes.values()), "errors": []}


def arithmetic_checked_callback(tmp_path, case, transform=None):
    """Fixture only: emit three explicitly artificial but internally sealed runs."""
    engine = engine_info()

    def run(state, scenario, label, step, horizon):
        nodes = _monotone_nodes(case, state)
        if transform:
            replacement = transform(state, scenario, label, nodes)
            nodes = nodes if replacement is None else replacement
        inp = json.dumps({"origin": "ARITHMETIC UNIT TEST DOUBLE; NOT SWMM EVIDENCE",
                          "state": sorted(state), "hydraulic": scenario["hydraulic"],
                          "step": step, "horizon": horizon, "nodes": nodes}, sort_keys=True).encode()
        request = {"input_sha256": sha256(inp).hexdigest(), "engine": engine,
                   "case_snapshot_sha256": assurance._hash(case), "adapter_sha256": engine["adapter_sha256"]}
        run_id = assurance._hash(request)
        folder = tmp_path / run_id
        folder.mkdir(parents=True, exist_ok=True)
        files = {"input": str(folder / "model.inp"), "report": str(folder / "model.rpt"),
                 "output": str(folder / "model.out"), "manifest": str(folder / "manifest.json"),
                 "result": str(folder / "result.json"), "log": str(folder / "worker.log")}
        result = {"valid": True, "status": "succeeded", "run_id": run_id,
                  "engine_version": engine["engine_version"], "nodes": nodes,
                  "total_spill_m3": sum(n["spill_m3"] for n in nodes.values()), "errors": [],
                  "diagnostics": {"origin": "unit-test arithmetic", "routing_step_s": step, "horizon_minutes": horizon},
                  "files": files}
        (folder / "model.inp").write_bytes(inp)
        for name in ("model.rpt", "model.out", "worker.log"):
            (folder / name).write_text("ARITHMETIC UNIT TEST DOUBLE; NOT SWMM EVIDENCE", encoding="utf-8")
        (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
        manifest = {"run_id": run_id, "completed_jobs": sorted(state), "hydraulic": scenario["hydraulic"],
                    "engine": engine, "case": case, "routing_step": step, "horizon_minutes": horizon,
                    "request_fingerprint": request, "result_sha256": assurance._hash(result),
                    "file_sha256": {name: sha256((folder / name).read_bytes()).hexdigest()
                                    for name in ("model.inp", "model.rpt", "model.out", "request.json", "worker.log")}}
        (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return result

    def callback(state, scenario):
        runs = [run(state, scenario, label, step, horizon) for label, step, horizon in assurance._NUMERIC_CONFIGS]
        base = deepcopy(runs[0])
        base["assurance_numerics"] = {
            "valid": True, "status": "passed", "errors": [], "all_engine_runs_valid": True,
            "routing_step_s": .5, "half_step_s": .25, "horizon_minutes": 180, "extended_horizon_minutes": 360,
            "default_run_id": runs[0]["run_id"], "half_step_run_id": runs[1]["run_id"], "extended_run_id": runs[2]["run_id"],
            "half_step_nodes": deepcopy(runs[1]["nodes"]), "half_step_total_spill_m3": runs[1]["total_spill_m3"],
            "runs": [{"configuration": config[0], **result} for config, result in zip(assurance._NUMERIC_CONFIGS, runs)]}
        return base
    return callback


def make_assurance_fixture(tmp_path, queue=("J2", "J3"), transform=None):
    """Shared positive workflow fixture using real identity contracts, fake water."""
    case = load_case()
    selected_scenarios = [deepcopy(next(s for s in case["scenarios"] if s["id"] == "P1"))]
    episode = planning.evaluate_episode(case, selected_scenarios, lambda state, scenario: _plain(case, state, scenario))
    plan = next(plan for plan in episode["plans"] if plan["queue"] == list(queue))
    protocol = assurance.load_protocol(case)
    snapshot = assurance._snapshot_for_audit(case, episode, plan, protocol, None)
    snapshot.update(supported=True, admissible=True)
    episode.update(inputs=deepcopy(snapshot["provenance"]), context_fingerprint=snapshot["context_fingerprint"], state_version=0)
    callback = arithmetic_checked_callback(tmp_path, case, transform)
    audit = assurance.audit_plan(case, episode, plan, callback)
    snapshot["assurance"] = audit
    return case, episode, plan, snapshot, callback


@pytest.fixture(scope="module")
def passing(tmp_path_factory):
    return make_assurance_fixture(tmp_path_factory.mktemp("assurance-arithmetic"))


def test_protocol_freeze_original_case_and_revealed_labels():
    case = load_case()
    protocol = assurance.load_protocol(case)
    assert protocol["source_case_sha256"] == "45eddc5d248a23b1954f4bd0e27b645acd21a53c5518005388d7e0b07cb36436"
    assert protocol["evidence_class"] == "development_only_not_independent_validation"
    assert len(protocol["scenarios"]) == 11
    for identifier in ("H1", "H2"):
        original = next(s for s in case["scenarios"] if s["id"] == identifier)
        stress = next(s["scenario"] for s in protocol["scenarios"] if s["scenario"]["id"] == identifier)
        assert stress["hydraulic"] == original["hydraulic"]
        assert stress["durations"] == original["durations"]
        assert stress["phase"] == "development_stress"
    bad = deepcopy(protocol)
    bad["scenarios"][0]["scenario"]["durations"]["J1"] = 1
    with pytest.raises(ValueError, match="seal"):
        assurance.assurance_requirement(bad)


def test_complete_intact_evidence_can_pass_only_declared_envelope(passing):
    _, _, _, snapshot, _ = passing
    audit = snapshot["assurance"]
    assert audit["status"] == "passed"
    assert audit["counts"] == {"passed": 12, "failed": 0, "unresolved": 0}
    gate = assurance.validate_audit(snapshot)
    assert gate["valid"] and gate["approval_allowed"] and gate["reasons"] == []
    assert gate["status"] == "passed"
    assert len(audit["hydraulic_evidence"]) == 36
    assert all(len(entry["raw_provenance"]) == 3 for entry in audit["hydraulic_evidence"].values())
    assert {state["stage"] for case in audit["cases"] for state in case["states"]} == {"prefix", "final"}


def test_ticket_stamping_preserves_same_subject_and_rejects_changed_observation(passing):
    snapshot = deepcopy(passing[3])
    before = assurance.subject_hash(snapshot)
    snapshot["observed_state"] = deepcopy(snapshot["assurance"]["subject"]["observed_state"])
    snapshot["context_inputs"] = deepcopy(snapshot["provenance"])
    assert assurance.subject_hash(snapshot) == before
    snapshot["observed_state"]["elapsed_minutes"] += 1
    gate = assurance.validate_audit(snapshot)
    assert not gate["approval_allowed"] and not gate["valid"]
    assert "Observed work state" in gate["reasons"][0]


@pytest.mark.parametrize("field,value", [
    ("queue", ["J3", "J2"]), ("deadline_minutes", 179), ("travel_minutes", 9),
    ("state_version", 1), ("context_fingerprint", "0" * 64), ("frozen_fingerprint", "1" * 64),
])
def test_queue_deadline_observed_version_and_input_identity_are_bound(passing, field, value):
    snapshot = deepcopy(passing[3])
    snapshot[field] = value
    gate = assurance.validate_audit(snapshot)
    assert gate["valid"] is False and gate["approval_allowed"] is False


@pytest.mark.parametrize("field,value", [("id", "P-fabricated"), ("worst_spill_m3", 0),
                                        ("mean_spill_m3", 0), ("worst_crew_minutes", 0),
                                        ("worst_cost_rm", 0), ("reasons", ["invented assurance"]),
                                        ("scenario_results", [])])
def test_all_displayed_planning_evidence_is_bound_not_only_execution_queue(passing, field, value):
    snapshot = deepcopy(passing[3])
    snapshot[field] = value
    gate = assurance.validate_audit(snapshot)
    assert not gate["valid"] and not gate["approval_allowed"]
    assert "different queue, model, protocol, input or observed state" in gate["reasons"][0]


def test_selected_plan_score_drift_rejected_before_stress_callback(passing):
    case, episode, plan, _, _ = passing
    altered = deepcopy(plan)
    altered["scenario_results"][0]["nodes"]["A1"]["spill_m3"] = 0
    def forbidden(*args):
        raise AssertionError("Invalid selection must be rejected before stress evidence is revealed")
    with pytest.raises(ValueError, match="scores or scenario results"):
        assurance.audit_plan(case, episode, altered, forbidden)


def test_stale_engine_source_and_planner_identity_block(passing, monkeypatch):
    snapshot = deepcopy(passing[3])
    changed_engine = engine_info()
    changed_engine["adapter_sha256"] = "0" * 64
    gate = assurance.validate_audit(snapshot, hydraulic_identity=changed_engine)
    assert not gate["valid"] and "engine or adapter changed" in gate["reasons"][0]
    monkeypatch.setattr(planning, "_LOADED_SOURCE_SHA256", "0" * 64)
    gate = assurance.validate_audit(snapshot)
    assert not gate["valid"]


def test_simple_and_resealed_result_tampering_fail_closed(passing):
    for reseal in (False, True):
        snapshot = deepcopy(passing[3])
        snapshot["assurance"]["cases"][0]["states"] = []
        if reseal:
            audit = snapshot["assurance"]
            audit["audit_sha256"] = assurance._hash({k: v for k, v in audit.items() if k != "audit_sha256"})
        gate = assurance.validate_audit(snapshot)
        assert not gate["valid"] and not gate["approval_allowed"]


def test_missing_case_and_missing_raw_result_cannot_be_resealed_to_pass(passing):
    for deletion in ("case", "run"):
        snapshot = deepcopy(passing[3])
        audit = snapshot["assurance"]
        if deletion == "case":
            audit["cases"].pop()
        else:
            audit["hydraulic_evidence"].pop(next(iter(audit["hydraulic_evidence"])))
        audit["audit_sha256"] = assurance._hash({k: v for k, v in audit.items() if k != "audit_sha256"})
        assert assurance.validate_audit(snapshot)["approval_allowed"] is False


def test_prefix_harm_blocks_even_when_final_and_total_improve(tmp_path):
    def harm(state, scenario, label, nodes):
        if scenario["id"] == "H1" and set(state) == {"J2"}:
            nodes["B2"]["spill_m3"] += .2
    _, _, _, snapshot, _ = make_assurance_fixture(tmp_path, transform=harm)
    audit = snapshot["assurance"]
    h1 = next(case for case in audit["cases"] if case["scenario_id"] == "H1")
    assert h1["status"] == "failed" and audit["status"] == "failed"
    assert h1["total_spill_m3"] < h1["baseline"]["total_spill_m3"]
    assert h1["states"][-1]["status"] == "passed"
    violation = h1["violations"][0]
    assert violation["node_id"] == "B2" and violation["stage"] == "prefix" and violation["prefix_index"] == 1
    assert violation["increase_m3"] == pytest.approx(.2)
    assert violation["tolerance_m3"] == .05
    assert violation["excess_over_tolerance_m3"] == pytest.approx(.15)
    gate = assurance.validate_audit(snapshot)
    assert gate["valid"] and gate["status"] == "failed" and not gate["approval_allowed"]


def test_a_half_step_classification_flip_is_unresolved_not_a_pass(tmp_path):
    def flip(state, scenario, label, nodes):
        if scenario["id"] == "H1" and set(state) == {"J2"}:
            nodes["B2"]["spill_m3"] += .04 if label != "half step" else .06
    snapshot = make_assurance_fixture(tmp_path, transform=flip)[3]
    audit = snapshot["assurance"]
    h1 = next(case for case in audit["cases"] if case["scenario_id"] == "H1")
    assert h1["status"] == "unresolved" and audit["status"] == "unresolved"
    assert any("pass/fail changes" in reason for reason in h1["reasons"])
    assert assurance.validate_audit(snapshot)["approval_allowed"] is False


def test_missing_numerics_and_callback_failures_stay_unresolved(passing):
    case, episode, plan, _, _ = passing
    audit = assurance.audit_plan(case, episode, plan, lambda state, scenario: _plain(case, state, scenario))
    assert audit["status"] == "unresolved" and not audit["approval_allowed"]
    assert audit["counts"]["unresolved"] == 12
    assert all(case["total_spill_m3"] is None for case in audit["cases"])


@pytest.mark.parametrize("bad_result", [None, [], {"valid": True, "status": "succeeded", "errors": 42},
                                      {"valid": True, "status": "succeeded", "total_spill_m3": float("nan")},
                                      {"valid": True, "status": "succeeded", "nodes": {"A1": {"spill_m3": float("inf")}}}])
def test_malformed_numeric_callbacks_export_unresolved_in_strict_json(passing, bad_result):
    case, episode, plan, _, _ = passing
    audit = assurance.audit_plan(case, episode, plan, lambda state, scenario: deepcopy(bad_result))
    assert audit["status"] == "unresolved" and not audit["approval_allowed"]
    assert audit["counts"]["unresolved"] == 12
    json.dumps(audit, allow_nan=False)


def test_uncertified_horizon_and_step_values_are_recomputed_from_raw_runs(tmp_path):
    def horizon_change(state, scenario, label, nodes):
        if scenario["id"] == "S_STAGE" and label == "extended horizon":
            nodes["A1"]["spill_m3"] += 1
    snapshot = make_assurance_fixture(tmp_path, transform=horizon_change)[3]
    audit = snapshot["assurance"]
    stage = next(case for case in audit["cases"] if case["scenario_id"] == "S_STAGE")
    assert stage["status"] == "unresolved"
    assert any("extended horizon" in reason for reason in stage["reasons"])
    assert len(next(entry for entry in audit["hydraulic_evidence"].values() if entry["scenario_id"] == "S_STAGE")["raw_provenance"]) == 3
    assert not assurance.validate_audit(snapshot)["approval_allowed"]


def test_no_work_compares_against_current_verified_start_not_empty(tmp_path):
    case = load_case()
    scenarios = [next(s for s in case["scenarios"] if s["id"] == "P1")]
    episode = planning.evaluate_episode(case, scenarios, lambda state, scenario: _plain(case, state, scenario),
                                        already_completed=["J4"], start_minute=85, start_location="J4")
    plan = next(plan for plan in episode["plans"] if plan["queue"] == [])
    seen = []
    callback = arithmetic_checked_callback(tmp_path, case)

    def traced(state, scenario):
        seen.append(tuple(state))
        return callback(state, scenario)
    audit = assurance.audit_plan(case, episode, plan, traced)
    assert audit["status"] == "passed"
    assert set(seen) == {("J4",)}
    assert all(case["replay"]["crew_minutes"] == 10 for case in audit["cases"])
    assert all(case["states"][0]["node_comparisons"][0]["increase_m3"] == 0 for case in audit["cases"])


def test_raw_artefact_tamper_blocks_even_when_top_audit_unchanged(tmp_path):
    snapshot = make_assurance_fixture(tmp_path)[3]
    first = next(iter(snapshot["assurance"]["hydraulic_evidence"].values()))
    report = Path(first["raw"]["files"]["report"])
    report.write_text("CORRUPTED TEST REPORT", encoding="utf-8")
    gate = assurance.validate_audit(snapshot)
    assert not gate["valid"] and not gate["approval_allowed"]


def test_no_stress_selection_or_oracle_and_bad_freeze_rejected_before_callback(passing, monkeypatch):
    case, episode, plan, _, callback = passing
    def forbidden(*args, **kwargs):
        raise AssertionError("Audit must never reselect or calculate an oracle")
    monkeypatch.setattr(planning, "evaluate_episode", forbidden)
    monkeypatch.setattr(planning, "evaluate_holdouts", forbidden)
    monkeypatch.setattr(planning, "_rank", forbidden)
    audit = assurance.audit_plan(case, episode, plan, callback)
    assert audit["subject"]["queue"] == plan["queue"]
    bad = deepcopy(episode)
    bad["policies"]["robust"]["queue"] = []
    with pytest.raises(ValueError, match="modified"):
        assurance.audit_plan(case, bad, plan, forbidden)


@pytest.mark.parametrize("snapshot", [None, {}, {"assurance_requirement": None}, {"assurance": {"status": "passed"}}])
def test_malformed_or_absent_evidence_never_approves(snapshot):
    gate = assurance.validate_audit(snapshot)
    assert gate["approval_allowed"] is False


def test_offline_inspection_cannot_approve(passing):
    gate = assurance.validate_audit(passing[3], verify_files=False)
    assert gate["valid"] and not gate["approval_allowed"]
    assert "Offline" in gate["reasons"][0]
