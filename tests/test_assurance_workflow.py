"""Adversarial workflow checks for the opt-in plan-specific assurance contract.

Synthetic objects here exercise persistence and refusal paths. They do not stand
in for SWMM results or demonstrate a safe intervention at the reference site.
"""
from copy import deepcopy
import sqlite3

import pytest

from monsoon.tickets import TicketStore, WorkflowError


JOBS = [{"id": "J1", "nominal_minutes": 45, "max_minutes": 55, "prerequisites": []}]
REQUIREMENT = {"schema_version": 1, "protocol_id": "deliberately-incomplete-test-protocol",
               "protocol_sha256": "0" * 64}


@pytest.fixture
def store(tmp_path):
    result = TicketStore(tmp_path / "workflow.sqlite3")
    result.ensure_project("case", JOBS)
    result.set_context("case", "context-requires-assurance",
                       {"deadline_minutes": 180, "assurance_requirement": REQUIREMENT})
    yield result
    result.disconnect()


def snapshot(store):
    state = store.project_state("case")
    return {"queue": ["J1"], "supported": True, "admissible": True,
            "deadline_minutes": 180, "travel_minutes": 10,
            "context_fingerprint": state["context_fingerprint"], "state_version": state["version"]}


def seed_ticket(store, plan_id, status, *, start_minute=None):
    """Emulate imported historical state with a now-unacceptable audit.

    A normal API caller cannot reach these states without earlier gate success.
    This fixture proves each later action validates again rather than trusting a
    previous status or an imported approval label.
    """
    store._db.execute("UPDATE plans SET status='approved' WHERE id=?", (plan_id,))
    store._db.execute(
        "INSERT INTO tickets(id,plan_id,project_id,job_id,status,crew,start_minute,created_at,created_by) "
        "VALUES('T-imported',?,'case','J1',?,'Crew A',?,'historical-test-fixture','Imported fixture')",
        (plan_id, status, start_minute))
    return "T-imported"


def test_context_requirement_cannot_be_removed_by_omitting_snapshot_marker(store):
    source = snapshot(store)
    assert "assurance_requirement" not in source
    saved = store.save_plan("case", source)
    assert saved["snapshot"]["assurance_requirement"] == REQUIREMENT
    assert saved["assurance_gate"]["required"] is True
    assert saved["assurance_gate"]["approval_allowed"] is False
    assert saved["status"] == "draft"
    assert saved["snapshot_integrity_valid"] is True


@pytest.mark.parametrize("replacement", [False, None, {}, {"schema_version": 1, "protocol_id": "easier"}])
def test_snapshot_cannot_weaken_requirement_declared_in_evaluated_context(store, replacement):
    source = dict(snapshot(store), assurance_requirement=replacement)
    before = store.events("case")
    with pytest.raises(WorkflowError, match="assurance requirement"):
        store.save_plan("case", source)
    assert store.events("case") == before
    assert store.list_plans("case") == []


@pytest.mark.parametrize("evidence", [None, {}, {"status": "passed"},
                                    {"status": "passed", "approval_allowed": True,
                                     "reviewed_by": "Supervisor", "override": True}])
def test_passed_label_and_supervisor_waiver_are_not_audited_evidence(store, evidence):
    source = snapshot(store)
    if evidence is not None:
        source["assurance"] = evidence
    saved = store.save_plan("case", source)
    before = store.events("case")
    with pytest.raises(WorkflowError, match="assurance"):
        store.review(saved["id"], "Supervisor", "I accept every risk and waive all audit failures.")
    assert store.get_plan(saved["id"])["status"] == "draft"
    assert store.get_plan(saved["id"])["review"] is None
    assert store.events("case") == before


@pytest.mark.parametrize("action", ["review", "approve", "create_ticket", "assign", "start"])
def test_each_advancing_action_independently_refuses_missing_required_audit(store, action):
    saved = store.save_plan("case", snapshot(store))
    if action == "review":
        invoke = lambda: store.review(saved["id"], "Reviewer")
    elif action == "approve":
        store._db.execute("UPDATE plans SET status='reviewed' WHERE id=?", (saved["id"],))
        invoke = lambda: store.approve(saved["id"], "Supervisor")
    elif action == "create_ticket":
        store._db.execute("UPDATE plans SET status='approved' WHERE id=?", (saved["id"],))
        invoke = lambda: store.create_ticket(saved["id"], "J1", "Dispatcher")
    elif action == "assign":
        ticket_id = seed_ticket(store, saved["id"], "approved")
        invoke = lambda: store.assign(ticket_id, "Crew A", "Dispatcher")
    else:
        ticket_id = seed_ticket(store, saved["id"], "assigned")
        invoke = lambda: store.start(ticket_id, 10, "Crew lead")
    before = store.export_manifest("case")
    with pytest.raises(WorkflowError, match="assurance"):
        invoke()
    after = store.export_manifest("case")
    for field in ("project", "plans", "tickets", "events"):
        assert after[field] == before[field]


