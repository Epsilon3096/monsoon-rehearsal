"""Independent adversarial tests of the finite-scenario decision contract.

Hydraulics here are deliberately tiny test doubles. They establish validation
and information-flow properties, never hydraulic or field-performance evidence.
"""
from copy import deepcopy
from itertools import permutations

import pytest

import monsoon.planning as planning
from monsoon.planning import (
    _rank, evaluate_episode, evaluate_holdouts, replay,
)


def review_case():
    return {
        "id": "independent-planning-review", "model_version": "test-only",
        "jobs": [
            {"id": "A", "asset_id": "SITE_A", "nominal_minutes": 10,
             "max_minutes": 20, "cost_rm": 1, "downstream_rank": 0,
             "prerequisites": []},
            {"id": "B", "asset_id": "SITE_B", "nominal_minutes": 10,
             "max_minutes": 20, "cost_rm": 2, "downstream_rank": 1,
             "prerequisites": []},
        ],
        "nodes": [{"id": "P", "kind": "junction"},
                  {"id": "U", "kind": "junction"}],
        "travel_minutes": 5, "protected_nodes": ["P"],
        "epsilon_m3": 0.05, "tie_m3": 0.05,
        "evidence_status": "synthetic",
    }


def review_scenario(identifier="P1", phase="planning", durations=None):
    return {"id": identifier, "phase": phase, "hydraulic": {"factor": 1},
            "durations": {"A": 10, "B": 10} if durations is None else durations}


def review_hydraulics(state, scenario):
    spill = (100 - 30 * len(state)) * scenario["hydraulic"].get("factor", 1)
    return {"valid": True, "status": "succeeded",
            "run_id": scenario["id"] + ":" + ("+".join(state) or "EMPTY"),
            "completed_jobs": list(state), "scenario_id": scenario["id"],
            "total_spill_m3": spill,
            "nodes": {"P": {"spill_m3": spill}, "U": {"spill_m3": 0}},
            "errors": []}


def test_duration_mapping_is_read_only_after_the_corresponding_dispatch():
    class WatchedDurations(dict):
        def __init__(self):
            super().__init__(A=20, B=1)
            self.reads = []

        def __getitem__(self, key):
            self.reads.append(key)
            return super().__getitem__(key)

    durations = WatchedDurations()
    result = replay(["A", "B"], review_case()["jobs"], 35,
                    travel_minutes=5, actual_durations=durations)
    assert result["completed_jobs"] == ["A"]
    assert durations.reads == ["A"]
    assert result["finish_minute"] == 30


def test_identical_observed_history_forces_identical_next_dispatch():
    # All futures agree about A. B/C outcomes remain unseen until dispatched.
    jobs = review_case()["jobs"]
    jobs.append({**deepcopy(jobs[1]), "id": "C", "asset_id": "SITE_C"})
    histories = []
    for future_b, future_c in [(1, 20), (20, 1), (19, 19)]:
        result = replay(["A", "B", "C"], jobs, 75, travel_minutes=5,
                        actual_durations={"A": 10, "B": future_b, "C": future_c})
        histories.append([(row["job_id"], row["start_minute"])
                          for row in result["events"][:2]])
    assert histories == [[("A", 5), ("B", 20)]] * 3


def test_bound_boundary_includes_initial_and_final_travel():
    case = review_case()
    at_boundary = replay(["A"], case["jobs"], 40, travel_minutes=5,
                         start_minute=10, actual_durations={"A": 20})
    too_late = replay(["A"], case["jobs"], 39.99, travel_minutes=5,
                      start_minute=10, actual_durations={"A": 1})
    assert at_boundary["completed_jobs"] == ["A"]
    assert at_boundary["finish_minute"] == 40
    assert too_late["completed_jobs"] == []
    assert too_late["skipped"][0]["reason"] == "insufficient_bound_window"


