"""Decision-first UI checks; arithmetic workflow fixtures are not field evidence."""
from copy import deepcopy
import json

import pytest
from streamlit.testing.v1 import AppTest

from monsoon import service
from monsoon.charts import TEAL
from monsoon.presentation import audit_case_options
from monsoon.service import ROOT, initialise
from test_app import assert_clean, button, use_arithmetic_app_hydraulics


pytestmark = pytest.mark.integration


@pytest.fixture
def local_data(tmp_path, monkeypatch):
    folder = tmp_path / "decision-interface"
    monkeypatch.setenv("MONSOON_DATA_DIR", str(folder))
    monkeypatch.setenv("MONSOON_CACHE_DIR", str(ROOT / "var" / "hydraulic_runs"))
    return folder


def start_app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=240).run()
    assert_clean(app)
    button(app, "Run rehearsal").click().run()
    assert_clean(app)
    return app


def visible_text(app):
    return "\n".join(item.value for kind in ("markdown", "caption", "info", "warning", "error", "success")
                     for item in app.get(kind))


def selectbox(app, label):
    return next(item for item in app.selectbox if item.label == label)


def current_audit(app):
    selected = app.session_state["selected_plan"]
    return next(audit for audit in app.session_state["plan_audits"].values()
                if audit["subject"]["queue"] == selected["queue"])


def assert_decision_before_plots(app, expected_verdict):
    """Inspect rendered tree order, not Python statement order or CSS position."""
    elements = list(app.main)
    first_plot = next(i for i, item in enumerate(elements) if item.type == "plotly_chart")
    audit_control = next(i for i, item in enumerate(elements)
                         if item.type == "button" and item.label == "Audit selected plan")
    verdict = next(i for i, item in enumerate(elements)
                   if item.type in {"info", "warning", "error", "success"}
                   and expected_verdict in item.value)
    assert verdict < first_plot
    assert audit_control < first_plot
    details = next(item for item in app.expander
                   if item.label == "Planning comparisons, achieved work and scenario details")
    assert details.proto.expanded is False


def test_empty_queue_requires_its_own_audit_then_can_be_reviewed_without_a_ticket(local_data, monkeypatch):
    use_arithmetic_app_hydraulics(monkeypatch, local_data)
    app = start_app()
    assert app.session_state["selected_plan"]["queue"]
    assert_decision_before_plots(app, "Planning candidate only")
    button(app, "Audit selected plan").click().run()
    assert_clean(app)
    first_audit = deepcopy(current_audit(app))
    assert first_audit["status"] == "passed"
    assert_decision_before_plots(app, "Selected queue · required model checks passed")

    button(app, "Select no additional work").click().run()
    assert_clean(app)
    assert app.session_state["selected_plan"]["queue"] == []
    assert len(app.session_state["plan_audits"]) == 1
    assert "Planning candidate only · stress audit outstanding" in visible_text(app)
    assert not app.success
    assert not button(app, "Audit selected plan").disabled
    # A prior passing nonempty audit cannot authorize a newly selected empty plan.
    button(app, "Save selected plan for review").click().run()
    button(app, "Open Work tickets").click().run()
    assert_clean(app)
    assert button(app, "Mark reviewed").disabled
    assert button(app, "Approve reviewed plan").disabled
    assert all(item.label != "Create work ticket" for item in app.button)

    app.sidebar.radio(key="workspace").set_value("Rehearse").run()
    # Streamlit disposes page-local widget state; explicitly choose the intended
    # queue again rather than assuming navigation retains that selection.
    if app.session_state["selected_plan"]["queue"]:
        button(app, "Select no additional work").click().run()
    button(app, "Audit selected plan").click().run()
    assert_clean(app)
    empty_audit = current_audit(app)
    assert empty_audit["status"] == "passed" and empty_audit["subject"]["queue"] == []
    assert empty_audit["audit_sha256"] != first_audit["audit_sha256"]
    assert len(app.session_state["plan_audits"]) == 2
    assert_decision_before_plots(app, "No additional discretionary work · model checks passed")
    assert "baseline flood risk remains" in visible_text(app).lower()
    assert "safe baseline" not in visible_text(app).lower()
    button(app, "Save selected plan for review").click().run()
    button(app, "Open Work tickets").click().run()
    app.selectbox(key="workflow_plan_id").select_index(0).run()
    for label in ("Mark reviewed", "Approve reviewed plan"):
        assert not button(app, label).disabled
        button(app, label).click().run()
        assert_clean(app)
    assert all(item.label != "Create work ticket" for item in app.button)
    assert "No work ticket can be issued" in visible_text(app)
    assert "Existing flood risk remains" in visible_text(app)
    case, store = initialise(local_data)
    try:
        approved = next(plan for plan in store.list_plans(case["id"]) if plan["status"] == "approved")
        assert approved["snapshot"]["queue"] == []
        assert approved["snapshot"]["assurance"]["audit_sha256"] == empty_audit["audit_sha256"]
        assert store.list_tickets(case["id"]) == []
        assert store.project_state(case["id"])["completed_jobs"] == []
    finally:
        store.disconnect()


