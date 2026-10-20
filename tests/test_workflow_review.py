"""Adversarial workflow regressions, independent of the hydraulic solver.

The orchestration tests replace only the expensive evaluator and engine identity;
all approval, observation and concurrency transitions use real SQLite connections.
"""
from contextlib import contextmanager
from copy import deepcopy
import sqlite3

import pytest

from monsoon import service
from monsoon.planning import replay
from monsoon.tickets import TicketStore, WorkflowError


JOBS = [
    {"id": "J1", "max_minutes": 100, "nominal_minutes": 90, "prerequisites": []},
    {"id": "J2", "max_minutes": 55, "nominal_minutes": 45, "prerequisites": []},
]


@pytest.fixture
def store(tmp_path):
    result = TicketStore(tmp_path / "workflow.sqlite3")
    result.ensure_project("case", JOBS)
    result.set_context("case", "initial", {"deadline_minutes": 180})
    yield result
    result.disconnect()


def snapshot(store, queue=("J1", "J2")):
    state = store.project_state("case")
    return {"queue": list(queue), "supported": True, "admissible": True,
            "deadline_minutes": 180, "travel_minutes": 10,
            "context_fingerprint": state["context_fingerprint"],
            "state_version": state["version"]}


def assigned(store, queue=("J1", "J2"), job="J1"):
    saved = store.save_plan("case", snapshot(store, queue), "Planner")
    store.review(saved["id"], "Reviewer")
    store.approve(saved["id"], "Supervisor")
    ticket = store.create_ticket(saved["id"], job, "Dispatcher")
    return store.assign(ticket["id"], "Crew A", "Dispatcher")


def finish_and_verify(store, ticket):
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Synthetic work report", "Crew")
    store.verify(ticket["id"], True, "Synthetic restored condition", "Verifier")


@pytest.mark.parametrize("missing", ["context_fingerprint", "state_version"])
def test_saved_plan_requires_calculation_identity(store, missing):
    source = snapshot(store)
    source.pop(missing)
    before = store.events("case")
    with pytest.raises(WorkflowError):
        store.save_plan("case", source, "Planner")
    assert store.list_plans("case") == []
    assert store.events("case") == before


def test_cached_snapshot_cannot_inherit_new_input_approval(store):
    source = snapshot(store)
    store.set_context("case", "new-inputs", {"deadline_minutes": 90})
    with pytest.raises(WorkflowError, match="stale|context|version"):
        store.save_plan("case", source, "Planner")
    assert store.list_plans("case") == []


def test_same_fingerprint_cannot_hide_changed_observed_state(store):
    source = snapshot(store, ("J2",))
    ticket = assigned(store)
    finish_and_verify(store, ticket)
    assert store.project_state("case")["context_fingerprint"] == source["context_fingerprint"]
    with pytest.raises(WorkflowError, match="stale|context|version"):
        store.save_plan("case", source, "Planner")


def test_context_compare_and_set_rejects_intervening_observation(store):
    captured = store.project_state("case")
    ticket = assigned(store)
    finish_and_verify(store, ticket)
    with pytest.raises(WorkflowError, match="stale|changed|version"):
        store.set_context("case", "old-state-calculation", {"already_completed": []},
                          expected_version=captured["version"])
    assert store.project_state("case")["context_fingerprint"] == captured["context_fingerprint"]


def prepare_service(store, monkeypatch):
    # These pre-v0.2 fixtures exercise orchestration races and durable legacy
    # approvals. They do not claim to evaluate the development stress protocol;
    # required-audit workflows have separate full-contract regression coverage.
    case = {"id": "case", "title": "Synthetic orchestration race fixture",
            "model_version": "test-1", "jobs": deepcopy(JOBS), "travel_minutes": 10,
            "scenarios": [{"id": "S1", "phase": "planning", "durations": {"J1": 90, "J2": 45}}]}
    scenarios = case["scenarios"]
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(case))
    monkeypatch.setattr(service, "engine_info", lambda: {"version": "test-only"})
    monkeypatch.setattr(service, "implementation_hash", lambda: "test-only")
    current_context = service.context
    def legacy_context(*args, **kwargs):
        inputs = current_context(*args, **kwargs)
        inputs.pop("assurance_requirement", None)
        return inputs
    monkeypatch.setattr(service, "context", legacy_context)
    identity = service.canonical_hash({"case": case, "engine": service.engine_info(),
                                       "implementation": service.implementation_hash()})
    store.set_runtime_identity("case", identity)
    inputs = service.context(case, scenarios, 180, store.project_state("case"))
    inputs["operator_queue"] = None
    store.set_context("case", service.canonical_hash(inputs), inputs)
    monkeypatch.setattr(service, "evaluate_episode", lambda *args, **kwargs: {
        "recommended": {"queue": ["J2"], "admissible": True}, "plans": []})
    return case, scenarios


