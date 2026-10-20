"""UI acceptance distinguishes real adverse evidence from arithmetic workflow fixtures."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from monsoon import service
from monsoon.service import ROOT, audit_selected_plan, initialise, plan_snapshot, rehearse
from monsoon.tickets import WorkflowError


def button(app, label):
    return next(b for b in app.button if b.label == label)


def assert_clean(app):
    assert not app.exception, [e.value for e in app.exception]
    assert not app.error, [e.value for e in app.error]


def use_arithmetic_app_hydraulics(monkeypatch, tmp_path):
    """Keep the real gate and UI; substitute explicitly labelled arithmetic water.

    No verdict, audit, validator or workflow method is mocked. This fixture is
    only a positive software-path test, never a SWMM/site effectiveness result.
    """
    from test_assurance import _plain, arithmetic_checked_callback

    case = service.load_case()
    callback = arithmetic_checked_callback(tmp_path / "arithmetic-workflow-raw", case)
    monkeypatch.setattr(service, "run_state", lambda state, scenario, *args, **kwargs:
                        dict(_plain(case, state, scenario), scenario_id=scenario["id"], completed_jobs=list(state)))
    monkeypatch.setattr(service, "checked_state", lambda state, scenario, *args, **kwargs: callback(state, scenario))
    actual_context = service.context
    def labelled_context(*args, **kwargs):
        inputs = actual_context(*args, **kwargs)
        inputs["evidence_origin"] = "ARITHMETIC WORKFLOW TEST DOUBLE; NOT SWMM OR FIELD EVIDENCE"
        return inputs
    monkeypatch.setattr(service, "context", labelled_context)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "app"))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    return tmp_path / "app"


@pytest.mark.integration
def test_arithmetic_complete_ui_audit_ticket_and_verified_replan(app_env, monkeypatch):
    use_arithmetic_app_hydraulics(monkeypatch, app_env)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert_clean(app)
    button(app, "Run rehearsal").click().run()
    assert_clean(app)
    episode = app.session_state["episode"]
    assert episode["counts"]["enumerated_queues"] == 65
    assert episode["recommended"]["admissible"]
    job_id = episode["recommended"]["scenario_results"][0]["replay"]["events"][0]["job_id"]
    job = next(item for item in episode["inputs"]["case"]["jobs"] if item["id"] == job_id)
    button(app, "Audit selected plan").click().run()
    assert_clean(app)
    assert all(audit["status"] == "passed" for audit in app.session_state["plan_audits"].values())
    button(app, "Save selected plan for review").click().run()
    assert_clean(app)
    app.sidebar.radio[0].set_value("Work tickets").run()
    assert_clean(app)
    for label in ["Mark reviewed", "Approve reviewed plan", "Create work ticket", "Assign crew", "Start job"]:
        assert not button(app, label).disabled, label
        button(app, label).click().run()
        assert_clean(app)
    # The reported work alone must never restore the modeled geometry.
    app.text_area[0].set_value("Arithmetic workflow fixture: specified restoration reported; no field inspection occurred.").run()
    button(app, "Report completion").click().run()
    assert_clean(app)
    case, store = initialise(app_env)
    try:
        assert store.project_state(case["id"])["completed_jobs"] == []
        assert store.project_state(case["id"])["condition_unknown"]
    finally:
        store.disconnect()
    button(app, "Verify restored condition").click().run()
    assert_clean(app)
    button(app, "Close verified ticket").click().run()
    assert_clean(app)
    app.sidebar.radio[0].set_value("Rehearse").run()
    assert_clean(app)
    assert button(app, "Save selected plan for review").disabled
    button(app, "Run rehearsal").click().run()
    assert_clean(app)
    replanned = app.session_state["episode"]
    assert replanned["inputs"]["already_completed"] == [job_id]
    assert replanned["inputs"]["start_minute"] == 10 + job["nominal_minutes"]
    assert replanned["inputs"]["start_location"] == job_id
    assert all(job_id not in p["queue"] for p in replanned["plans"])
    app.sidebar.radio[0].set_value("Evidence").run()
    assert_clean(app)


@pytest.mark.integration
def test_real_reference_stress_failure_blocks_ui_review_and_approval(app_env):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240).run()
    button(app, "Run rehearsal").click().run()
    assert_clean(app)
    episode = app.session_state["episode"]
    assert episode["recommended"]["queue"][0] == "J4"
    button(app, "Audit selected plan").click().run()
    assert not app.exception, [e.value for e in app.exception]
    audits = list(app.session_state["plan_audits"].values())
    assert len(audits) == 1 and audits[0]["status"] in ("failed", "unresolved")
    assert not audits[0]["approval_allowed"]
    assert any("Approval blocked" in e.value for e in app.error)
    button(app, "Save selected plan for review").click().run()
    app.sidebar.radio[0].set_value("Work tickets").run()
    assert not app.exception, [e.value for e in app.exception]
    for label in ("Mark reviewed", "Approve reviewed plan", "Create work ticket"):
        assert button(app, label).disabled, label
    case, store = initialise(app_env)
    try:
        saved = store.list_plans(case["id"])[0]
        assert saved["status"] == "draft" and saved["review"] is None and saved["approval"] is None
        assert saved["snapshot"]["assurance"]["audit_sha256"] == audits[0]["audit_sha256"]
        assert not saved["assurance_gate"]["approval_allowed"]
        assert store.list_tickets(case["id"]) == []
    finally:
        store.disconnect()


@pytest.mark.integration
def test_changed_controls_invalidate_cached_ui_result(app_env):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    button(app, "Run rehearsal").click().run()
    assert not button(app, "Save selected plan for review").disabled
    app.number_input(key="deadline").set_value(150).run()
    assert_clean(app)
    assert button(app, "Save selected plan for review").disabled
    app.multiselect(key="scenario_ids").set_value([]).run()
    assert_clean(app)
    assert button(app, "Run rehearsal").disabled


@pytest.mark.integration
def test_identical_context_is_stable_and_saved_evidence_durable(app_env):
    case, store = initialise(app_env)
    scenarios = [s for s in case["scenarios"] if s["phase"] == "planning"]
    try:
        first = rehearse(case, scenarios, 180, store, app_env)
        second = rehearse(case, scenarios, 180, store, app_env)
        assert first["state_version"] == second["state_version"]
        assert first["context_fingerprint"] == second["context_fingerprint"]
        assert first["hydraulic_run_ids"] == second["hydraulic_run_ids"]
        saved = store.save_plan(case["id"], plan_snapshot(case, first, first["recommended"]), "Acceptance planner")
        assert Path(first["episode_file"]).is_file()
    finally:
        store.disconnect()
    _, reopened = initialise(app_env)
    try:
        assert not reopened.get_plan(saved["id"])["is_stale"]
        assert reopened.get_plan(saved["id"])["snapshot"]["hydraulic_run_ids"]
    finally:
        reopened.disconnect()


@pytest.mark.integration
def test_real_no_work_audit_can_be_approved_but_cannot_issue_any_job(app_env):
    case, store = initialise(app_env)
    try:
        episode = rehearse(case, [s for s in case["scenarios"] if s["phase"] == "planning"], 180, store, app_env)
        no_work = next(plan for plan in episode["plans"] if plan["queue"] == [])
        audit = audit_selected_plan(case, episode, no_work, store, app_env)
        assert audit["status"] == "passed" and audit["counts"]["unresolved"] == 0
        saved = store.save_plan(case["id"], plan_snapshot(case, episode, no_work, audit), "No-work reviewer")
        assert saved["assurance_gate"]["approval_allowed"]
        store.review(saved["id"], "No-work reviewer", "No extra work only")
        approved = store.approve(saved["id"], "No-work supervisor", "No job authorized")
        assert approved["approval"]["snapshot_hash"] == saved["snapshot_hash"]
        for job in case["jobs"]:
            with pytest.raises(WorkflowError, match="not part of the exact approved plan"):
                store.create_ticket(saved["id"], job["id"], "Dispatcher")
        assert store.list_tickets(case["id"]) == []
        assert store.project_state(case["id"])["completed_jobs"] == []
    finally:
        store.disconnect()