def test_impossible_prerequisite_is_never_bypassed_by_a_short_future_duration():
    jobs = review_case()["jobs"]
    jobs[1]["prerequisites"] = ["A"]
    result = replay(["B"], jobs, 100, travel_minutes=5,
                    actual_durations={"B": 1})
    assert result["completed_jobs"] == []
    assert result["skipped"][0]["missing_prerequisites"] == ["A"]


def test_rank_is_order_independent_at_all_four_minimum_relative_stages():
    def candidate(identifier, worst, mean, minutes, cost):
        return {"id": identifier, "admissible": True, "worst_spill_m3": worst,
                "mean_spill_m3": mean, "worst_crew_minutes": minutes,
                "worst_cost_rm": cost}

    choices = [candidate("A", 10, 8.10, 1, 1),
               candidate("B", 10.04, 8, 20, 10),
               candidate("C", 10.08, 0, 0, 0),
               candidate("D", 10.03, 8.04, 20.04, 9)]
    for ordering in permutations(choices):
        selected, alternatives, audit = _rank(ordering, 0.05, 0.05, 0)
        assert selected["id"] == "D"
        assert {item["id"] for item in alternatives} == {"B"}
        assert [stage["attained_minimum"] for stage in audit] == [10, 8, 20, 9]


def test_invalid_intermediate_run_cannot_inherit_valid_final_score():
    def hydraulic(state, scenario):
        if set(state) == {"A"}:
            return {"valid": False, "status": "invalid", "run_id": "bad-prefix",
                    "errors": ["Prefix convergence failed"]}
        return review_hydraulics(state, scenario)

    episode = evaluate_episode(review_case(), [review_scenario()], hydraulic,
                               deadline_minutes=100)
    forward = next(p for p in episode["plans"] if p["queue"] == ["A", "B"])
    reverse = next(p for p in episode["plans"] if p["queue"] == ["B", "A"])
    assert forward["status"] == "unresolved"
    assert forward["worst_spill_m3"] is None
    assert forward["scenario_results"][0]["total_spill_m3"] is None
    assert reverse["status"] == "supported"


def test_missing_nonprotected_model_node_makes_a_run_unresolved():
    def incomplete(state, scenario):
        result = review_hydraulics(state, scenario)
        if "A" in state:
            # Internally consistent but incomplete: U's spill is unrepresented.
            result["nodes"] = {"P": {"spill_m3": 0}}
            result["total_spill_m3"] = 0
        return result

    episode = evaluate_episode(review_case(), [review_scenario()], incomplete,
                               deadline_minutes=100)
    affected = next(p for p in episode["plans"] if p["queue"] == ["A"])
    assert affected["status"] == "unresolved"
    assert affected["worst_spill_m3"] is None


@pytest.mark.parametrize("run_id", [None, "", " "])
def test_missing_hydraulic_evidence_identity_cannot_support_a_recommendation(run_id):
    def anonymous(state, scenario):
        result = review_hydraulics(state, scenario)
        result["run_id"] = run_id
        return result

    episode = evaluate_episode(review_case(), [review_scenario()], anonymous)
    assert episode["recommended"] is None
    assert all(plan["status"] == "unresolved" for plan in episode["plans"])


def test_marginal_holdout_dispatch_does_not_consult_realised_forcing():
    case = review_case()
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics,
                               deadline_minutes=60)
    positive = review_scenario("H1", "holdout", {"A": 10, "B": 10})
    different = review_scenario("H2", "holdout", {"A": 10, "B": 10})
    different["hydraulic"]["factor"] = 3
    result = evaluate_holdouts(episode, case, [positive, different], review_hydraulics)
    dispatches = [row["replay"]["events"] for row in result["comparisons"]
                  if row["method"] == "marginal_benefit"]
    assert dispatches[0] == dispatches[1]
    assert episode["policies"]["marginal_benefit"]["kind"] == "marginal"


