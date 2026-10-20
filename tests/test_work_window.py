"""Synthetic arithmetic/record-integrity checks; none are actual observations."""
from copy import deepcopy
from hashlib import sha256
import json
import math

import pytest

from monsoon.planning import replay
from monsoon.work_window import audit_observed_window, audit_replay_window


JOBS = [{"id": "A", "nominal_minutes": 10, "max_minutes": 12},
        {"id": "B", "nominal_minutes": 8, "max_minutes": 10}]


@pytest.fixture
def planned():
    # A travel 0--2, work 2--12; B travel 12--14, work 14--22;
    # return 22--24. The original restore-and-return deadline is 40.
    return replay(["A", "B"], JOBS, 40, travel_minutes=2)


def reference(label="unit-test"):
    return {"id": label, "sha256": sha256(label.encode()).hexdigest(),
            "source": "Synthetic unit-test data only; not actual field evidence"}


def event(kind, minute, job="A", *, available=None, **extra):
    result = {"event_id": f"{kind}-{job}-{minute}", "type": kind, "minute": minute,
              "available_minute": minute if available is None else available,
              "evidence_ref": reference(f"{kind}-{job}-{minute}")}
    if kind not in {"return_started", "returned"}:
        result["job_id"] = job
    result.update(extra)
    return result


def coverage(through=15, available=None):
    return {"from_minute": 0, "through_minute": through,
            "available_minute": through if available is None else available,
            "evidence_ref": reference("synthetic coverage attestation")}


def observed(planned, events=(), *, cutoff=15, as_of=40, declared_coverage=True, **kwargs):
    declared = coverage(cutoff) if declared_coverage is True else None if declared_coverage is False else declared_coverage
    return audit_observed_window(planned, {"events": list(events), "coverage": declared},
                                 stop={"minute": cutoff, "reason": "Synthetic stop for a unit test",
                                       "evidence_ref": reference("synthetic stop")},
                                 as_of_minute=as_of, **kwargs)


def row(result, job="A"):
    return next(item for item in result["jobs"] if item["job_id"] == job)


def verified_events():
    return [event("work_started", 2), event("completion_reported", 12),
            event("condition_verified", 13, condition="restored", accepted=True)]


@pytest.mark.parametrize("cutoff,state", [
    (0, "not_departed_at_cutoff"),
    (1, "travelling_at_cutoff"),
    (2, "planned_start_boundary_not_started"),
    (2 + 1e-12, "work_interrupted_in_projection"),
    (12 - 1e-12, "work_interrupted_in_projection"),
    (12, "replay_finish_boundary_unverified"),
    (12 + 1e-12, "replay_finished_unverified"),
    (40, "replay_finished_unverified"),
])
def test_hypothetical_exact_start_and_finish_boundaries(planned, cutoff, state):
    result = audit_replay_window(planned, cutoff)
    assert result["valid"], result["errors"]
    assert row(result)["state"] == state
    assert result["decision_known_restored_jobs"] == []
    assert row(result)["observed_start_minute"] is None
    assert row(result)["verification_minute"] is None
    assert not result["stop_rule_breach"]


@pytest.mark.parametrize("cutoff,phase", [
    (22 - 1e-12, "return_not_yet_reached_in_replay"),
    (22, "planned_return_start_boundary"),
    (22 + 1e-12, "planned_return_in_progress"),
    (24 - 1e-12, "planned_return_in_progress"),
    (24, "planned_depot_arrival_boundary"),
    (24 + 1e-12, "planned_return_finished"),
])
def test_return_boundaries_are_projection_only(planned, cutoff, phase):
    result = audit_replay_window(planned, cutoff)
    assert result["return_phase"] == phase
    assert result["recovery"]["return_confirmed"] is False
    assert result["recovery"]["return_minutes"] is None


