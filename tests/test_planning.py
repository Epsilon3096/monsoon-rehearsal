"""Hand-checkable scheduling and decision-contract tests.

The tiny arithmetic hydraulic oracle in this file is strictly a unit-test double.
The application and integration tests use the actual EPA SWMM adapter.
"""
from copy import deepcopy
import json
import math

import pytest

from monsoon.planning import enumerate_queues, evaluate_episode, evaluate_holdouts, replay, _rank


def jobs4():
    return [{"id": f"J{i + 1}", "asset_id": f"A{i + 1}", "nominal_minutes": nominal,
             "max_minutes": bound, "downstream_rank": i, "cost_rm": 10 * (i + 1),
             "prerequisites": []}
            for i, (nominal, bound) in enumerate(zip([90, 45, 60, 75], [100, 55, 70, 85]))]


def case4():
    return {"id": "unit-test-case", "model_version": "test-only", "jobs": jobs4(),
            "travel_minutes": 10, "protected_nodes": ["A", "B"], "epsilon_m3": 0.05,
            "tie_m3": 0.05, "evidence_status": "synthetic"}


def scenario(identifier="P1", phase="planning", durations=None):
    return {"id": identifier, "phase": phase, "hydraulic": {"factor": 1.0},
            "durations": durations or {"J1": 90, "J2": 45, "J3": 60, "J4": 75}}


def fake_hydraulics(state, event):
    benefit = sum({"J1": 30, "J2": 25, "J3": 15, "J4": 10}[identifier] for identifier in state)
    a = (100 - benefit) * event["hydraulic"].get("factor", 1)
    b = 50.0
    return {"status": "succeeded", "valid": True, "run_id": event["id"] + ":" + "+".join(state),
            "total_spill_m3": a + b, "nodes": {"A": {"spill_m3": a}, "B": {"spill_m3": b}},
            "errors": [], "timeseries": [{"very_large": "must_not_be_copied"}], "files": {"input": "test-only"}}


def test_all_ordered_subsets_and_stable_order():
    four = enumerate_queues(["J4", "J1", "J3", "J2"])
    assert len(four) == 65
    assert len(set(four)) == 65
    assert four[0] == ()
    assert four[1] == ("J1",)
    assert len(enumerate_queues([f"J{i}" for i in range(6)])) == 1957
    assert enumerate_queues([]) == [()]
    with pytest.raises(ValueError, match="Duplicate"):
        enumerate_queues(["J1", "J1"])


def test_hand_checked_travel_bound_gate_and_return():
    result = replay(["J1", "J2", "J3", "J4"], jobs4(), 180)
    assert result["status"] == "supported"
    assert result["completed_jobs"] == ["J1", "J2"]
    assert [(event["depart_minute"], event["start_minute"], event["finish_minute"])
            for event in result["events"]] == [(0, 10, 100), (100, 110, 155)]
    assert result["finish_minute"] == 165
    assert result["crew_minutes"] == 165
    assert result["return_minutes"] == 10
    assert {skip["reason"] for skip in result["skipped"]} == {"insufficient_bound_window"}


def test_upper_bound_not_realised_or_nominal_duration_gates_start():
    # J1 would actually fit, but its unobserved 1-minute outcome cannot be used.
    result = replay(["J1", "J2"], jobs4(), 80,
                    actual_durations={"J1": 1, "J2": 45, "J3": 60, "J4": 75})
    assert result["completed_jobs"] == ["J2"]
    assert result["finish_minute"] == 65
    assert result["events"][0]["job_id"] == "J2"


def test_nonanticipation_and_adaptation_to_observed_elapsed_time():
    slow = replay(["J1", "J2", "J3"], jobs4(), 170,
                  actual_durations={"J1": 100, "J2": 45, "J3": 60, "J4": 75})
    fast = replay(["J1", "J2", "J3"], jobs4(), 170,
                  actual_durations={"J1": 50, "J2": 45, "J3": 1, "J4": 75})
    assert slow["events"][0]["job_id"] == fast["events"][0]["job_id"] == "J1"
    assert slow["events"][0]["start_minute"] == fast["events"][0]["start_minute"] == 10
    assert slow["completed_jobs"] == ["J1"]
    assert fast["completed_jobs"] == ["J1", "J2"]


def test_reconsider_deferred_prerequisite_after_completion():
    jobs = jobs4()
    jobs[0]["prerequisites"] = ["J2"]
    result = replay(["J1", "J2"], jobs, 200)
    assert result["completed_jobs"] == ["J2", "J1"]
    assert result["finish_minute"] == 165