def test_rehearse_rejects_change_between_state_read_and_context_commit(store, monkeypatch, tmp_path):
    case, scenarios = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    second = TicketStore(store.db_path)
    invoked = False

    original_context = service.context
    def context_with_concurrent_observation(*args, **kwargs):
        nonlocal invoked
        if not invoked:
            invoked = True
            finish_and_verify(second, ticket)
        return original_context(*args, **kwargs)

    monkeypatch.setattr(service, "context", context_with_concurrent_observation)
    try:
        with pytest.raises(ValueError, match="stale|changed|version"):
            service.rehearse(case, scenarios, 180, store, root=tmp_path)
        assert invoked
        assert store.project_state("case")["completed_jobs"] == ["J1"]
    finally:
        second.disconnect()


def test_rehearse_rejects_change_after_context_commit_before_return(store, monkeypatch, tmp_path):
    case, scenarios = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    second = TicketStore(store.db_path)
    original_tx = store._tx
    armed = True

    @contextmanager
    def tx_with_concurrent_observation_after_commit():
        nonlocal armed
        with original_tx():
            yield
        if armed:
            armed = False
            finish_and_verify(second, ticket)

    monkeypatch.setattr(store, "_tx", tx_with_concurrent_observation_after_commit)
    try:
        with pytest.raises(ValueError, match="stale|changed|version"):
            service.rehearse(case, scenarios, 180, store, root=tmp_path)
        assert not armed
    finally:
        second.disconnect()


def test_rehearse_rejects_context_change_during_evaluation(store, monkeypatch, tmp_path):
    case, scenarios = prepare_service(store, monkeypatch)
    second = TicketStore(store.db_path)

    def changed_context_evaluator(*args, **kwargs):
        second.set_context("case", "new-context", {"deadline_minutes": 90})
        return {"recommended": {"queue": ["J2"], "admissible": True}, "plans": []}

    monkeypatch.setattr(service, "evaluate_episode", changed_context_evaluator)
    try:
        with pytest.raises(ValueError, match="stale|changed|version"):
            service.rehearse(case, scenarios, 180, store, root=tmp_path)
        assert not list((tmp_path / "episodes").glob("*.json"))
    finally:
        second.disconnect()


def test_model_update_invalidates_unstarted_approval_on_application_entry(store, monkeypatch, tmp_path):
    case, _ = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    changed_case = dict(case, model_version="test-2")
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(changed_case))
    _, reopened = service.initialise(root=tmp_path)
    try:
        assert reopened.get_plan(ticket["plan_id"])["is_stale"]
        with pytest.raises(WorkflowError, match="stale|changed"):
            reopened.start(ticket["id"], 10, "Crew")
    finally:
        reopened.disconnect()


def test_model_update_preserves_historical_in_progress_reporting(store, monkeypatch, tmp_path):
    case, _ = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    store.start(ticket["id"], 10, "Crew")
    changed_case = dict(case, model_version="test-2")
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(changed_case))
    _, reopened = service.initialise(root=tmp_path)
    try:
        reopened.report_completion(ticket["id"], 100, "Synthetic work report", "Crew")
        reopened.verify(ticket["id"], True, "Synthetic restored condition", "Verifier")
        assert reopened.project_state("case")["completed_jobs"] == ["J1"]
    finally:
        reopened.disconnect()