def test_no_selection_no_replay_no_mutation_and_same_source_hash(planned, monkeypatch):
    original = json.dumps(planned, sort_keys=True)
    monkeypatch.setattr("monsoon.planning.replay", lambda *a, **k: pytest.fail("Audit must not run a new replay"))
    monkeypatch.setattr("monsoon.planning.enumerate_queues", lambda *a, **k: pytest.fail("Audit must not select jobs"))
    early, late = audit_replay_window(planned, 5), audit_replay_window(planned, 35)
    assert early["replay_sha256"] == late["replay_sha256"]
    assert early["replay_job_order"] == late["replay_job_order"] == ["A", "B"]
    assert json.dumps(planned, sort_keys=True) == original
    assert early["unresolved_jobs"] == ["A"]
    assert not early["queue_reselected"] and not early["future_cutoff_used_for_job_selection"]


def test_original_unsupported_overrun_is_preserved_not_repaired():
    result = replay(["A", "B"], JOBS, 40, travel_minutes=2, actual_durations={"A": 13, "B": 8})
    report = audit_replay_window(result, 35)
    assert report["valid"]
    assert report["original_replay_status"] == "unsupported"
    assert report["original_replay_reasons"] == result["reasons"]
    assert report["decision_known_restored_jobs"] == []
    assert row(report, "B")["state"] == "not_scheduled_in_replay"


def test_claimed_replay_cannot_bypass_original_bound_plus_return_gate(planned):
    planned["events"][0].update(max_minutes=40, bound_finish_minute=42)
    report = audit_replay_window(planned, 15)
    assert not report["valid"]
    assert "bound-plus-return" in report["errors"][0]


def test_nonuniform_or_same_location_travel_cannot_pose_as_original_replay(planned):
    planned["events"][1].update(start_minute=15, finish_minute=23, bound_finish_minute=25)
    planned.update(finish_minute=25, work_finish_minute=23, crew_minutes=25)
    assert not audit_replay_window(planned, 16)["valid"]
    direct = replay(["A"], JOBS, 40, travel_minutes=2, start_location="A")
    assert audit_replay_window(direct, 1)["valid"]
    direct["events"][0].update(start_minute=2, finish_minute=12, bound_finish_minute=14)
    direct.update(finish_minute=14, work_finish_minute=12, crew_minutes=14)
    assert not audit_replay_window(direct, 1)["valid"]


def test_empty_queue_from_site_preserves_return_exposure():
    result = replay([], JOBS, 40, travel_minutes=2, start_location="A", start_minute=10)
    report = audit_replay_window(result, 11)
    assert report["valid"] and report["jobs"] == []
    assert report["status"] == "hypothetical_travel_exposure"
    assert report["recovery"]["original_return_allowance_minutes"] == 2
    assert audit_replay_window(result, 9)["stop_before_replay_start"]


def test_absent_actual_end_never_comes_from_replay_finish(planned):
    report = observed(planned, [event("work_started", 2)], cutoff=30)
    assert report["valid"]
    assert row(report)["state"] == "work_unfinished_or_unreported"
    assert row(report)["completion_reported_minute"] is None
    assert report["decision_known_restored_jobs"] == []
    assert report["unresolved_jobs"] == ["A"]
    assert not report["returned_by_as_of"]
    assert not report["recovery"]["return_confirmed"]
    assert report["recovery"]["recovery_or_return_may_be_required"]


def test_completion_reporting_needs_separate_verification(planned):
    report = observed(planned, verified_events()[:2])
    assert report["valid"]
    assert row(report)["state"] == "completion_reported_unverified"
    assert report["decision_known_restored_jobs"] == []


def test_interruption_after_completion_cannot_reuse_old_completion_evidence(planned):
    events = [event("work_started", 2), event("completion_reported", 12),
              event("work_interrupted", 14),
              event("condition_verified", 20, condition="restored", accepted=True)]
    report = observed(planned, events, cutoff=30)
    assert not report["valid"] and report["status"] == "invalid"
    assert "new work cycle" in report["errors"][0]
    assert report["decision_known_restored_jobs"] == []


