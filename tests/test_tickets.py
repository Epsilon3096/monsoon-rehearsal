import json
import sqlite3

import pytest

from monsoon.tickets import TicketStore, WorkflowError


JOBS = [
    {"id": "J1", "title": "Trunk", "max_minutes": 100, "nominal_minutes": 90, "prerequisites": []},
    {"id": "J2", "title": "Branch", "max_minutes": 55, "nominal_minutes": 45, "prerequisites": []},
    {"id": "J3", "title": "Dependent", "max_minutes": 30, "nominal_minutes": 25, "prerequisites": ["J2"]},
]


@pytest.fixture
def store(tmp_path):
    result = TicketStore(tmp_path / "tickets.db")
    result.ensure_project("case", JOBS)
    result.set_context("case", "hash-1", {"model": "v1", "deadline": 180}, "Planner")
    yield result
    result.disconnect()


def plan(store, queue=None, deadline=180, approve=True):
    state = store.project_state("case")
    result = store.save_plan("case", {"queue": ["J1", "J2"] if queue is None else queue,
                                    "supported": True, "admissible": True,
                                    "deadline_minutes": deadline, "travel_minutes": 10,
                                    "context_fingerprint": state["context_fingerprint"],
                                    "state_version": state["version"],
                                    "provenance": {"run_ids": ["swmm-1"]}}, "Planner")
    if approve:
        store.review(result["id"], "Reviewer", "Reviewed the represented states and comparators.")
        result = store.approve(result["id"], "Supervisor", "Synthetic shift authorised.")
    return result


def assigned_ticket(store, queue=None, job_id="J1", deadline=180):
    saved = plan(store, queue, deadline)
    ticket = store.create_ticket(saved["id"], job_id, "Supervisor")
    return store.assign(ticket["id"], "Crew A", "Dispatcher")


def test_durable_full_workflow_and_replan_state(store):
    ticket = assigned_ticket(store)
    original = store.get_plan(ticket["plan_id"])
    store.start(ticket["id"], 10, "Crew lead")
    assert store.project_state("case")["condition_unknown"]
    reported = store.report_completion(ticket["id"], 100, {"photo": "synthetic://after/J1", "inspection": "Restoration reported"}, "Crew lead")
    assert reported["actual_minutes"] == 90
    assert store.project_state("case")["completed_jobs"] == []
    assert store.project_state("case")["elapsed_minutes"] == 100
    store.verify(ticket["id"], True, "Synthetic inspection confirms restoration", "Verifier")
    assert store.close(ticket["id"], "Supervisor")["status"] == "closed"
    state = store.project_state("case")
    assert state["completed_jobs"] == ["J1"]
    assert state["crew_location"] == "J1"
    assert state["ready_to_replan"] is True
    assert store.get_plan(original["id"])["snapshot"] == original["snapshot"]
    assert store.get_plan(original["id"])["is_stale"]
    reopened = TicketStore(store.db_path)
    assert reopened.project_state("case") == state
    assert reopened.get_ticket(ticket["id"])["status"] == "closed"
    assert [e["action"] for e in reopened.events("case")][-6:] == ["issued", "assigned", "started", "completion_reported", "verification_accepted", "closed"]
    manifest = reopened.export_manifest("case")
    assert manifest["schema_version"] == store.SCHEMA_VERSION
    json.dumps(manifest, allow_nan=False)
    reopened.disconnect()
    store.set_context("case", "hash-after-completion", {"model": "v1", "completed": ["J1"]})
    new_plan = plan(store, ["J2", "J3"])
    new_ticket = store.create_ticket(new_plan["id"], "J2", "Supervisor")
    store.assign(new_ticket["id"], "Crew A", "Dispatcher")
    store.start(new_ticket["id"], 110, "Crew lead")
    assert store.get_ticket(new_ticket["id"])["status"] == "in_progress"


def test_same_context_is_idempotent_but_input_change_stales_review(store):
    saved = plan(store, approve=False)
    version = store.project_state("case")["version"]
    store.set_context("case", "hash-1", {"model": "v1", "deadline": 180}, "Planner")
    assert store.project_state("case")["version"] == version
    store.review(saved["id"], "Reviewer")
    store.set_context("case", "hash-2", {"model": "v2", "deadline": 180}, "Planner")
    with pytest.raises(WorkflowError, match="stale"):
        store.approve(saved["id"], "Supervisor")
    assert store.get_plan(saved["id"])["approval"] is None


def test_even_reused_hash_does_not_hide_changed_inputs(store):
    saved = plan(store)
    store.set_context("case", "hash-1", {"model": "different"})
    with pytest.raises(WorkflowError, match="stale"):
        store.create_ticket(saved["id"], "J1", "Dispatcher")