def test_unchanged_runtime_preserves_current_approval_on_application_entry(store, monkeypatch, tmp_path):
    case, _ = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(case))
    _, reopened = service.initialise(root=tmp_path)
    try:
        assert not reopened.get_plan(ticket["plan_id"])["is_stale"]
    finally:
        reopened.disconnect()


def test_reinterpreted_completed_job_blocks_planning_but_allows_historical_close(store, monkeypatch, tmp_path):
    case, _ = prepare_service(store, monkeypatch)
    ticket = assigned(store)
    finish_and_verify(store, ticket)
    changed_case = deepcopy(case)
    changed_case["model_version"] = "changed-job-definition"
    changed_case["jobs"][0]["max_minutes"] = 110
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(changed_case))
    actual_case, reopened = service.initialise(root=tmp_path)
    try:
        assert actual_case["jobs"] == case["jobs"]
        assert actual_case["planning_blocked_reason"]
        with pytest.raises(ValueError, match="accepted physical history"):
            service.context(actual_case, actual_case["scenarios"], 180, reopened.project_state("case"))
        assert reopened.close(ticket["id"], "Supervisor")["status"] == "closed"
        assert reopened.project_state("case")["completed_jobs"] == ["J1"]
    finally:
        reopened.disconnect()


def test_project_state_never_combines_old_physical_state_with_new_readiness(store, monkeypatch):
    ticket = assigned(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Synthetic report", "Crew")
    second = TicketStore(store.db_path)
    original_row = store._row
    armed = True

    def row_with_concurrent_verification(table, identifier):
        nonlocal armed
        row = original_row(table, identifier)
        if table == "projects" and armed:
            armed = False
            second.verify(ticket["id"], True, "Synthetic restored condition", "Verifier")
        return row

    monkeypatch.setattr(store, "_row", row_with_concurrent_verification)
    try:
        state = store.project_state("case")
        assert (state["completed_jobs"], state["condition_unknown"]) in [([], True), (["J1"], False)]
    finally:
        second.disconnect()


def test_export_is_one_consistent_database_snapshot(store, monkeypatch):
    ticket = assigned(store)
    store.start(ticket["id"], 10, "Crew")
    store.report_completion(ticket["id"], 100, "Synthetic report", "Crew")
    second = TicketStore(store.db_path)
    # Either a deferred reader snapshot or a serialised write-lock snapshot is
    # valid. Do not wait 30 seconds for the latter during this injected overlap.
    second._db.execute("PRAGMA busy_timeout=1")
    original_state = store.project_state
    armed = True
    deferred_verification = False

    def state_with_concurrent_verification(case_id):
        nonlocal armed, deferred_verification
        state = original_state(case_id)
        if armed:
            armed = False
            try:
                second.verify(ticket["id"], True, "Synthetic restored condition", "Verifier")
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc):
                    raise
                deferred_verification = True
        return state

    monkeypatch.setattr(store, "project_state", state_with_concurrent_verification)
    try:
        manifest = store.export_manifest("case")
        physical_accepted = "J1" in manifest["project"]["completed_jobs"]
        ticket_accepted = manifest["tickets"][0]["status"] in ("verified", "closed")
        event_accepted = any(e["action"] == "verification_accepted" for e in manifest["events"])
        assert physical_accepted == ticket_accepted == event_accepted
        if deferred_verification:
            second.verify(ticket["id"], True, "Synthetic restored condition", "Verifier")
    finally:
        second.disconnect()


