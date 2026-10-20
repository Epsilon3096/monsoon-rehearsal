"""Research validation workspace; imported data never activate the reference model."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]


def _download(path, label):
    source = ROOT / path
    if source.is_file():
        st.download_button(label, source.read_bytes(), file_name=source.name,
                           key=f"validation_download_{path}")


def _document(path, label):
    source = ROOT / path
    if source.is_file():
        with st.expander(label):
            st.markdown(source.read_text(encoding="utf-8"))
        _download(path, f"Download {label.lower()}")


def _issues(report):
    if report.get("errors"):
        st.dataframe(report["errors"], hide_index=True, width="stretch")
    if report.get("warnings"):
        with st.expander("Evidence limitations and warnings"):
            st.dataframe(report["warnings"], hide_index=True, width="stretch")


def _readiness():
    st.subheader("Prepare the evidence, then test the decision")
    st.write("The chosen first validation route is an instrumented bench network, followed by a small township catchment. The original synthetic model and its failed recommendations remain available for inspection.")
    st.write("Software development, bench preparation and operator interviews proceed in parallel. An interview is needed to validate the real decision and operating assumptions; it does not block building or testing the prototype. A campus facilities operator is a suitable first workflow participant, with a lecturer providing a separate technical review.")
    st.dataframe([
        {"Stage": "Operator decision", "Prepared here": "Baseline before model reveal; review and disagreements", "Still needed": "Actual drainage operator and a real maintenance window"},
        {"Stage": "Physical mechanism", "Prepared here": "Site checks, measurement protocol and balance calculations", "Still needed": "Survey, sensor calibration and matched measured events"},
        {"Stage": "Policy benefit", "Prepared here": "Frozen synthetic comparison with equal-information baselines", "Still needed": "Withheld measured or independent catchment evaluation"},
        {"Stage": "Operational preparation", "Prepared here": "Authenticated research records, attachments and version review", "Still needed": "Operator agreement on the draft data contract and a reviewed site model"},
        {"Stage": "Shadow then pilot", "Prepared here": "Prospective decision seal and later outcome record", "Still needed": "Observed shadow trial and responsible engineer's pilot decision"},
    ], hide_index=True, width="stretch")
    st.info("No actual operator review, physical experiment or field shadow trial has been performed by this software work. Synthetic examples are practice records. Import review does not activate a site or authorise maintenance.")
    _document("VALIDATION_PLAN.md", "Validation plan")
    _document("PHYSICAL_VALIDATION.md", "Physical investigation protocol")
    _document("SITE_DATA_CONTRACT.md", "Draft site data contract")
    _document("OPERATIONS.md", "Research workflow guide")


def _data_intake():
    from monsoon.site_data import compare_site_versions, validate_site_package
    from monsoon.measurements import analyze_measurements

    st.subheader("Inspect site and measurement records")
    st.caption("These checks run in this session. Save a versioned record through Operator & shadow after signing in. The supported import structures are described in the draft contract.")
    _download("data/templates/synthetic_site_v1.json", "Download synthetic site example")
    _download("data/templates/synthetic_measurements_v1.json", "Download synthetic measurement example")
    _download("data/templates/bench_protocol_v1.json", "Download bench protocol")
    _document("SITE_DATA_CONTRACT.md", "Site contract and supported structures")
    uploaded = st.file_uploader("Site package file", type=["json"], key="validation_site_file")
    text = st.text_area("Or paste site package JSON", height=160, key="validation_site_json",
                        help="No missing measurement is filled automatically. The example is explicitly synthetic.")
    source = uploaded.getvalue() if uploaded is not None else text
    if st.button("Check site package", key="validation_site_check", disabled=not source):
        try:
            result = validate_site_package(source)
            st.session_state["validation_site_result"] = result
            st.session_state["validation_site_checked_source"] = source
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"Site package could not be inspected: {exc}")
    result = st.session_state.get("validation_site_result")
    current = st.session_state.get("validation_site_checked_source") == source
    if result and not current:
        st.warning("The package changed. Check it again before using its results.")
    if result and current:
        if result.get("valid"):
            st.success("Package structure accepted for staging. Physical validity and site activation are separate.")
        else:
            st.error("Package remains a draft. Resolve the reported errors before review.")
        _issues(result)
        st.json(result, expanded=False)
        st.download_button("Download site checks", json.dumps(result, indent=2, allow_nan=False),
                           file_name="site-intake-checks.json", key="validation_site_report")
    previous = st.file_uploader("Earlier site version for comparison (optional)", type=["json"], key="validation_previous_site")
    if st.button("Compare site versions", disabled=not source or previous is None, key="validation_compare"):
        try:
            st.json(compare_site_versions(previous.getvalue(), source))
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"Comparison could not be completed: {exc}")

    st.divider()
    st.subheader("Check measured balance and response")
    st.caption("A numerical example checks the calculation only. Missing intervals, unmeasured boundaries, an unsuitable datum or calibration/validation overlap cannot establish physical validation.")
    observations = st.file_uploader("Measurement package file", type=["json"], key="validation_measurement_file")
    measurement_text = st.text_area("Or paste measurement package JSON", height=160, key="validation_measurement_json")
    measurement_source = observations.getvalue() if observations is not None else measurement_text
    if st.button("Analyse measurement package", disabled=not measurement_source, key="validation_analyze"):
        try:
            report = analyze_measurements(measurement_source, site_package=source or None)
            st.session_state["validation_measurement_result"] = report
            st.session_state["validation_measurement_checked_source"] = (measurement_source, source)
        except (ValueError, TypeError, KeyError) as exc:
            st.error(f"Measurement analysis could not be completed: {exc}")
    report = st.session_state.get("validation_measurement_result")
    if report and st.session_state.get("validation_measurement_checked_source") == (measurement_source, source):
        if report.get("evidence_kind") == "synthetic_fixture":
            st.info("Synthetic arithmetic example. These values are not physical observations.")
        _issues(report)
        rows = []
        for event in report.get("event_results", []):
            balance = event.get("mass_balance", {})
            rows.append({"Event": event.get("event_id"), "Partition": event.get("partition"),
                         "Mechanism": event.get("mechanism"), "State": event.get("state"),
                         "Balance residual (m³)": balance.get("residual_m3"),
                         "Balance check": balance.get("acceptance", {}).get("status"),
                         "Combined arithmetic check": event.get("arithmetic_acceptance")})
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
            st.caption("A passing calculation is not physical validation. Inspect sensor uncertainty, missing protocol events and independent evidence review before interpreting the response.")
        st.json(report, expanded=False)
        st.download_button("Download measurement checks", json.dumps(report, indent=2, allow_nan=False),
                           file_name="measurement-checks.json", key="validation_measurement_report")
    elif report:
        st.warning("The site or measurement package changed. Analyse again to update the result.")


def _policy_evidence():
    st.subheader("A revised policy must earn its benefit")
    st.write("This research policy uses the observations available at the decision time, retains uncertainty in unobserved conditions, and applies the same information and constraints to the comparison methods. It cannot approve work through this page.")
    st.info("The new evaluation is synthetic and uses the original topology. It is not a measured trial or independent catchment validation. Previous adverse results remain part of the evidence.")
    directory = ROOT / "evidence" / "v0.3"
    reports = sorted(directory.glob("policy*.json")) if directory.exists() else []
    result_path = directory / "policy-results.json"
    if not result_path.exists():
        st.caption("The frozen policy experiment has not produced a release report yet.")
    else:
        report = json.loads(result_path.read_text(encoding="utf-8"))
        counts = report.get("counts", {})
        st.caption(f'{counts.get("designed_event_rows", 0)} designed event rows · {counts.get("reused_synthetic_networks", 0)} reused synthetic network · {counts.get("new_measured_events", 0)} measured events')
        methods = report.get("summary", {}).get("by_method", {})
        operational = [value for key, value in methods.items()
                       if not value["diagnostic_only"] and key != "no_work"]
        if operational and all(value["abstention_rows"] == counts.get("designed_event_rows") for value in operational):
            st.warning("No scheduling advantage was demonstrated. The revised policy and all three screened alternatives recommended no additional work in every designed event. Measuring the disputed hydraulic effects is the next step.")
        rows = [{"Method": value["label"], **{k.title(): v for k, v in value["exclusive_outcomes"].items()},
                 "Duration overruns": value["duration_overrun_rows"], "Historical diagnostic only": value["diagnostic_only"]}
                for value in methods.values()]
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(report.get("summary", {}).get("category_definition", ""))
        paired = report.get("summary", {}).get("observed_robust_paired_against", {})
        st.subheader("Revised policy compared with simpler methods")
        st.dataframe([{"Baseline": methods.get(key, {}).get("label", key),
                       "Revised policy better": value["positive"], "Tie": value["tie"],
                       "Revised policy worse": value["loss"], "Unresolved": value["unresolved"]}
                      for key, value in paired.items()], hide_index=True, width="stretch")
        events = sorted({row["scenario_id"] for row in report.get("results", [])})
        if events:
            event = st.selectbox("Inspect evaluation event", events, key="validation_policy_event")
            selected = [row for row in report["results"] if row["scenario_id"] == event]
            st.dataframe([{"Method": row["method_label"], "Outcome": row["status"],
                           "Completed jobs": ", ".join(row["completed_jobs"]) or "None",
                           "Spill (m³)": row["total_spill_m3"], "Crew minutes": row["crew_minutes"],
                           "Abstained": row["abstained"]} for row in selected], hide_index=True, width="stretch")
            with st.expander("Location checks, work prefixes and evidence for this event"):
                st.json(selected, expanded=False)
        with st.expander("Study limitations"):
            for limitation in report.get("limitations", []):
                st.write(limitation)
    with st.expander("Download complete frozen experiment records"):
        for path in reports:
            _download(path.relative_to(ROOT).as_posix(), f"Download {path.stem}")
    _download("data/policy_v3_protocol.json", "Download frozen evaluation protocol")


def render_validation():
    if st.session_state.get("research_tools_enabled") is not True:
        st.info("Research tools are off. Enable Show research tools in the sidebar to open experimental validation workspaces. Historical results remain available in Evidence.")
        return
    st.title("Validation workspace")
    st.caption("Research tools enabled · separate from the SWMM rehearsal and work-ticket workflow")
    st.caption("Collect the evidence that turns a synthetic demonstration into a defensible operational decision.")
    page = st.radio("Validation area", ["Readiness", "Bench preparation", "Bench model", "Wet preparation", "Boundary replay", "Conservative bench", "Site & measurements", "Policy comparison", "Operator & shadow"],
                    horizontal=True, key="validation_area")
    if page == "Readiness":
        _readiness()
    elif page == "Bench preparation":
        from monsoon.preparation_ui import render_bench_preparation
        render_bench_preparation()
    elif page == "Bench model":
        from monsoon.bench_ui import render_bench_model
        st.warning("This earlier bench workspace retains the v0.5 endpoint checks. Its synthetic pulse examples fail the newer cumulative water-balance audit. A passing result here does not qualify a prediction for the new replay study; use Boundary replay for that gate.")
        render_bench_model()
    elif page == "Wet preparation":
        from monsoon.bench_next_ui import render_wet_preparation
        render_wet_preparation()
    elif page == "Boundary replay":
        from monsoon.bench_next_ui import render_boundary_replay
        render_boundary_replay()
    elif page == "Conservative bench":
        st.warning("Experimental solver — unqualified. The custom conservative bench failed a required mesh-accuracy check on the complex pulse case. Runs here are research experiments; they do not qualify the method, replace the preserved failures, or authorise work.")
        from monsoon.bench_conservative_ui import render_conservative_bench
        render_conservative_bench()
    elif page == "Site & measurements":
        _data_intake()
    elif page == "Policy comparison":
        _policy_evidence()
    else:
        from monsoon.operations_ui import render_operations
        _document("OPERATIONS.md", "Research record formats and account guide")
        render_operations()