def test_approval_requires_review_and_actor(store):
    saved = plan(store, approve=False)
    with pytest.raises(WorkflowError, match="reviewed"):
        store.approve(saved["id"], "Supervisor")
    with pytest.raises(WorkflowError, match="Actor"):
        store.review(saved["id"], " ")
    assert store.get_plan(saved["id"])["status"] == "draft"


def test_failed_verification_keeps_unknown_and_blocks_replanning(store):
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 90, "Crew report", "Crew")
    store.verify(ticket["id"], False, "Residual obstruction observed", "Verifier", "residual_restriction")
    state = store.project_state("case")
    assert state["completed_jobs"] == []
    assert state["unresolved_jobs"] == ["J1"]
    assert not state["ready_to_replan"]
    with pytest.raises(WorkflowError, match="unverified"):
        store.set_context("case", "anything")
    with pytest.raises(WorkflowError, match="unverified"):
        plan(store)
    with pytest.raises(WorkflowError, match="verified"):
        store.close(ticket["id"], "Supervisor")
    store.report_completion(ticket["id"], 100, "Obstruction removed and reinspected", "Crew")
    store.verify(ticket["id"], True, "Restored state confirmed", "Verifier")
    assert store.project_state("case")["completed_jobs"] == ["J1"]
    assert store.project_state("case")["elapsed_minutes"] == 100


def test_accepted_restoration_exactly_once(store):
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 90, "Work report", "Crew")
    with pytest.raises(WorkflowError, match="binary-state"):
        store.verify(ticket["id"], True, "Partial", "Verifier", "residual_restriction")
    store.verify(ticket["id"], True, "Restored", "Verifier")
    version = store.project_state("case")["version"]
    count = len(store.events("case"))
    with pytest.raises(WorkflowError, match="completion_reported"):
        store.verify(ticket["id"], True, "Duplicate", "Verifier")
    assert store.project_state("case")["version"] == version
    assert len(store.events("case")) == count


def test_unverified_completion_never_changes_physical_state(store):
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Reported", "Crew")
    with pytest.raises(WorkflowError, match="verified"):
        store.close(ticket["id"], "Supervisor")
    assert store.project_state("case")["completed_jobs"] == []
    assert store.project_state("case")["condition_unknown"]


@pytest.mark.parametrize("bad", [-1, float("inf"), float("nan"), "10", True, None])
def test_reject_malformed_times_without_mutation(store, bad):
    ticket = assigned_ticket(store)
    before = store.export_manifest("case")
    with pytest.raises(WorkflowError):
        store.start(ticket["id"], bad, "Crew")
    assert store.get_ticket(ticket["id"])["status"] == "assigned"
    assert store.project_state("case") == before["project"]
    assert store.events("case") == before["events"]


def test_travel_and_upper_bound_return_gate(store):
    ticket = assigned_ticket(store)
    with pytest.raises(WorkflowError, match="travel"):
        store.start(ticket["id"], 0, "Crew")
    with pytest.raises(WorkflowError, match="upper duration"):
        store.start(ticket["id"], 80, "Crew")
    assert store.project_state("case")["elapsed_minutes"] == 0


def test_queue_order_is_binding(store):
    ticket = assigned_ticket(store, job_id="J2")
    with pytest.raises(WorkflowError, match="next dispatchable"):
        store.start(ticket["id"], 10, "Crew")


def test_upper_bound_deferral_allows_next_job(store):
    ticket = assigned_ticket(store, job_id="J2", deadline=100)
    store.start(ticket["id"], 10, "Crew")
    assert store.get_ticket(ticket["id"])["status"] == "in_progress"


def test_unmet_prerequisite_rejected_and_deferrable(store):
    ticket = assigned_ticket(store, queue=["J3", "J2"], job_id="J3")
    with pytest.raises(WorkflowError, match="prerequisites"):
        store.start(ticket["id"], 10, "Crew")
    saved = store.get_plan(ticket["plan_id"])
    other = store.create_ticket(saved["id"], "J2", "Supervisor")
    store.assign(other["id"], "Crew A", "Dispatcher")
    store.start(other["id"], 10, "Crew")