def test_real_h2_audit_selection_and_exact_prefix_are_independent_of_planning_selector(local_data):
    """Use retained real SWMM results; do not substitute any audit or gate."""
    app = start_app()
    app.selectbox(key="inspect_scenario_id").set_value("P2").run()
    button(app, "Audit selected plan").click().run()
    assert not app.exception, [item.value for item in app.exception]
    audit = current_audit(app)
    assert audit["status"] in {"failed", "unresolved"}
    assert not audit["approval_allowed"]
    assert_decision_before_plots(app, "Approval blocked")
    options = audit_case_options(audit)
    h2_index = next(i for i, row in enumerate(options) if row["scenario_id"] == "H2")
    h2 = options[h2_index]
    assert h2["status"] == "failed"
    assert len(h2["states"]) > 1
    audit_selector = selectbox(app, "Inspect audited case / prefix")
    assert any("H2" in option for option in audit_selector.options)
    audit_selector.select_index(h2_index).run()
    first_adverse = next(i for i, state in enumerate(h2["states"]) if state["status"] == "failed")
    assert selectbox(app, "Achieved work state").value == first_adverse
    assert app.selectbox(key="inspect_scenario_id").value == "P2"
    audit_selection = selectbox(app, "Inspect audited case / prefix").value
    app.selectbox(key="inspect_scenario_id").set_value("P3").run()
    assert selectbox(app, "Inspect audited case / prefix").value == audit_selection

    previous_rows = None
    for index in (0, len(h2["states"]) - 1):
        selectbox(app, "Achieved work state").select_index(index).run()
        assert not app.exception, [item.value for item in app.exception]
        state = h2["states"][index]
        assert f'Result run: {state["run_id"]} · reference run: {state["reference_run_id"]}' in visible_text(app)
        exact_state = next(item for item in app.expander if item.label == "Node comparisons for this exact state")
        rendered_rows = exact_state.dataframe[0].value.to_dict("records")
        assert rendered_rows == state["node_comparisons"]
        if previous_rows is not None:
            assert rendered_rows != previous_rows
        previous_rows = rendered_rows
        assert app.selectbox(key="inspect_scenario_id").value == "P3"
    selectbox(app, "Inspect audited case / prefix").select_index(
        next(i for i, row in enumerate(options) if row["scenario_id"] != "H2")).run()
    assert app.selectbox(key="inspect_scenario_id").value == "P3"
    assert not app.exception, [item.value for item in app.exception]


def test_signed_overlay_uses_matching_scenario_reference_and_achieved_subset(local_data, monkeypatch):
    use_arithmetic_app_hydraulics(monkeypatch, local_data)
    original_run = service.run_state
    offsets = {"P1": 7.0, "P2": 19.0, "P3": 31.0, "P4": 43.0}

    def scenario_distinct_arithmetic(state, scenario, *args, **kwargs):
        result = original_run(state, scenario, *args, **kwargs)
        # Different no-work levels make an incorrectly paired reference observable.
        result["nodes"]["A1"]["spill_m3"] += offsets[scenario["id"]]
        result["total_spill_m3"] = sum(node["spill_m3"] for node in result["nodes"].values())
        return result

    monkeypatch.setattr(service, "run_state", scenario_distinct_arithmetic)
    app = start_app()
    episode = app.session_state["episode"]
    chosen = next(plan for plan in episode["plans"] if plan["admissible"] and
                  len({tuple(row["replay"]["completed_jobs"]) for row in plan["scenario_results"]}) > 1)
    app.selectbox(key="inspect_plan_id").set_value(chosen["id"]).run()
    app.radio(key="node_measure").set_value("Change vs no additional work").run()
    no_work = next(plan for plan in episode["plans"] if plan["queue"] == [])
    references = {row["scenario_id"]: row for row in no_work["scenario_results"]}
    case = service.load_case()
    seen_subsets = set()
    for result in chosen["scenario_results"]:
        app.selectbox(key="inspect_scenario_id").set_value(result["scenario_id"]).run()
        assert_clean(app)
        completed = result["replay"]["completed_jobs"]
        seen_subsets.add(tuple(completed))
        charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
        figure = next(fig for fig in charts if "Change vs. no additional work" in fig.get("layout", {}).get("title", {}).get("text", ""))
        for link, trace in zip(case["links"], figure["data"]):
            assert (trace["line"]["color"] == TEAL) == (link.get("job_id") in completed)
        nodes = next(trace for trace in figure["data"] if trace.get("mode") == "markers+text")
        expected = result["nodes"]["A1"]["spill_m3"] - references[result["scenario_id"]]["nodes"]["A1"]["spill_m3"]
        a1_index = next(i for i, node in enumerate(case["nodes"]) if node["id"] == "A1")
        assert f"Δ {expected:+.6g} m³" in nodes["hovertext"][a1_index]
        summary = next(item.value for item in app.dataframe
                       if list(item.value.columns) == ["Location", "Measure", "Finding"])
        assert summary.loc[summary["Location"] == "A1", "Measure"].item() == f"Δ {expected:+.6g} m³"
        assert f'Modelled scenario {result["scenario_id"]} · achieved jobs: {", ".join(completed) or "none"}' in visible_text(app)
    assert len(seen_subsets) > 1
    assert any(set(subset) != set(chosen["queue"]) for subset in seen_subsets)