def test_verified_start_state_time_and_actual_location():
    jobs = jobs4()
    jobs[1]["prerequisites"] = ["J1"]
    result = replay(["J1", "J2"], jobs, 180, already_completed=["J1"],
                    start_minute=100, start_location="A1")
    assert result["completed_jobs"] == ["J2"]
    assert result["events"][0]["depart_minute"] == 100
    assert result["events"][0]["start_minute"] == 110
    assert result["finish_minute"] == 165
    assert result["crew_minutes"] == 65
    assert result["skipped"] == [{"job_id": "J1", "reason": "already_completed"}]


def test_no_work_still_accounts_for_return_from_site():
    result = replay([], jobs4(), 180, start_minute=150, start_location="J1")
    assert result["crew_minutes"] == 10
    assert result["finish_minute"] == 160
    result = replay([], jobs4(), 180, start_minute=175, start_location="J1")
    assert result["status"] == "unsupported"
    assert result["finish_minute"] == 185


def test_job_bound_violation_never_receives_restoration_credit():
    result = replay(["J1", "J2"], jobs4(), 500,
                    actual_durations={"J1": 101, "J2": 45, "J3": 60, "J4": 75})
    assert result["status"] == "unsupported"
    assert result["completed_jobs"] == []
    assert result["events"][0]["supported"] is False
    assert "exceeded" in result["reasons"][0]
    assert result["finish_minute"] == 121


@pytest.mark.parametrize("value", [None, -1, math.inf, math.nan, True, "bad"])
def test_invalid_observed_duration_fails_closed(value):
    result = replay(["J1"], jobs4(), 180, actual_durations={"J1": value})
    assert result["status"] == "unsupported"
    assert not result["completed_jobs"]


def test_unused_future_duration_is_not_consulted():
    result = replay(["J1", "J2"], jobs4(), 120, actual_durations={"J1": 90, "J2": -999})
    assert result["status"] == "supported"
    assert result["completed_jobs"] == ["J1"]


def test_bad_queue_dependencies_and_unknown_state_rejected():
    with pytest.raises(ValueError):
        replay(["J1", "J1"], jobs4(), 180)
    with pytest.raises(ValueError):
        replay(["missing"], jobs4(), 180)
    with pytest.raises(ValueError):
        replay([], jobs4(), 180, already_completed=["missing"])
    with pytest.raises(ValueError):
        replay([], jobs4(), 180, start_location="unknown")
    jobs = jobs4()
    jobs[0]["prerequisites"] = ["J2"]
    jobs[1]["prerequisites"] = ["J1"]
    with pytest.raises(ValueError, match="cycle"):
        replay(["J1"], jobs, 180)


def test_empty_plan_is_valid_when_no_job_fits():
    result = evaluate_episode(case4(), [scenario()], fake_hydraulics, deadline_minutes=0)
    assert result["recommended"] is not None
    assert result["recommended"]["queue"] == []
    assert result["recommended"]["worst_crew_minutes"] == 0
    assert result["counts"]["enumerated_queues"] == 65


def test_exact_plan_scores_and_all_comparators_share_dispatch():
    result = evaluate_episode(case4(), [scenario()], fake_hydraulics,
                              deadline_minutes=180, operator_queue=["J1", "J2", "J3", "J4"])
    assert result["counts"]["enumerated_queues"] == 65
    assert result["recommended"]["worst_spill_m3"] == 95
    assert result["counts"]["hydraulic_callback_calls"] <= 16
    by_method = {row["method"]: row for row in result["comparisons"]}
    assert set(by_method) == {"robust", "downstream_first", "marginal_benefit", "deterministic_nominal", "no_work", "user_entered"}
    for method in ["downstream_first", "user_entered"]:
        assert by_method[method]["completed_jobs"] == ["J1", "J2"]
        assert by_method[method]["crew_minutes"] == 165
    assert by_method["no_work"]["completed_jobs"] == []
    assert by_method["user_entered"]["method_label"] == "User-entered comparison"
    assert "expert" in result["baseline_definitions"]["downstream_first"]["definition"]
    serialised = json.dumps(result, allow_nan=False)
    assert "very_large" not in serialised
    assert "test-only\"}" not in serialised


def test_same_completed_state_has_same_hydraulic_score_regardless_order():
    result = evaluate_episode(case4(), [scenario()], fake_hydraulics, deadline_minutes=500)
    by_id = {plan["id"]: plan for plan in result["plans"]}
    a, b = by_id["P-J1-J2-J3-J4"], by_id["P-J4-J3-J2-J1"]
    assert a["worst_spill_m3"] == b["worst_spill_m3"] == 70
    assert a["scenario_results"][0]["run_id"] == b["scenario_results"][0]["run_id"]
    assert result["counts"]["hydraulic_callback_calls"] <= 16


