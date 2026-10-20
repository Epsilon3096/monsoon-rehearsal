"""Arithmetic contracts only; these doubles do not validate SWMM or a physical rig."""
from copy import deepcopy

import pytest

from monsoon import assurance
from monsoon.case import load_case
from monsoon.observed_policy import (
    _Evidence, condition_development, fingerprint, freeze_observed_policy,
    load_protocol, replay_observed_policy, validate_observation,
)
from monsoon.policy_evaluation import outcome_summary


def resign(protocol):
    protocol["protocol_sha256"] = fingerprint({k: v for k, v in protocol.items() if k != "protocol_sha256"})
    return protocol


@pytest.fixture
def research(monkeypatch):
    case, protocol = load_case(), load_protocol()
    protocol["development_profiles"] = protocol["development_profiles"][:1]
    resign(protocol)
    monkeypatch.setattr(assurance, "_runtime_identity", lambda: {"hydraulic": {"fixture": True}})
    monkeypatch.setattr(assurance, "_raw_provenance", lambda *args, **kwargs: ({"fixture": "arithmetic only"}, []))
    return case, protocol


def checked_fixture(case, state, event, *, harmful=None, invalid=None, half_change=None):
    gain = sum({"J1": 35, "J2": 20, "J3": 18, "J4": 12}[j] for j in state)
    nodes = {n["id"]: {"spill_m3": max(0, 100-gain) if n["id"] == "A1" else 0,
                       "max_depth_m": .4, "duration_above_threshold_min": 2,
                       "threshold_m": .8} for n in case["nodes"]}
    if harmful and harmful(state, event):
        nodes["B2"]["spill_m3"] = 1.0
    base = {"valid": True, "status": "succeeded", "run_id": fingerprint([sorted(state), event["hydraulic"]]),
            "nodes": nodes, "total_spill_m3": sum(x["spill_m3"] for x in nodes.values()),
            "engine_version": "arithmetic-test-only", "files": {}, "errors": []}
    if invalid and invalid(state, event):
        base.update(valid=False, status="failed", errors=["prespecified fake error"])
    runs = []
    for i, label in enumerate(("default", "half step", "extended horizon")):
        run = deepcopy(base)
        run.update(configuration=label, run_id=base["run_id"] + f":{i}")
        if i == 1 and half_change:
            half_change(run, state)
        runs.append(run)
    result = deepcopy(runs[0])
    result.pop("configuration")
    result["assurance_numerics"] = {
        "valid": True, "status": "passed", "all_engine_runs_valid": True, "errors": [],
        "routing_step_s": .5, "half_step_s": .25, "horizon_minutes": 180, "extended_horizon_minutes": 360,
        "runs": runs, "default_run_id": runs[0]["run_id"], "half_step_run_id": runs[1]["run_id"],
        "extended_run_id": runs[2]["run_id"], "half_step_nodes": deepcopy(runs[1]["nodes"]),
        "half_step_total_spill_m3": runs[1]["total_spill_m3"],
    }
    return result


def callback(case, **kwargs):
    return lambda state, event: checked_fixture(case, state, event, **kwargs)


def test_conditioning_preserves_all_unobserved_profiles_and_error_corners():
    case, protocol = load_case(), load_protocol()
    scenarios = condition_development(case, protocol["observations"]["LOW"], protocol)
    assert len(scenarios) == 11 * 4 * 2 + 1
    for profile in protocol["development_profiles"]:
        rows = [s for s in scenarios if s["profile_id"] == profile["id"]]
        assert len(rows) == 8
        assert {(s["hydraulic"]["initial_storage_depth_m"], s["hydraulic"]["tailwater_m"]) for s in rows} == {
            (.09, 99.36), (.09, 99.4), (.15, 99.36), (.15, 99.4)}
        assert all(all(s["hydraulic"][k] == v for k, v in profile["hydraulic"].items()) for s in rows)


@pytest.mark.parametrize("change", [
    lambda o: o.pop("storage"),
    lambda o: o.update(observed_at="2026-10-13T23:00:00+00:00"),
    lambda o: o.update(available_at="2026-10-14T00:06:00+00:00"),
    lambda o: o.update(observed_at="2026-10-14T00:08:00+00:00"),
    lambda o: o.update(future_durations={"J1": 1}),
    lambda o: o.update(future_hydraulic={"peak_a_cms": 0}),
    lambda o: o["receiving_stage"].update(uncertainty_m=0),
    lambda o: o["storage"].update(value_m=float("nan")),
    lambda o: o["receiving_stage"].update(datum="unknown"),
    lambda o: o.update(quality="unchecked"),
])
def test_invalid_or_future_observations_close_dispatch_without_engine(research, change):
    case, protocol = research
    observation = deepcopy(protocol["observations"]["LOW"])
    change(observation)
    def forbidden(*args):
        pytest.fail("Invalid observation must not invoke hydraulics")
    result = freeze_observed_policy(case, observation, None, forbidden, protocol)
    assert result["status"] == "abstained_invalid_observation"
    assert all(p["queue"] == [] for method, p in result["policies"].items() if method != "original_queue_diagnostic")


def test_future_evaluation_fields_cannot_enter_selection(research):
    case, protocol = research
    observation = protocol["observations"]["LOW"]
    scenarios = condition_development(case, observation, protocol)
    scenarios[0]["future_realised_duration"] = 1
    with pytest.raises(ValueError, match="complete frozen"):
        freeze_observed_policy(case, observation, scenarios, callback(case), protocol)


