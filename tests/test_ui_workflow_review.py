"""UI controls, plus explicit arithmetic passing-audit work/inspection fixtures."""
import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT, initialise
from test_app import use_arithmetic_app_hydraulics


def button(app, label):
    return next(item for item in app.button if item.label == label)


def number(app, label):
    return next(item for item in app.number_input if item.label == label)


def clean(app):
    assert not app.exception, [item.value for item in app.exception]
    assert not app.error, [item.value for item in app.error]


def observe(data_dir):
    case, store = initialise(data_dir)
    try:
        return case, store.project_state(case["id"]), store.list_tickets(case["id"])
    finally:
        store.disconnect()


@pytest.mark.integration
def test_reverting_controls_does_not_reenable_stale_episode_save(tmp_path, monkeypatch):
    data_dir = tmp_path / "roundtrip"
    monkeypatch.setenv("MONSOON_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    button(app, "Run rehearsal").click().run()
    clean(app)
    original = app.session_state["episode"]
    assert not button(app, "Save selected plan for review").disabled
    app.number_input(key="deadline").set_value(150).run()
    assert button(app, "Save selected plan for review").disabled
    app.number_input(key="deadline").set_value(180).run()
    clean(app)
    _, state, _ = observe(data_dir)
    assert state["context_fingerprint"] == original["context_fingerprint"]
    assert state["version"] > original["state_version"]
    assert button(app, "Save selected plan for review").disabled


@pytest.mark.integration
def test_delay_stales_controls_and_failed_inspection_blocks_replanning(tmp_path, monkeypatch):
    data_dir = tmp_path / "app"
    monkeypatch.setenv("MONSOON_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    use_arithmetic_app_hydraulics(monkeypatch, tmp_path)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    clean(app)
    button(app, "Run rehearsal").click().run()
    clean(app)
    button(app, "Audit selected plan").click().run()
    clean(app)
    button(app, "Save selected plan for review").click().run()
    app.sidebar.radio[0].set_value("Work tickets").run()
    for label in ("Mark reviewed", "Approve reviewed plan", "Create work ticket", "Assign crew"):
        assert not button(app, label).disabled
        button(app, label).click().run()
        clean(app)

    app.number_input(key="delay_clock").set_value(20).run()
    button(app, "Record delay and require replanning").click().run()
    clean(app)
    case, state, tickets = observe(data_dir)
    assert state["elapsed_minutes"] == 20
    assert state["crew_location"] == "DEPOT"
    assert tickets[0]["is_stale"]
    for label in ("Mark reviewed", "Approve reviewed plan", "Create work ticket", "Assign crew", "Start job"):
        assert button(app, label).disabled, label
    assert not button(app, "Cancel unstarted ticket").disabled
    button(app, "Cancel unstarted ticket").click().run()
    clean(app)

    app.sidebar.radio[0].set_value("Rehearse").run()
    clean(app)
    assert button(app, "Save selected plan for review").disabled
    button(app, "Run rehearsal").click().run()
    clean(app)
    delayed_episode = app.session_state["episode"]
    assert delayed_episode["inputs"]["start_minute"] == 20
    assert delayed_episode["inputs"]["start_location"] == "DEPOT"
    assert delayed_episode["recommended"]["admissible"]
    assert delayed_episode["recommended"]["queue"]
    button(app, "Audit selected plan").click().run()
    clean(app)
    button(app, "Save selected plan for review").click().run()
    app.sidebar.radio[0].set_value("Work tickets").run()
    app.selectbox(key="workflow_plan_id").select_index(0).run()
    for label in ("Mark reviewed", "Approve reviewed plan", "Create work ticket", "Assign crew", "Start job"):
        assert not button(app, label).disabled, label
        button(app, label).click().run()
        clean(app)
        if label == "Create work ticket":
            app.selectbox(key="work_ticket_id").select_index(0).run()
            clean(app)
    _, state, tickets = observe(data_dir)
    assert state["elapsed_minutes"] == 30
    assert len([ticket for ticket in tickets if ticket["status"] == "cancelled"]) == 1
    active = next(ticket for ticket in tickets if ticket["status"] == "in_progress")
    first_job = active["job_id"]
    assert active["start_minute"] == 30

    app.text_area[0].set_value("Synthetic crew report: restoration reported for inspection.").run()
    first_finish = number(app, "Actual finish, including restoration (minutes)").value
    button(app, "Report completion").click().run()
    clean(app)
    app.text_area[0].set_value("Synthetic inspection: residual obstruction, restoration uncertain.").run()
    button(app, "Record failed verification").click().run()
    clean(app)
    _, state, _ = observe(data_dir)
    assert state["completed_jobs"] == []
    assert state["condition_unknown"]
    assert state["elapsed_minutes"] == first_finish
    assert state["crew_location"] == first_job
    assert button(app, "Close verified ticket").disabled
    assert button(app, "Record delay and require replanning").disabled
    app.sidebar.radio[0].set_value("Rehearse").run()
    clean(app)
    assert button(app, "Run rehearsal").disabled
    assert button(app, "Save selected plan for review").disabled

    app.sidebar.radio[0].set_value("Work tickets").run()
    clean(app)
    number(app, "Actual finish, including restoration (minutes)").set_value(first_finish + 5).run()
    app.text_area[0].set_value("Synthetic repeat inspection: specified restored condition confirmed.").run()
    button(app, "Report completion").click().run()
    button(app, "Verify restored condition").click().run()
    clean(app)
    button(app, "Close verified ticket").click().run()
    clean(app)
    _, state, _ = observe(data_dir)
    assert state["completed_jobs"] == [first_job]
    assert state["elapsed_minutes"] == first_finish + 5
    assert state["crew_location"] == first_job
    assert not state["condition_unknown"]
    app.sidebar.radio[0].set_value("Rehearse").run()
    button(app, "Run rehearsal").click().run()
    clean(app)
    verified_episode = app.session_state["episode"]
    assert verified_episode["inputs"]["already_completed"] == [first_job]
    assert verified_episode["inputs"]["start_minute"] == first_finish + 5
    assert verified_episode["inputs"]["start_location"] == first_job