def test_no_worsening_is_per_location_and_screens_reachable_prefixes():
    def redistributing(state, event):
        # The final J1+J2 state improves both nodes, but stopping after J1 harms B.
        if "J1" in state and "J2" not in state:
            a, b = 1, 60
        elif "J1" in state:
            a, b = 1, 40
        else:
            a, b = 100, 50
        return {"status": "succeeded", "valid": True, "run_id": "+".join(state) or "EMPTY",
                "total_spill_m3": a + b, "nodes": {"A": {"spill_m3": a}, "B": {"spill_m3": b}}}
    result = evaluate_episode(case4(), [scenario()], redistributing, deadline_minutes=500)
    plans = {plan["id"]: plan for plan in result["plans"]}
    assert plans["P-J1"]["status"] == "inadmissible"
    assert plans["P-J1-J2"]["status"] == "inadmissible"
    assert plans["P-J2-J1"]["status"] == "supported"
    assert plans["P-J1-J2"]["worst_spill_m3"] == 41
    violation = plans["P-J1-J2"]["scenario_results"][0]["protected_violations"][0]
    assert violation["node_id"] == "B"
    assert violation["increase_m3"] == 10


def test_required_failed_scenario_is_not_dropped_from_aggregation():
    def failure(state, event):
        if event["id"] == "P2" and "J1" in state:
            return {"valid": False, "status": "failed", "run_id": "failed-1", "errors": ["simulation failed"]}
        return fake_hydraulics(state, event)
    result = evaluate_episode(case4(), [scenario(), scenario("P2")], failure)
    plan = next(plan for plan in result["plans"] if plan["id"] == "P-J1")
    assert plan["status"] == "unresolved"
    assert not plan["admissible"]
    assert plan["worst_spill_m3"] is None
    assert plan["mean_spill_m3"] is None
    assert len(plan["scenario_results"]) == 2
    assert "J1" not in result["recommended"]["scenario_results"][0]["completed_jobs"]


def test_failed_reference_abstains_and_does_not_make_zero_score():
    def failure(state, event):
        raise RuntimeError("unit-test outage")
    result = evaluate_episode(case4(), [scenario()], failure)
    assert result["recommended"] is None
    assert result["counts"]["unresolved_plans"] == 65
    assert all(plan["worst_spill_m3"] is None for plan in result["plans"])
    assert any(row["method"] == "robust" and row["status"] == "unresolved" for row in result["comparisons"])


def test_missing_protected_metric_and_inconsistent_total_fail_closed():
    def missing(state, event):
        result = fake_hydraulics(state, event)
        del result["nodes"]["B"]
        return result
    assert evaluate_episode(case4(), [scenario()], missing)["recommended"] is None
    def inconsistent(state, event):
        result = fake_hydraulics(state, event)
        result["total_spill_m3"] = 0
        return result
    assert evaluate_episode(case4(), [scenario()], inconsistent)["recommended"] is None


def test_tie_bands_are_relative_to_attained_minimum_not_pairwise_chain():
    def plan(identifier, worst, mean, minutes):
        return {"id": identifier, "admissible": True, "worst_spill_m3": worst,
                "mean_spill_m3": mean, "worst_crew_minutes": minutes, "worst_cost_rm": 0}
    plans = [plan("A", 10.00, 10.00, 100), plan("B", 10.04, 10.04, 90), plan("C", 10.08, 9.0, 1)]
    selected, alternatives, audit = _rank(plans, 0.05)
    assert selected["id"] == "B"
    assert audit[0]["remaining_plan_ids"] == ["A", "B"]
    assert {item["id"] for item in alternatives} == {"A"}


def test_replan_enumerates_only_remaining_jobs_and_preserves_initial_state():
    result = evaluate_episode(case4(), [scenario()], fake_hydraulics, deadline_minutes=180,
                              already_completed=["J1"], start_minute=100, start_location="J1")
    assert result["counts"]["enumerated_queues"] == 16
    assert result["counts"]["remaining_jobs"] == 3
    assert all("J1" not in plan["queue"] for plan in result["plans"])
    assert all("J1" in row["completed_jobs"] for row in result["comparisons"])
    no_work = next(row for row in result["comparisons"] if row["method"] == "no_work")
    assert no_work["total_spill_m3"] == 120
    assert no_work["crew_minutes"] == 10


def test_marginal_policy_recomputes_interacting_benefits():
    case = case4()
    for job in case["jobs"]:
        job["nominal_minutes"] = job["max_minutes"] = 20
    def interaction(state, event):
        # J1 initially best. After J1, J2 is redundant and J3 has the next gain.
        gain = (50 if "J1" in state else 40 if "J2" in state else 0) + (30 if "J3" in state else 0)
        a = 100 - gain
        return {"status": "succeeded", "valid": True, "run_id": "+".join(state) or "EMPTY",
                "total_spill_m3": a + 50, "nodes": {"A": {"spill_m3": a}, "B": {"spill_m3": 50}}}
    event = scenario(durations={"J1": 20, "J2": 20, "J3": 20, "J4": 20})
    result = evaluate_episode(case, [event], interaction, deadline_minutes=70)
    marginal = next(row for row in result["comparisons"] if row["method"] == "marginal_benefit")
    assert marginal["newly_completed_jobs"] == ["J1", "J3"]
    assert marginal["crew_minutes"] == 70