def test_completion_and_accepted_verification_known_by_cutoff(planned):
    report = observed(planned, verified_events() + [event("returned", 14)])
    assert report["valid"]
    assert report["status"] == "documented_conditions_only"
    assert report["decision_known_restored_jobs"] == ["A"]
    assert row(report, "B")["state"] == "no_start_recorded_in_attested_log"
    assert not report["coverage_independently_verified"]
    assert not report["evidence_references_independently_verified"]
    assert not report["unlogged_work_independently_excluded"]


@pytest.mark.parametrize("delayed_index", [0, 1, 2])
def test_late_start_completion_or_verification_cannot_retroactively_credit_cutoff(planned, delayed_index):
    events = verified_events()
    events[delayed_index]["available_minute"] = 20
    report = observed(planned, events)
    assert report["valid"], report["errors"]
    assert report["decision_known_restored_jobs"] == []
    assert "A" in report["unresolved_jobs"]
    assert row(report)["retrospective_state_at_cutoff"] == "restored_documented"
    assert row(report)["state_as_of"] == "restored_documented"
    assert report["later_available_event_ids"] == [events[delayed_index]["event_id"]]


def test_verification_exactly_at_cutoff_is_known_but_next_float_is_later(planned):
    events = verified_events()
    events[-1]["minute"] = events[-1]["available_minute"] = 15
    on = observed(planned, events)
    events[-1]["minute"] = events[-1]["available_minute"] = math.nextafter(15, math.inf)
    after = observed(planned, events)
    assert on["decision_known_restored_jobs"] == ["A"]
    assert after["decision_known_restored_jobs"] == []
    assert row(after)["retrospective_state_at_cutoff"] == "completion_reported_unverified"
    assert row(after)["state_as_of"] == "restored_documented"


def test_later_inspection_after_crew_return_remains_separate(planned):
    events = verified_events()[:2] + [event("returned", 14),
                                    event("condition_verified", 20, condition="restored", accepted=True)]
    report = observed(planned, events)
    assert report["valid"], report["errors"]
    assert report["decision_known_restored_jobs"] == []
    assert row(report)["verification_minute"] is None
    assert row(report)["verification_as_of_minute"] == 20
    assert row(report)["state_as_of"] == "restored_documented"
    assert report["recovery"]["return_confirmed"]
    assert report["observation_events"] == events


@pytest.mark.parametrize("return_kind", ["return_started", "returned"])
@pytest.mark.parametrize("job_kind", ["completion_reported", "work_interrupted"])
def test_physical_completion_or_interruption_after_return_is_outside_cycle(planned, return_kind, job_kind):
    condition = "restored" if job_kind == "completion_reported" else "baseline"
    events = [event("work_started", 2), event(return_kind, 6), event(job_kind, 8),
              event("condition_verified", 10, condition=condition, accepted=True)]
    report = observed(planned, events)
    assert report["status"] == "invalid" and not report["valid"]
    assert report["decision_known_restored_jobs"] == []
    assert report["decision_known_baseline_jobs"] == []


@pytest.mark.parametrize("job_kind", ["completion_reported", "work_interrupted"])
def test_earlier_physical_event_can_arrive_after_return_and_inspection(planned, job_kind):
    condition = "restored" if job_kind == "completion_reported" else "baseline"
    events = [event("work_started", 2), event(job_kind, 5, available=25),
              event("return_started", 6), event("returned", 8),
              event("condition_verified", 20, condition=condition, accepted=True)]
    report = observed(planned, events)
    assert report["valid"], report["errors"]
    assert report["decision_known_restored_jobs"] == []
    assert row(report)["verification_minute"] is None
    assert row(report)["verification_as_of_minute"] == 20
    assert row(report)["state_as_of"] == ("restored_documented" if condition == "restored" else "baseline_restoration_documented")


def test_completion_exactly_at_return_departure_boundary_is_not_after(planned):
    events = [event("work_started", 2), event("return_started", 12),
              event("completion_reported", 12),
              event("condition_verified", 13, condition="restored", accepted=True), event("returned", 14)]
    report = observed(planned, events)
    assert report["valid"], report["errors"]
    assert report["decision_known_restored_jobs"] == ["A"]