def test_delay_changing_next_job_requires_rehearsal_and_new_approval(store):
    ticket = assigned(store, job="J2")
    # J2 alone is not necessarily a screened hydraulic prefix of the old plan.
    with pytest.raises(WorkflowError, match="next dispatchable"):
        store.start(ticket["id"], 80, "Crew")
    before = store.project_state("case")
    observed = store.record_delay("case", 70, "Supervisor", "Synthetic access delay")
    assert observed["elapsed_minutes"] == 70
    assert observed["crew_location"] == "DEPOT"
    assert observed["version"] == before["version"] + 1
    assert observed["context_fingerprint"] is None
    assert store.get_ticket(ticket["id"])["is_stale"]
    with pytest.raises(WorkflowError, match="stale"):
        store.start(ticket["id"], 80, "Crew")
    store.cancel(ticket["id"], "Supervisor", "Rehearse remaining time")
    store.set_context("case", "observed-delay", {"start_minute": 70, "start_location": "DEPOT"},
                      expected_version=observed["version"])
    delayed = replay(["J1", "J2"], JOBS, 180, travel_minutes=10,
                     start_minute=observed["elapsed_minutes"], start_location=observed["crew_location"])
    assert delayed["events"][0]["job_id"] == "J2"
    assert delayed["events"][0]["start_minute"] == 80
    replacement = assigned(store, job="J2")
    store.start(replacement["id"], 80, "Crew")
    assert store.get_ticket(replacement["id"])["status"] == "in_progress"


@pytest.mark.parametrize("elapsed", [0, -1, float("inf"), True, "70"])
def test_invalid_delay_does_not_mutate_state_or_audit(store, elapsed):
    before = store.export_manifest("case")
    with pytest.raises(WorkflowError):
        store.record_delay("case", elapsed, "Supervisor", "Synthetic delay")
    assert store.project_state("case") == before["project"]
    assert store.events("case") == before["events"]


def test_delay_cannot_replace_unresolved_work_observations(store):
    ticket = assigned(store)
    store.start(ticket["id"], 10, "Crew")
    with pytest.raises(WorkflowError, match="unverified"):
        store.record_delay("case", 70, "Supervisor", "Synthetic delay")
    assert store.project_state("case")["elapsed_minutes"] == 10


def test_runtime_identity_is_durable_idempotent_and_invalidates_current_plans(store):
    first = store.set_runtime_identity("case", "runtime-1")
    assert first["runtime_identity"] == "runtime-1"
    store.set_context("case", "context-runtime-1", {"runtime": "runtime-1"})
    ticket = assigned(store)
    same = store.project_state("case")
    before_events = store.events("case")
    assert store.set_runtime_identity("case", "runtime-1") == same
    assert store.events("case") == before_events
    changed = store.set_runtime_identity("case", "runtime-2")
    assert changed["version"] == same["version"] + 1
    assert changed["context_fingerprint"] is None
    assert store.get_ticket(ticket["id"])["is_stale"]
    with pytest.raises(WorkflowError, match="stale"):
        store.start(ticket["id"], 10, "Crew")
    reopened = TicketStore(store.db_path)
    try:
        assert reopened.project_state("case")["runtime_identity"] == "runtime-2"
    finally:
        reopened.disconnect()


def test_runtime_change_during_work_keeps_original_observation_contract(store):
    store.set_runtime_identity("case", "runtime-1")
    store.set_context("case", "context-runtime-1", {"runtime": "runtime-1"})
    ticket = assigned(store)
    original = store.get_plan(ticket["plan_id"])["snapshot"]
    store.start(ticket["id"], 10, "Crew")
    changed = store.set_runtime_identity("case", "runtime-2")
    assert changed["condition_unknown"]
    store.report_completion(ticket["id"], 100, "Synthetic old-scope work report", "Crew")
    store.verify(ticket["id"], True, "Synthetic old-scope restoration confirmed", "Verifier")
    store.close(ticket["id"], "Supervisor")
    assert store.project_state("case")["completed_jobs"] == ["J1"]
    assert store.get_plan(ticket["plan_id"])["snapshot"] == original


def test_version_one_database_migrates_without_rewriting_history(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    old = TicketStore(database)
    old.SCHEMA_VERSION = 1
    old.ensure_project("case", JOBS)
    original_events = old.events("case")
    old.disconnect()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE runtime_identities")
        connection.execute("PRAGMA user_version=1")
    upgraded = TicketStore(database)
    try:
        assert upgraded.events("case") == original_events
        assert upgraded.project_state("case")["runtime_identity"] is None
        upgraded.set_runtime_identity("case", "runtime-after-upgrade")
        assert upgraded._db.execute("PRAGMA user_version").fetchone()[0] == upgraded.SCHEMA_VERSION
    finally:
        upgraded.disconnect()
