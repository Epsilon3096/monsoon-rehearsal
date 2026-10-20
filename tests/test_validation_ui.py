"""Integration checks for the research workspace; fixtures are never field evidence."""
from pathlib import Path
import json
from datetime import datetime, timedelta, timezone

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "interactive"))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    result.sidebar.checkbox(key="research_tools_enabled").check().run()
    result.sidebar.radio[0].set_value("Validation").run()
    assert not result.exception, [x.value for x in result.exception]
    return result


def button(app, label):
    return next(b for b in app.button if b.label == label)


def text_input(app, label):
    return next(b for b in app.text_input if b.label == label)


def test_readiness_does_not_invent_completed_external_validation(app):
    assert any("No actual operator review" in value.value for value in app.info)
    app.radio(key="validation_area").set_value("Policy comparison").run()
    assert not app.exception
    assert any("not a measured trial" in value.value for value in app.info)
    assert any("No scheduling advantage was demonstrated" in value.value for value in app.warning)


def test_research_store_integrity_refusal_is_visible_without_opening_controls(app, monkeypatch):
    import monsoon.operations as operations

    def refuse_open(*args, **kwargs):
        raise operations.IntegrityError("Stored evidence failed integrity verification")

    monkeypatch.setattr(operations, "OperationsStore", refuse_open)
    app.radio(key="validation_area").set_value("Operator & shadow").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("integrity verification" in value.value for value in app.error)
    assert all(b.label not in ("Sign in", "Seal shadow decision now") for b in app.button)


def test_site_intake_and_changed_source_cannot_borrow_previous_checks(app):
    original = (ROOT / "data" / "reference_case.json").read_bytes()
    app.radio(key="validation_area").set_value("Site & measurements").run()
    package = (ROOT / "data/templates/synthetic_site_v1.json").read_text(encoding="utf-8")
    app.text_area(key="validation_site_json").set_value(package).run()
    button(app, "Check site package").click().run()
    assert not app.exception, [e.value for e in app.exception]
    report = app.session_state["validation_site_result"]
    assert report["valid"] and not report["operational_activation_allowed"]
    assert not report["physical_validation_established"]
    app.text_area(key="validation_site_json").set_value('{"bad":true}').run()
    assert any("package changed" in w.value.lower() for w in app.warning)
    button(app, "Check site package").click().run()
    assert not app.exception
    assert not app.session_state["validation_site_result"]["valid"]
    assert original == (ROOT / "data/reference_case.json").read_bytes()


def test_measurement_fixture_retains_evidence_limits_and_stales_on_site_change(app):
    app.radio(key="validation_area").set_value("Site & measurements").run()
    site = (ROOT / "data/templates/synthetic_site_v1.json").read_text(encoding="utf-8")
    observations = (ROOT / "data/templates/synthetic_measurements_v1.json").read_text(encoding="utf-8")
    app.text_area(key="validation_site_json").set_value(site).run()
    app.text_area(key="validation_measurement_json").set_value(observations).run()
    button(app, "Analyse measurement package").click().run()
    assert not app.exception, [e.value for e in app.exception]
    report = app.session_state["validation_measurement_result"]
    assert report["physical_validation_established"] is False
    app.text_area(key="validation_site_json").set_value("{}").run()
    assert any("site or measurement package changed" in w.value.lower() for w in app.warning)


def test_local_setup_login_and_logout_do_not_leave_authenticated_controls(app):
    app.radio(key="validation_area").set_value("Operator & shadow").run()
    assert not app.exception, [e.value for e in app.exception]
    text_input(app, "Administrator username").set_value("fixture-admin")
    text_input(app, "Administrator display name").set_value("Synthetic test administrator")
    text_input(app, "Administrator password").set_value("This-Is-Only-A-Fixture-Password-947!")
    text_input(app, "Repeat administrator password").set_value("This-Is-Only-A-Fixture-Password-947!")
    button(app, "Create administrator").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert not app.error, [e.value for e in app.error]
    text_input(app, "Username").set_value("fixture-admin")
    text_input(app, "Password").set_value("This-Is-Only-A-Fixture-Password-947!")
    button(app, "Sign in").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert not app.error, [e.value for e in app.error]
    assert app.selectbox(key="ops_activity").value == "Accounts"
    button(app, "Sign out").click().run()
    assert not app.exception
    assert any(b.label == "Sign in" for b in app.button)
    assert all(b.label != "Create research account" for b in app.button)