def test_failed_draft_evidence_survives_restart_and_cannot_be_deleted(store):
    source = dict(snapshot(store), assurance={"status": "failed", "reasons": ["Known node harm"]})
    saved = store.save_plan("case", source)
    original = deepcopy(saved["snapshot"])
    source["assurance"]["status"] = "passed"
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute("UPDATE plans SET snapshot_json='{}' WHERE id=?", (saved["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute("DELETE FROM plans WHERE id=?", (saved["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute("UPDATE plans SET id='renamed' WHERE id=?", (saved["id"],))
    reopened = TicketStore(store.db_path)
    try:
        persisted = reopened.get_plan(saved["id"])
        assert persisted["snapshot"] == original
        assert persisted["snapshot_hash"] == saved["snapshot_hash"]
        assert persisted["assurance_gate"]["approval_allowed"] is False
        assert reopened.export_manifest("case")["plans"][0]["snapshot"]["assurance"] == original["assurance"]
    finally:
        reopened.disconnect()


def test_stale_required_plan_does_not_obstruct_observations_and_closeout(store):
    saved = store.save_plan("case", snapshot(store))
    ticket_id = seed_ticket(store, saved["id"], "in_progress", start_minute=10)
    store.set_runtime_identity("case", "new-runtime")
    assert store.get_plan(saved["id"])["is_stale"]
    report = store.report_completion(ticket_id, 200, "Observed work ran late", "Crew lead")
    assert report["duration_bound_exceeded"]
    assert report["deadline_including_return_exceeded"]
    store.verify(ticket_id, False, "Residual restriction observed", "Inspector", "residual_restriction")
    assert store.project_state("case")["condition_unknown"]
    store.report_completion(ticket_id, 210, "Further work completed", "Crew lead")
    store.verify(ticket_id, True, "Restoration physically inspected", "Inspector")
    assert store.close(ticket_id, "Supervisor")["status"] == "closed"
    assert store.project_state("case")["completed_jobs"] == ["J1"]
    assert store.project_state("case")["elapsed_minutes"] == 210
    assert store.get_plan(saved["id"])["snapshot"] == saved["snapshot"]


def test_unmarked_legacy_plan_remains_distinct_from_a_passed_assurance(store):
    store.set_context("case", "legacy-context", {"deadline_minutes": 180})
    saved = store.save_plan("case", snapshot(store))
    assert saved["assurance_gate"] == {"required": False, "valid": True,
                                       "approval_allowed": True, "status": "legacy_not_required", "reasons": []}
    store.review(saved["id"], "Reviewer")
    store.approve(saved["id"], "Supervisor")
    ticket = store.create_ticket(saved["id"], "J1", "Dispatcher")
    store.assign(ticket["id"], "Crew A", "Dispatcher")
    store.start(ticket["id"], 10, "Crew lead")
    assert store.get_ticket(ticket["id"])["status"] == "in_progress"


@pytest.mark.parametrize("value", [False, None, {}, []])
def test_malformed_opt_in_is_not_treated_as_legacy(store, value):
    store.set_context("case", "legacy-context", {"deadline_minutes": 180})
    saved = store.save_plan("case", dict(snapshot(store), assurance_requirement=value))
    assert saved["assurance_gate"]["required"]
    with pytest.raises(WorkflowError, match="assurance"):
        store.review(saved["id"], "Reviewer")


def test_status_label_cannot_replace_an_immutable_review_record(store):
    store.set_context("case", "legacy-context", {"deadline_minutes": 180})
    saved = store.save_plan("case", snapshot(store))
    store._db.execute("UPDATE plans SET status='reviewed' WHERE id=?", (saved["id"],))
    with pytest.raises(WorkflowError, match="review record"):
        store.approve(saved["id"], "Supervisor")
    assert store.get_plan(saved["id"])["approval"] is None


def test_imported_approval_for_different_snapshot_cannot_issue_work(store):
    store.set_context("case", "legacy-context", {"deadline_minutes": 180})
    saved = store.save_plan("case", snapshot(store))
    store.review(saved["id"], "Reviewer")
    store._db.execute("INSERT INTO approvals VALUES(?,?,?,?,?)",
                      (saved["id"], "Imported fixture", "Mismatched historical record", "other-snapshot", "historical-test-fixture"))
    store._db.execute("UPDATE plans SET status='approved' WHERE id=?", (saved["id"],))
    before = store.events("case")
    with pytest.raises(WorkflowError, match="approval.*snapshot"):
        store.create_ticket(saved["id"], "J1", "Dispatcher")
    assert store.events("case") == before
    assert store.list_tickets("case") == []


@pytest.fixture
def audited(tmp_path):
    """Full validator, explicit arithmetic water; no status/validator mock."""
    from monsoon import assurance
    from test_assurance import make_assurance_fixture

    case, episode, plan, source, callback = make_assurance_fixture(tmp_path / "arithmetic-raw")
    result = TicketStore(tmp_path / "audited.sqlite3")
    result.ensure_project(case["id"], case["jobs"])
    inputs = deepcopy(source["provenance"])
    inputs["assurance_requirement"] = assurance.assurance_requirement()
    inputs["evidence_origin"] = "ARITHMETIC WORKFLOW TEST DOUBLE; NOT SWMM OR FIELD EVIDENCE"
    fingerprint = assurance._hash(inputs)
    captured = result.set_context(case["id"], fingerprint, inputs)
    episode.update(inputs=inputs, context_fingerprint=fingerprint, state_version=captured["version"])
    source.update(provenance=inputs, context_fingerprint=fingerprint, state_version=captured["version"])
    source["assurance"] = assurance.audit_plan(case, episode, plan, callback)
    assert assurance.validate_audit(source)["approval_allowed"]
    try:
        yield result, case, source
    finally:
        result.disconnect()


def audited_assignment(audited):
    result, case, source = audited
    saved = result.save_plan(case["id"], source, "Arithmetic fixture planner")
    assert saved["assurance_gate"]["approval_allowed"]
    result.review(saved["id"], "Arithmetic fixture reviewer", "Software test only")
    approved = result.approve(saved["id"], "Arithmetic fixture supervisor", "No SWMM or field claim")
    assert approved["approval"]["snapshot_hash"] == saved["snapshot_hash"]
    ticket = result.create_ticket(saved["id"], source["queue"][0], "Arithmetic fixture dispatcher")
    return result.assign(ticket["id"], "Arithmetic fixture crew", "Arithmetic fixture dispatcher")


def test_complete_required_audit_survives_stamping_and_authorizes_only_audited_start(audited):
    result, case, source = audited
    ticket = audited_assignment(audited)
    saved = result.get_plan(ticket["plan_id"])
    assert saved["snapshot"]["assurance"] == source["assurance"]
    before = result.export_manifest(case["id"])
    with pytest.raises(WorkflowError, match="later than the audited|observed delay"):
        result.start(ticket["id"], 11, "Arithmetic fixture crew")
    assert result.events(case["id"]) == before["events"]
    assert result.get_ticket(ticket["id"])["status"] == "assigned"
    result.start(ticket["id"], 10, "Arithmetic fixture crew")
    assert result.get_ticket(ticket["id"])["status"] == "in_progress"
    result.set_runtime_identity(case["id"], "subsequent-runtime-change")
    result.report_completion(ticket["id"], 200, "Artificial overrun observation", "Arithmetic fixture crew")
    result.verify(ticket["id"], True, "Artificial restored-state observation", "Arithmetic fixture inspector")
    result.close(ticket["id"], "Arithmetic fixture supervisor")
    assert result.project_state(case["id"])["completed_jobs"] == [source["queue"][0]]
    assert result.get_plan(saved["id"])["snapshot"] == saved["snapshot"]


@pytest.mark.parametrize("field,value", [("queue", ["J3", "J2"]), ("deadline_minutes", 179),
                                        ("travel_minutes", 9), ("frozen_fingerprint", "f" * 64),
                                        ("id", "P-forged-display"), ("worst_spill_m3", -999),
                                        ("scenario_results", [])])
def test_complete_passed_audit_cannot_be_copied_onto_changed_plan(audited, field, value):
    result, case, source = audited
    changed = deepcopy(source)
    changed[field] = value
    saved = result.save_plan(case["id"], changed)
    assert saved["assurance_gate"]["approval_allowed"] is False
    with pytest.raises(WorkflowError, match="assurance"):
        result.review(saved["id"], "Reviewer")


def test_deleting_raw_evidence_after_approval_blocks_start_but_keeps_audit_snapshot(audited):
    from pathlib import Path

    result, case, source = audited
    ticket = audited_assignment(audited)
    raw = next(iter(source["assurance"]["hydraulic_evidence"].values()))["raw"]
    Path(raw["files"]["output"]).unlink()
    with pytest.raises(WorkflowError, match="assurance"):
        result.start(ticket["id"], 10, "Crew")
    assert result.get_ticket(ticket["id"])["status"] == "assigned"
    assert result.get_plan(ticket["plan_id"])["snapshot"]["assurance"]["status"] == "passed"
    assert not result.get_plan(ticket["plan_id"])["assurance_gate"]["approval_allowed"]