def test_policy_choices_do_not_use_future_forcing_or_realised_first_duration(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None, callback(case), protocol)
    first, second = deepcopy(protocol["evaluation_events"][0]), deepcopy(protocol["evaluation_events"][1])
    second["hydraulic"]["peak_a_cms"] = 20
    second["durations"] = {j["id"]: 1 for j in case["jobs"]}
    a = replay_observed_policy(frozen, case, first, callback(case), protocol)
    b = replay_observed_policy(frozen, case, second, callback(case), protocol)
    for x, y in zip(a["results"], b["results"]):
        if x["replay"]["events"]:
            assert x["replay"]["events"][0]["job_id"] == y["replay"]["events"][0]["job_id"]
            assert x["replay"]["events"][0]["depart_minute"] == y["replay"]["events"][0]["depart_minute"]


def test_every_operational_baseline_uses_identical_screen_and_information(research):
    case, protocol = research
    bad = lambda state, event: "J1" in state
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None, callback(case, harmful=bad), protocol)
    result = replay_observed_policy(frozen, case, protocol["evaluation_events"][0], callback(case, harmful=bad), protocol)
    assert frozen["state_screen"]["J1"]["status"] == "failed"
    for row in result["results"]:
        if not row["diagnostic_only"]:
            assert "J1" not in row["completed_jobs"]
            assert row["snapshot_sha256"] == frozen["snapshot_sha256"]
            assert row["status"] == "supported"


def test_unresolved_baseline_closes_all_policies(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None,
                                    callback(case, invalid=lambda state, event: not state), protocol)
    assert frozen["status"] == "unresolved"
    assert all(p["queue"] == [] for method, p in frozen["policies"].items() if method != "original_queue_diagnostic")


def test_numerical_error_is_not_an_admissible_state(research):
    case, protocol = research
    def flip(run, state):
        if state:
            run["nodes"]["B2"]["spill_m3"] = .051
            run["total_spill_m3"] += .051
    evidence = _Evidence(case, callback(case, half_change=flip))
    row = evidence.compare(["J1"], condition_development(case, protocol["observations"]["LOW"], protocol)[0])
    assert row["status"] == "unresolved"
    assert row["total_spill_m3"] is None


def test_small_numerical_change_that_flips_eligibility_is_unresolved(research):
    case, protocol = research
    def near_threshold(state, event):
        result = checked_fixture(case, state, event)
        if state:
            result["nodes"]["B2"]["spill_m3"] = .049
            result["total_spill_m3"] += .049
            for i, run in enumerate(result["assurance_numerics"]["runs"]):
                run["nodes"]["B2"]["spill_m3"] = .051 if i == 1 else .049
                run["total_spill_m3"] += .051 if i == 1 else .049
            half = result["assurance_numerics"]["runs"][1]
            result["assurance_numerics"].update(half_step_nodes=deepcopy(half["nodes"]), half_step_total_spill_m3=half["total_spill_m3"])
        return result
    evidence = _Evidence(case, near_threshold)
    row = evidence.compare(["J1"], condition_development(case, protocol["observations"]["LOW"], protocol)[0])
    assert row["status"] == "unresolved"
    assert any("decision changes" in error for error in row["errors"])


def test_missing_observation_replay_stays_abstained_for_every_method(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["MISSING"], None, callback(case), protocol)
    result = replay_observed_policy(frozen, case, protocol["evaluation_events"][8], callback(case), protocol)
    operational = [row for row in result["results"] if not row["diagnostic_only"]]
    assert all(row["abstained"] and not row["replay"]["events"] for row in operational)
    assert all(row["decision_status"] == "abstained_invalid_observation" for row in operational)


def test_duration_overrun_never_scores_unverified_restoration(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None, callback(case), protocol)
    result = replay_observed_policy(frozen, case, protocol["evaluation_events"][7], callback(case), protocol)
    for row in result["results"]:
        if row["method"] != "no_work":
            assert row["duration_overrun"]
            assert row["completed_jobs"] == []
            assert row["status"] == "unresolved"
            assert row["total_spill_m3"] is None


def test_harmful_intermediate_prefix_is_loss_even_when_final_is_better(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None, callback(case), protocol)
    harmful = lambda state, event: len(state) == 1
    results = replay_observed_policy(frozen, case, protocol["evaluation_events"][0], callback(case, harmful=harmful), protocol)
    summary = outcome_summary(results["results"], case["tie_m3"])
    row = next(r for r in results["results"] if r["method"] == "observed_robust")
    assert len(row["completed_jobs"]) == 2
    assert row["prefixes"][0]["status"] == "failed"
    assert row["prefixes"][-1]["status"] == "passed"
    assert row["status"] == "inadmissible"
    assert summary["by_method"]["observed_robust"]["exclusive_outcomes"]["loss"] == 1


def test_frozen_snapshot_and_protocol_tampering_rejected(research):
    case, protocol = research
    frozen = freeze_observed_policy(case, protocol["observations"]["LOW"], None, callback(case), protocol)
    modified = deepcopy(frozen)
    modified["policies"]["observed_robust"]["queue"] = []
    with pytest.raises(ValueError, match="snapshot was altered"):
        replay_observed_policy(modified, case, protocol["evaluation_events"][0], callback(case), protocol)
    protocol["observation_contract"]["maximum_age_minutes"] += 1
    with pytest.raises(ValueError, match="protocol was altered"):
        replay_observed_policy(frozen, case, protocol["evaluation_events"][0], callback(case), protocol)