@pytest.mark.parametrize("known_empty", [False, True])
def test_synthetic_operator_and_prospective_shadow_forms_preserve_seal(app, monkeypatch, known_empty):
    """A frozen test clock and invented records exercise software, not a trial."""
    import monsoon.operations as operations
    from monsoon.service import data_root
    cls = operations.OperationsStore
    now = [datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)]
    monkeypatch.setattr(operations, "OperationsStore", lambda path: cls(path, clock=lambda: now[0]))
    store = cls(data_root() / "operations.sqlite3", clock=lambda: now[0])
    store.bootstrap_admin("fixture-admin", "Fixture-Admin-Password-923!", "Fixture administrator")
    admin = store.login("fixture-admin", "Fixture-Admin-Password-923!")["token"]
    store.create_user(admin, "fixture-researcher", "Fixture-Research-Password-923!", "Synthetic software-test researcher", ["dispatcher", "reviewer", "observer"])
    token = store.login("fixture-researcher", "Fixture-Research-Password-923!")["token"]
    site = store.stage_site(token, (ROOT / "data/templates/synthetic_site_v1.json").read_bytes())
    evidence = store.add_attachment(token, "synthetic-participation.txt", b"Invented test notes, no operator participation.", "text/plain", "Explicit software fixture", now[0].isoformat())
    app.session_state["ops_token"] = token
    app.radio(key="validation_area").set_value("Operator & shadow").run()
    app.selectbox(key="ops_activity").set_value("Operator interview").run()
    for label, value in {
        "Operator's name": "Invented fixture operator",
        "Operator's actual role": "Synthetic software-test role",
        "Available crew and equipment": "No actual crew; fixture only",
        "Authorised job IDs (comma-separated)": "" if known_empty else site["data"]["package"]["jobs"][0]["id"],
        "Access restrictions and travel requirements": "Fixture access",
        "Restoration deadline and its basis": "Fixture deadline",
        "Reason for no work (required for an empty queue)": "Missing observations in this test",
    }.items():
        text_input(app, label).set_value(value)
    app.checkbox(key="ops_no_authorised_jobs").set_value(known_empty)
    for label, value in {
        "Real maintenance window and decision being reviewed": "No real window: automated synthetic form exercise",
        "Current stopping and escalation rules": "Abstain while observations are missing",
        "Required restoration and inspection evidence": "No actual work in this fixture",
        "Operator's reasoning and conditional rules": "No-work fixture comparator",
    }.items():
        next(x for x in app.text_area if x.label == label).set_value(value)
    button(app, "Seal operator baseline").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    interview = store.list_records(token, kind="interview")[0]
    assert interview["data"]["constraints"]["authorised_jobs"] == ([] if known_empty else [site["data"]["package"]["jobs"][0]["id"]])
    available = [{"id": "FIXTURE-MISSING", "source": "Synthetic fixture", "value": None,
                  **{key: now[0].isoformat() for key in ("observed_at", "issued_at", "available_at")}}]
    model = {"model_id": "FIXTURE-ABSTENTION", "policy_id": "FIXTURE-NO-CALCULATION", "generated_at": now[0].isoformat(),
             "site_package_sha256": site["data"]["package_sha256"], "inputs_sha256": operations.input_snapshot_sha256(available),
             "result": {"decision": "abstain", "queue": [], "reasons": ["Missing measurements; software fixture"]}}
    app.text_area(key="ops_reveal_snapshot").set_value(json.dumps(model)).run()
    button(app, "Record model disclosure").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    app.text_area(key="ops_interview_review").set_value("Invented review notes; no actual operator validation.")
    app.multiselect(key="ops_operator_review_attachments").set_value([evidence["id"]]).run()
    button(app, "Record operator review").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    now[0] += timedelta(seconds=10)
    app.selectbox(key="ops_activity").set_value("Shadow decisions").run()
    app.text_area(key="ops_shadow_inputs").set_value(json.dumps(available))
    app.text_area(key="ops_shadow_protocol").set_value(json.dumps({key: "Synthetic software fixture only" for key in ("protocol_id", "objective", "stopping_rules", "exception_rules", "outcome_plan")})).run()
    button(app, "Seal shadow decision now").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    shadow = store.list_records(token, kind="shadow")[0]
    sealed = shadow["data"]["decision_seal_sha256"]
    now[0] += timedelta(seconds=20)
    later = store.add_attachment(token, "synthetic-outcome.txt", b"Invented no-work outcome; software fixture only.", "text/plain", "Synthetic fixture", now[0].isoformat())
    app.run()
    app.text_input(key="ops_outcome_time").set_value(now[0].isoformat())
    app.text_area(key="ops_outcome_json").set_value(json.dumps({"executed_plan": [], "completed_jobs": [], "exceptions": [], "measured_response": None, "planning_minutes": None, "crew_minutes": None}))
    app.text_area(key="ops_outcome_notes").set_value("No actual observed trial; test fixture only.")
    app.multiselect(key="ops_outcome_attachments").set_value([later["id"]])
    button(app, "Append outcome").click().run()
    assert not app.exception and not app.error, [e.value for e in app.error]
    final = store.get_record(token, shadow["id"])
    assert final["data"]["decision_seal_sha256"] == sealed
    readiness = store.readiness(token, site["id"])
    assert not readiness["physical_validation_established"] and not readiness["pilot_authorised"]
    assert store.get_record(token, interview["id"])["data"]["baseline_plan"]["queue"] == []
    store.disconnect()