def test_holdout_inputs_cannot_enter_selection():
    calls = []
    def callback(state, event):
        calls.append(event["id"])
        return fake_hydraulics(state, event)
    with pytest.raises(ValueError, match="planning-only"):
        evaluate_episode(case4(), [scenario("H1", "holdout")], callback)
    assert calls == []


def test_frozen_holdout_replay_and_oracle_separation():
    case = case4()
    episode = evaluate_episode(case, [scenario()], fake_hydraulics)
    locked = deepcopy(episode["policies"])
    holdout = scenario("H1", "holdout", {"J1": 50, "J2": 20, "J3": 30, "J4": 30})
    result = evaluate_holdouts(episode, case, [holdout], fake_hydraulics)
    assert episode["policies"] == locked
    assert result["frozen_fingerprint"] == episode["frozen_fingerprint"]
    assert all(row["scenario_id"] == "H1" for row in result["comparisons"])
    robust = next(row for row in result["comparisons"] if row["method"] == "robust")
    assert robust["queue"] == locked["robust"]["queue"]
    oracle = result["diagnostic_oracles"][0]
    assert "diagnostic only" in oracle["label"]
    assert oracle["plan"]["worst_spill_m3"] <= robust["total_spill_m3"]
    assert "Perfect" in oracle["information_advantage"]
    json.dumps(result, allow_nan=False)


def test_changed_case_modified_lock_or_reused_ids_rejected():
    case = case4()
    episode = evaluate_episode(case, [scenario()], fake_hydraulics)
    holdout = scenario("H1", "holdout")
    changed = deepcopy(case)
    changed["jobs"][0]["max_minutes"] += 1
    with pytest.raises(ValueError, match="changed"):
        evaluate_holdouts(episode, changed, [holdout], fake_hydraulics)
    tampered = deepcopy(episode)
    tampered["policies"]["robust"]["queue"] = []
    with pytest.raises(ValueError, match="modified"):
        evaluate_holdouts(tampered, case, [holdout], fake_hydraulics)
    with pytest.raises(ValueError, match="reused"):
        evaluate_holdouts(episode, case, [scenario("P1", "holdout")], fake_hydraulics)


def test_full_restoration_convergence_and_downstream_friendly_case():
    result = evaluate_episode(case4(), [scenario()], fake_hydraulics, deadline_minutes=500)
    operational = {row["method"]: row for row in result["comparisons"]}
    for method in ["robust", "downstream_first", "marginal_benefit", "deterministic_nominal"]:
        assert operational[method]["completed_jobs"] == ["J1", "J2", "J3", "J4"]
        assert operational[method]["total_spill_m3"] == 70
    def downstream_only(state, event):
        a = 1 if "J1" in state else 100
        return {"status": "succeeded", "valid": True, "run_id": "+".join(state) or "EMPTY",
                "total_spill_m3": a + 50, "nodes": {"A": {"spill_m3": a}, "B": {"spill_m3": 50}}}
    result = evaluate_episode(case4(), [scenario()], downstream_only, deadline_minutes=120)
    operational = {row["method"]: row for row in result["comparisons"]}
    assert operational["robust"]["total_spill_m3"] == operational["downstream_first"]["total_spill_m3"] == 51


def test_nominal_planner_uses_declared_nominal_durations():
    # A slower planning realisation does not redefine the deterministic nominal forecast.
    event = scenario(durations={"J1": 100, "J2": 55, "J3": 70, "J4": 85})
    result = evaluate_episode(case4(), [event], fake_hydraulics, deadline_minutes=180)
    nominal = result["policies"]["deterministic_nominal"]
    nominal_replay = replay(nominal["queue"], jobs4(), 180)
    assert set(nominal_replay["completed_jobs"]) == {"J1", "J2"}
    actual = next(row for row in result["comparisons"] if row["method"] == "deterministic_nominal")
    assert len(actual["newly_completed_jobs"]) == 1


def test_bounds_exception_survives_evaluation_without_hydraulic_credit():
    event = scenario(durations={"J1": 101, "J2": 45, "J3": 60, "J4": 75})
    result = evaluate_episode(case4(), [event], fake_hydraulics, deadline_minutes=180)
    plan = next(plan for plan in result["plans"] if plan["id"] == "P-J1")
    assert plan["status"] == "unresolved"
    assert plan["worst_spill_m3"] is None
    assert plan["scenario_results"][0]["completed_jobs"] == []
