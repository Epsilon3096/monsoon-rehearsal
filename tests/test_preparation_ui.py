"""New preparation flows operate on isolated, explicitly synthetic data."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from monsoon.service import ROOT


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "app-data"))
    result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not result.exception
    return result


def test_hypothetical_stop_never_reselects_queue_or_credits_inspection(app):
    app.sidebar.radio[0].set_value("Work window").run()
    assert not app.exception, [e.value for e in app.exception]
    initial = app.session_state["window_hypothetical_report"]
    assert initial["valid"]
    assert initial["work_authorisation_granted"] is False
    assert initial["hydraulic_replay_allowed"] is False
    assert initial["queue_reselected"] is False
    assert initial["decision_known_restored_jobs"] == []
    app.number_input(key="window_stop").set_value(30).run()
    changed = app.session_state["window_hypothetical_report"]
    assert changed["replay_sha256"] == initial["replay_sha256"]
    assert changed["stop_minute"] == 30
    assert changed["unresolved_jobs"]
    app.text_input(key="window_queue").set_value("UNKNOWN").run()
    assert not app.exception
    assert any("could not be checked" in item.value for item in app.error)
    assert "window_hypothetical_report" not in app.session_state


def test_observed_mode_has_no_preinvented_records_and_rejects_invalid_bundle(app):
    app.sidebar.radio[0].set_value("Work window").run()
    app.radio(key="window_mode").set_value("Observed records").run()
    assert app.text_area(key="window_observed_replay").value == ""
    assert app.text_area(key="window_observed_bundle").value == ""
    app.text_area(key="window_observed_replay").set_value("{}").run()
    app.text_area(key="window_observed_bundle").set_value('{"invalid":true}').run()
    app.button(key="window_observed_check").click().run()
    assert not app.exception
    assert any("requires observations" in item.value for item in app.error)


def test_observed_result_is_bound_to_both_inputs_and_never_fills_missing_events(app):
    from hashlib import sha256
    from monsoon.planning import replay
    planned = replay(["TEST"], [{"id": "TEST", "nominal_minutes": 10, "max_minutes": 12}],
                     40, travel_minutes=2)
    bundle = {"observations": {"events": [], "coverage": None},
              "stop": {"minute": 20, "reason": "Synthetic UI test stop",
                       "evidence_ref": {"id": "synthetic-test", "sha256": sha256(b"synthetic-test").hexdigest(),
                                        "source": "Isolated arithmetic test, not a real observation"}},
              "as_of_minute": 20}
    app.sidebar.radio[0].set_value("Work window").run()
    app.radio(key="window_mode").set_value("Observed records").run()
    app.text_area(key="window_observed_replay").set_value(json.dumps(planned)).run()
    app.text_area(key="window_observed_bundle").set_value(json.dumps(bundle)).run()
    app.button(key="window_observed_check").click().run()
    assert not app.exception
    result = app.session_state["window_observed_report"]
    assert result["valid"] and result["unresolved_jobs"] == ["TEST"]
    assert result["decision_known_restored_jobs"] == []
    assert not result["hydraulic_replay_allowed"]
    app.text_area(key="window_observed_replay").set_value(json.dumps(planned, indent=2)).run()
    assert any("records changed" in item.value for item in app.warning)
    assert not any("Restoration evidenced by the stop" in item.value for item in app.caption)
    app.button(key="window_observed_check").click().run()
    bundle["as_of_minute"] = 21
    app.text_area(key="window_observed_bundle").set_value(json.dumps(bundle)).run()
    assert any("records changed" in item.value for item in app.warning)
    app.text_area(key="window_observed_bundle").set_value("[]").run()
    app.button(key="window_observed_check").click().run()
    assert not app.exception
    assert "window_observed_report" not in app.session_state


def test_missing_participants_do_not_block_unfilled_bench_pack(app):
    app.sidebar.checkbox(key="research_tools_enabled").check().run()
    app.sidebar.radio[0].set_value("Validation").run()
    app.radio(key="validation_area").set_value("Bench preparation").run()
    app.button(key="bench_prepare").click().run()
    assert not app.exception, [e.value for e in app.exception]
    result = app.session_state["bench_pack_result"]
    assert result["valid"] and result["missing_items"]
    assert not result["documentary_requirements_complete"]
    assert not result["physical_validation_established"]
    assert len(result["pack"]["run_sheets"]) == 24
    assert all(not sheet["readings"] and not sheet["predictions"] for sheet in result["pack"]["run_sheets"])
    assert len([name for name in result["files"] if name.startswith("run-sheets/")]) == 24
    app.text_area(key="bench_readiness_text").set_value('{"bad":true}').run()
    assert any("checklist changed" in item.value.lower() for item in app.warning)
    app.button(key="bench_prepare").click().run()
    assert not app.exception
    assert any("invalid or unsupported" in item.value for item in app.error)
    assert not app.session_state["bench_pack_result"]["valid"]


def test_bench_pack_user_markup_stays_in_data_and_downloads(app):
    from monsoon.bench_preparation import blank_bench_readiness
    payload = blank_bench_readiness()
    payload["notes"] = '<script>alert("fixture")</script>'
    app.sidebar.checkbox(key="research_tools_enabled").check().run()
    app.sidebar.radio[0].set_value("Validation").run()
    app.radio(key="validation_area").set_value("Bench preparation").run()
    app.text_area(key="bench_readiness_text").set_value(json.dumps(payload)).run()
    app.button(key="bench_prepare").click().run()
    assert not app.exception
    assert app.session_state["bench_pack_result"]["valid"]
    assert not any('<script>alert("fixture")</script>' in item.value for item in app.markdown)