@pytest.mark.parametrize("kind,accepted,state", [
    ("baseline", True, "baseline_restoration_documented"),
    ("intermediate", True, "intermediate_condition_unsupported"),
    ("unknown", True, "condition_unresolved"),
    ("baseline", False, "condition_unresolved"),
])
def test_interrupted_job_needs_explicit_condition_not_automatic_unchanged(planned, kind, accepted, state):
    events = [event("work_started", 2), event("work_interrupted", 4),
              event("condition_verified", 6, condition=kind, accepted=accepted)]
    report = observed(planned, events)
    assert report["valid"]
    assert row(report)["state"] == state
    assert report["decision_known_restored_jobs"] == []
    assert not report["unfinished_job_assumed_unchanged"]
    assert not report["unfinished_job_assumed_restored"]
    assert report["decision_known_baseline_jobs"] == (["A"] if kind == "baseline" and accepted else [])


def test_missing_coverage_and_later_coverage_cannot_assert_no_unlogged_work(planned):
    missing = observed(planned, declared_coverage=False)
    later = observed(planned, declared_coverage=coverage(15, available=20))
    for report in [missing, later]:
        assert report["valid"] and report["status"] == "unresolved"
        assert report["unresolved_jobs"] == ["A", "B"]
        assert row(report)["state"] == "no_evidence"
        assert report["documentary_coverage_at_cutoff"] == "missing_or_incomplete"
    assert later["retrospective_documentary_coverage"] == "attested_complete"
    assert row(later)["retrospective_state_at_cutoff"] == "no_start_recorded_in_attested_log"
    assert not later["unlogged_work_independently_excluded"]


@pytest.mark.parametrize("minute", [15, math.nextafter(15, math.inf), 20])
def test_actual_start_at_or_after_stop_is_recorded_breach(planned, minute):
    report = observed(planned, [event("work_started", minute, available=30)])
    assert report["valid"] and report["status"] == "observed_stop_breach"
    assert report["stop_rule_breach_event_ids"] == [f"work_started-A-{minute}"]
    assert report["decision_known_restored_jobs"] == []
    assert row(report)["observed_start_as_of_minute"] == minute


def test_start_just_before_stop_is_interrupted_unresolved_not_start_breach(planned):
    report = observed(planned, [event("work_started", math.nextafter(15, -math.inf))])
    assert report["valid"] and not report["stop_rule_breach"]
    assert row(report)["state"] == "work_unfinished_or_unreported"


def test_actual_order_deviation_and_skipped_job_are_preserved(planned):
    events = [event("work_started", 2, "B"), event("completion_reported", 5, "B"),
              event("work_started", 7, "A")]
    report = observed(planned, events)
    assert report["valid"] and report["actual_order_differs_from_replay"]
    assert report["actual_started_order"] == ["B", "A"]
    assert report["replay_job_order"] == ["A", "B"]
    shorter = replay(["A", "B"], JOBS, 18, travel_minutes=2)
    skipped = observed(shorter, [event("work_started", 2, "B")])
    assert skipped["valid"] and skipped["actual_order_differs_from_replay"]
    assert row(skipped, "B")["planned_start_minute"] is None
    assert not skipped["queue_reselected"]


@pytest.mark.parametrize("return_minute,late", [(40, False), (math.nextafter(40, math.inf), True)])
def test_later_return_is_retained_without_crediting_return_at_stop(planned, return_minute, late):
    report = observed(planned, [event("work_started", 2), event("work_interrupted", 5),
                               event("return_started", 15), event("returned", return_minute)], as_of=50)
    assert report["valid"]
    assert report["returned_by_as_of"]
    assert not report["recovery"]["return_confirmed"]
    assert report["reported_return_after_deadline"] is late
    assert "A" in report["unresolved_jobs"]


def recovery(restoration=10, inspection=5, travel=10, available=15):
    return {"restoration_minutes": restoration, "inspection_minutes": inspection,
            "return_minutes": travel, "available_minute": available,
            "source": "Unapproved synthetic duration bounds for a unit test"}