def test_stale_other_ticket_cannot_start_after_observation(store):
    saved = plan(store)
    first = store.create_ticket(saved["id"], "J1", "Supervisor")
    second = store.create_ticket(saved["id"], "J2", "Supervisor")
    for ticket in (first, second):
        store.assign(ticket["id"], "Crew A", "Dispatcher")
    store.start(first["id"], 10, "Crew")
    with pytest.raises(WorkflowError, match="stale"):
        store.start(second["id"], 110, "Crew")
    store.report_completion(first["id"], 100, "Report", "Crew")
    store.verify(first["id"], True, "Restored", "Verifier")
    with pytest.raises(WorkflowError, match="stale"):
        store.start(second["id"], 110, "Crew")
    assert store.cancel(second["id"], "Supervisor", "Replanning with observed times")["status"] == "cancelled"


def test_overrun_is_recorded_honestly_then_verified(store):
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    reported = store.report_completion(ticket["id"], 185, "Unexpected condition delayed work", "Crew")
    assert reported["duration_bound_exceeded"]
    assert reported["deadline_including_return_exceeded"]
    assert reported["actual_minutes"] == 175
    assert store.project_state("case")["completed_jobs"] == []
    store.verify(ticket["id"], True, "Subsequent inspection confirms restoration", "Verifier")
    assert store.project_state("case")["elapsed_minutes"] == 185


def test_snapshot_and_approvals_are_immutable_in_database(store):
    state = store.project_state("case")
    source = {"queue": ["J1"], "supported": True, "deadline_minutes": 180, "travel_minutes": 10,
              "context_fingerprint": state["context_fingerprint"], "state_version": state["version"]}
    saved = store.save_plan("case", source, "Planner")
    source["queue"].append("J2")
    assert store.get_plan(saved["id"])["queue"] == ["J1"]
    store.review(saved["id"], "Reviewer")
    store.approve(saved["id"], "Supervisor")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute("UPDATE plans SET snapshot_json='{}' WHERE id=?", (saved["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute("UPDATE approvals SET actor='Changed' WHERE plan_id=?", (saved["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._db.execute("DELETE FROM events")


def test_unsupported_snapshot_and_invalid_evidence_rejected(store):
    with pytest.raises(WorkflowError, match="supported"):
        store.save_plan("case", {"supported": False}, "Planner")
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    for evidence in (None, {}, "  ", [], 5):
        with pytest.raises(WorkflowError, match="Evidence"):
            store.report_completion(ticket["id"], 100, evidence, "Crew")
    assert store.project_state("case")["elapsed_minutes"] == 10


def test_transaction_rolls_back_if_event_write_fails(store):
    ticket = assigned_ticket(store)
    before = store.project_state("case")
    original = store._event
    def fail(*args, **kwargs):
        raise RuntimeError("Injected storage failure")
    store._event = fail
    try:
        with pytest.raises(RuntimeError, match="storage failure"):
            store.start(ticket["id"], 10, "Crew")
    finally:
        store._event = original
    assert store.get_ticket(ticket["id"])["status"] == "assigned"
    assert store.project_state("case") == before


def test_independent_connections_observe_latest_version(store):
    saved = plan(store)
    second = TicketStore(store.db_path)
    second.set_context("case", "external-new-context", {"deadline": 90})
    with pytest.raises(WorkflowError, match="stale"):
        store.create_ticket(saved["id"], "J1", "Supervisor")
    second.disconnect()


def test_job_changes_stale_previous_plan_and_require_context(store):
    saved = plan(store)
    changed = json.loads(json.dumps(JOBS))
    changed[0]["max_minutes"] = 110
    store.ensure_project("case", changed)
    assert store.get_plan(saved["id"])["is_stale"]
    with pytest.raises(WorkflowError, match="context"):
        plan(store)


def test_concurrent_verifiers_cannot_duplicate_physical_restoration(store):
    from concurrent.futures import ThreadPoolExecutor
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Report", "Crew")
    def verify_once(actor):
        connection = TicketStore(store.db_path)
        try:
            connection.verify(ticket["id"], True, "Restored", actor)
            return "accepted"
        except WorkflowError:
            return "rejected"
        finally:
            connection.disconnect()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(verify_once, ["Verifier A", "Verifier B"]))
    assert sorted(results) == ["accepted", "rejected"]
    assert store.project_state("case")["completed_jobs"] == ["J1"]
    assert len([e for e in store.events("case") if e["action"] == "verification_accepted"]) == 1


def test_verified_job_definition_cannot_reinterpret_physical_history(store):
    ticket = assigned_ticket(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Report", "Crew")
    store.verify(ticket["id"], True, "Restored", "Verifier")
    changed = json.loads(json.dumps(JOBS))
    changed[0]["intervention_patch"] = "different physical patch"
    with pytest.raises(WorkflowError, match="reinterpret"):
        store.ensure_project("case", changed)
    assert store.project_state("case")["completed_jobs"] == ["J1"]