def test_holdout_oracle_failure_does_not_discard_operational_evidence():
    case = review_case()
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics,
                               deadline_minutes=35)
    # A is observed to overrun its bound; B's recorded duration is corrupt.
    # Frozen operational rows must survive as unresolved, with no fake score.
    bad = review_scenario("H1", "holdout", {"A": 21, "B": None})
    result = evaluate_holdouts(episode, case, [bad], review_hydraulics)
    robust = next(row for row in result["comparisons"] if row["method"] == "robust")
    assert robust["status"] == "unresolved"
    assert robust["total_spill_m3"] is None
    no_work = next(row for row in result["comparisons"] if row["method"] == "no_work")
    assert no_work["status"] == "supported"
    assert no_work["total_spill_m3"] == 100
    assert result["diagnostic_oracles"][0]["plan"] is None


def test_exact_oracle_loss_is_distinct_from_tolerance_selected_oracle_plan():
    case = review_case()
    case["jobs"] = case["jobs"][:1]

    def hydraulic(state, scenario):
        gain = 10 if scenario["phase"] == "planning" else 0.04
        spill = 100 - (gain if "A" in state else 0)
        result = review_hydraulics(state, scenario)
        result.update(total_spill_m3=spill,
                      nodes={"P": {"spill_m3": spill}, "U": {"spill_m3": 0}})
        return result

    episode = evaluate_episode(case, [review_scenario()], hydraulic)
    result = evaluate_holdouts(episode, case, [review_scenario("H1", "holdout")], hydraulic)
    robust = next(row for row in result["comparisons"] if row["method"] == "robust")
    oracle = result["diagnostic_oracles"][0]
    assert robust["total_spill_m3"] == pytest.approx(99.96)
    assert oracle["plan"]["worst_spill_m3"] == 100
    assert oracle["exact_minimum_spill_m3"] == pytest.approx(99.96)


def test_all_completed_holdout_does_not_require_past_duration_observations():
    case = review_case()
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics,
                               already_completed=["A", "B"], start_minute=50,
                               start_location="B", deadline_minutes=100)
    outcome = review_scenario("H1", "holdout", {})
    result = evaluate_holdouts(episode, case, [outcome], review_hydraulics)
    assert all(row["status"] == "supported" for row in result["comparisons"])
    assert result["diagnostic_oracles"][0]["plan"]["queue"] == []
    assert result["diagnostic_oracles"][0]["exact_minimum_spill_m3"] == 40


def test_unresolved_oracle_candidate_cannot_produce_a_false_exact_lower_bound():
    case = review_case()
    case["jobs"] = case["jobs"][:1]
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics)

    def failed_work_state(state, scenario):
        if state:
            return {"valid": False, "status": "failed", "run_id": "failed-A",
                    "errors": ["Cannot determine the work-state outcome"]}
        return review_hydraulics(state, scenario)

    result = evaluate_holdouts(episode, case, [review_scenario("H1", "holdout")], failed_work_state)
    oracle = result["diagnostic_oracles"][0]
    assert oracle["status"] == "unresolved"
    assert oracle["plan"] is None
    assert oracle["exact_minimum_spill_m3"] is None
    assert oracle["best_supported_plan"]["queue"] == []
    assert "lower-bound" in " ".join(oracle["reasons"])


def test_frozen_baseline_definitions_cannot_be_silently_relabelled():
    case = review_case()
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics)
    episode["baseline_definitions"]["downstream_first"]["label"] = "Expert operator"
    with pytest.raises(ValueError, match="modified"):
        evaluate_holdouts(episode, case, [review_scenario("H1", "holdout")], review_hydraulics)


def test_holdout_replay_requires_the_same_frozen_planner_implementation(monkeypatch):
    case = review_case()
    episode = evaluate_episode(case, [review_scenario()], review_hydraulics)
    assert len(episode["decision_manifest"]["planner_source_sha256"]) == 64
    monkeypatch.setattr(planning, "_planner_source_fingerprint", lambda: "changed-implementation")
    with pytest.raises(ValueError, match="planner implementation"):
        evaluate_holdouts(episode, case, [review_scenario("H1", "holdout")], review_hydraulics)