def test_recovery_sum_exact_deadline_and_just_after(planned):
    on = observed(planned, [event("work_started", 2)], recovery=recovery())
    after = observed(planned, [event("work_started", 2)], recovery=recovery(travel=10 + 1e-8))
    assert on["recovery"]["budgeted_finish_minute"] == 40
    assert on["recovery"]["fits_planned_deadline"] is True
    assert after["recovery"]["fits_planned_deadline"] is False
    assert on["unresolved_jobs"] == ["A"]
    assert not on["recovery"]["unverified_condition_cleared_by_budget"]


def test_missing_zero_and_later_recovery_estimates_never_clear_conditions(planned):
    missing = observed(planned, [event("work_started", 2)], recovery=recovery(restoration=None))
    zero = observed(planned, [event("work_started", 2)], recovery=recovery(0, 0, 0))
    later = observed(planned, [event("work_started", 2)], recovery=recovery(available=20))
    assert missing["recovery"]["status"] == "unknown_duration_bounds"
    assert missing["recovery"]["budgeted_finish_minute"] is None
    assert zero["recovery"]["budgeted_finish_minute"] == 15
    assert later["recovery"]["status"] == "later_estimate_not_available_at_cutoff"
    assert later["recovery"]["budgeted_finish_minute"] is None
    for report in (missing, zero, later):
        assert report["unresolved_jobs"] == ["A"]
        assert not report["recovery"]["recovery_plan_approved"]
        assert not report["recovery"]["return_confirmed"]


def test_storm_uncertainty_does_not_rewrite_deadline_stop_or_queue(planned):
    timing = {"earliest_minute": 5, "latest_minute": 60, "issued_minute": 0,
              "available_minute": 0, "source": "Synthetic uncertain range; not a probability distribution"}
    original = deepcopy(planned)
    report = observed(planned, [event("work_started", 2)], storm_timing=timing)
    assert report["valid"]
    assert report["stop_minute"] == 15 and report["planned_deadline_minute"] == 40
    assert report["storm_timing"]["earliest_minute"] == 5
    assert not report["storm_timing"]["used_as_deadline"]
    assert not report["storm_timing"]["used_as_stop"]
    assert not report["storm_timing"]["probability_assigned"]
    assert planned == original
    timing.update(available_minute=20)
    late = observed(planned, storm_timing=timing)
    assert late["valid"] and late["storm_timing"]["available_at_cutoff"] is False


@pytest.mark.parametrize("value", [True, False, -0.01, None, "15", math.inf, -math.inf, math.nan, 10**500])
def test_invalid_cutoff_values_fail_closed(planned, value):
    assert not audit_replay_window(planned, value)["valid"]
    assert not observed(planned, cutoff=value, declared_coverage=False)["valid"]


@pytest.mark.parametrize("field", ["minute", "available_minute"])
@pytest.mark.parametrize("value", [True, None, "2", -1, math.inf, math.nan])
def test_invalid_observation_times_fail_closed(planned, field, value):
    item = event("work_started", 2)
    item[field] = value
    report = observed(planned, [item])
    assert not report["valid"] and report["status"] == "invalid"
    assert report["jobs"] == [] and report["decision_known_restored_jobs"] == []


@pytest.mark.parametrize("mutation", [
    lambda r: r.pop("finish_minute"),
    lambda r: r.update(physical_state="unchanged"),
    lambda r: r.update(finish_minute=True),
    lambda r: r.update(completed_jobs=["A"]),
    lambda r: r.update(crew_minutes=999),
    lambda r: r.update(final_location="unknown"),
    lambda r: r["events"][0].pop("finish_minute"),
    lambda r: r["events"][0].update(actual_minutes=9),
    lambda r: r["events"][0].update(supported=False),
    lambda r: r["events"][1].update(depart_minute=13),
    lambda r: r["events"][0].update(observed=True),
    lambda r: r["skipped"].append({"job_id": "A", "reason": "duplicate"}),
])
def test_inconsistent_or_unknown_replay_fields_rejected(planned, mutation):
    mutation(planned)
    for report in (audit_replay_window(planned, 15), observed(planned)):
        assert report["status"] == "invalid" and not report["valid"]
        assert report["errors"]