def test_control_roundtrip_cannot_reenable_reviewed_plan_approval(local_data, monkeypatch):
    use_arithmetic_app_hydraulics(monkeypatch, local_data)
    app = start_app()
    button(app, "Audit selected plan").click().run()
    button(app, "Save selected plan for review").click().run()
    button(app, "Open Work tickets").click().run()
    button(app, "Mark reviewed").click().run()
    assert_clean(app)
    assert not button(app, "Approve reviewed plan").disabled
    app.sidebar.radio(key="workspace").set_value("Rehearse").run()
    app.number_input(key="deadline").set_value(150).run()
    assert button(app, "Audit selected plan").disabled
    assert button(app, "Save selected plan for review").disabled
    assert "Stale record · fresh rehearsal required" in visible_text(app)
    app.number_input(key="deadline").set_value(180).run()
    assert_clean(app)
    assert button(app, "Audit selected plan").disabled
    assert button(app, "Save selected plan for review").disabled
    button(app, "Open Work tickets").click().run()
    assert_clean(app)
    for label in ("Mark reviewed", "Approve reviewed plan", "Create work ticket"):
        assert button(app, label).disabled
    case, store = initialise(local_data)
    try:
        saved = store.list_plans(case["id"])[0]
        assert saved["is_stale"] and saved["status"] == "reviewed"
        assert saved["approval"] is None
        assert store.list_tickets(case["id"]) == []
    finally:
        store.disconnect()


def test_overlay_keeps_verified_job_when_new_empty_queue_has_no_replay_jobs(local_data, monkeypatch):
    use_arithmetic_app_hydraulics(monkeypatch, local_data)
    app = start_app()
    selected = app.session_state["selected_plan"]
    verified_job = selected["scenario_results"][0]["replay"]["events"][0]["job_id"]
    for label in ("Audit selected plan", "Save selected plan for review", "Open Work tickets",
                  "Mark reviewed", "Approve reviewed plan", "Create work ticket", "Assign crew", "Start job"):
        assert not button(app, label).disabled
        button(app, label).click().run()
        assert_clean(app)
    app.text_area[0].set_value("Arithmetic interface fixture: restoration reported for synthetic inspection.").run()
    button(app, "Report completion").click().run()
    button(app, "Verify restored condition").click().run()
    assert_clean(app)
    case, store = initialise(local_data)
    try:
        assert store.project_state(case["id"])["completed_jobs"] == [verified_job]
    finally:
        store.disconnect()
    app.sidebar.radio(key="workspace").set_value("Rehearse").run()
    button(app, "Run rehearsal").click().run()
    assert_clean(app)
    assert app.session_state["episode"]["inputs"]["already_completed"] == [verified_job]
    button(app, "Select no additional work").click().run()
    app.radio(key="node_measure").set_value("Change vs no additional work").run()
    assert_clean(app)
    chosen = app.session_state["selected_plan"]
    assert chosen["queue"] == []
    selected_scenario = app.selectbox(key="inspect_scenario_id").value
    result = next(row for row in chosen["scenario_results"] if row["scenario_id"] == selected_scenario)
    assert result["replay"]["completed_jobs"] == []
    assert result["completed_jobs"] == [verified_job]
    charts = [json.loads(item.proto.spec) for item in app.get("plotly_chart")]
    overlay = next(fig for fig in charts if "Change vs. no additional work" in fig.get("layout", {}).get("title", {}).get("text", ""))
    for link, trace in zip(case["links"], overlay["data"]):
        assert (trace["line"]["color"] == TEAL) == (link.get("job_id") == verified_job)
    summary = next(item.value for item in app.dataframe
                   if list(item.value.columns) == ["Location", "Measure", "Finding"])
    assert set(summary["Measure"]) == {"Δ +0 m³"}