@pytest.mark.parametrize("events", [
    [event("work_started", 2, "UNKNOWN")],
    [event("unknown_type", 2)],
    [event("work_started", 2, available=1)],
    [event("work_started", 2, available=41)],
    [event("work_started", 41)],
    [event("completion_reported", 12)],
    [event("condition_verified", 13, condition="restored", accepted=True)],
    [event("work_started", 2), event("condition_verified", 13, condition="restored", accepted=True)],
    [event("work_started", 2), event("completion_reported", 2)],
    [event("work_started", 2), event("work_started", 3, "B")],
    [event("work_started", 2), event("work_interrupted", 1)],
    [event("work_started", 2), event("work_started", 2)],
    [event("returned", 2), event("work_started", 3)],
    [event("return_started", 2), event("work_started", 3)],
    [event("work_started", 2), event("condition_verified", 3, condition="unknown", accepted="yes")],
    [event("work_started", 2), event("condition_verified", 3, condition="magically_unchanged", accepted=True)],
    [event("work_started", 2, observed_end=12)],
    [event("work_started", 2, evidence_ref={"id": "unsubstantiated", "sha256": "PLACEHOLDER", "source": "placeholder"})],
])
def test_bad_unknown_or_contradictory_event_contracts_return_invalid(planned, events):
    report = observed(planned, events)
    assert report["status"] == "invalid" and not report["valid"]
    assert report["decision_known_restored_jobs"] == []


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(restoration_minutes=True),
    lambda r: r.update(inspection_minutes=math.nan),
    lambda r: r.update(return_minutes=-1),
    lambda r: r.update(available_minute=41),
    lambda r: r.update(restoration_minutes=1e308, inspection_minutes=1e308),
    lambda r: r.update(approved=True),
])
def test_recovery_invalid_numbers_overflow_or_authority_claim_rejected(planned, mutation):
    estimate = recovery()
    mutation(estimate)
    report = observed(planned, recovery=estimate)
    assert report["status"] == "invalid" and not report["valid"]


def test_all_public_outputs_keep_authority_false_and_stable_ui_keys(planned):
    reports = [audit_replay_window(planned, 15), observed(planned, verified_events()),
               audit_replay_window({}, 15), observed(planned, [event("work_started", 15)])]
    for report in reports:
        assert isinstance(report["summary"], str)
        assert isinstance(report["jobs"], list) and isinstance(report["recovery"], dict)
        assert isinstance(report["decision_known_restored_jobs"], list)
        assert isinstance(report["unresolved_jobs"], list)
        for flag in ("work_authorisation_granted", "hydraulic_replay_allowed", "queue_reselected",
                     "future_cutoff_used_for_job_selection", "unfinished_job_assumed_unchanged",
                     "unfinished_job_assumed_restored", "evidence_references_independently_verified"):
            assert report[flag] is False
        json.dumps(report, allow_nan=False)


def test_bounded_inputs_cyclic_data_and_invalid_unicode_fail_closed(planned):
    huge = observed(planned, [event("work_started", 2)] * 2001)
    assert not huge["valid"]
    cycle = deepcopy(planned)
    cycle["extra"] = cycle
    assert not audit_replay_window(cycle, 15)["valid"]
    events = [event("work_started", 2, notes="\ud800")]
    assert not observed(planned, events)["valid"]


def test_unknown_storm_interval_can_be_recorded_but_never_as_a_guarantee(planned):
    timing = {"earliest_minute": None, "latest_minute": None, "issued_minute": 0,
              "available_minute": 0, "source": "No timing interval established in this unit test"}
    report = audit_replay_window(planned, 15, storm_timing=timing)
    assert report["valid"] and report["storm_timing"]["earliest_minute"] is None
    for update in ({"earliest_minute": 20, "latest_minute": 10},
                   {"earliest_minute": True}, {"issued_minute": 5},
                   {"latest_minute": math.inf}, {"guaranteed": True}):
        bad = {**timing, **update}
        assert not audit_replay_window(planned, 15, storm_timing=bad)["valid"]
