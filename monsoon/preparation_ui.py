"""Practical preparation tools; no field observation or authority is inferred."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import zipfile

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


def _document(name, label):
    path = ROOT / name
    if path.exists():
        with st.expander(label):
            st.markdown(path.read_text(encoding="utf-8"))
        st.download_button(f"Download {label.lower()}", path.read_bytes(), file_name=path.name,
                           key=f"preparation_doc_{name}")


def _report(report, key):
    if not report.get("valid"):
        st.error("The record needs correction before its timing can be interpreted.")
        if report.get("errors"):
            st.json(report["errors"], expanded=True)
    else:
        st.write(report.get("summary", "Review the recorded state and unresolved evidence below."))
        if report.get("unresolved_jobs"):
            st.warning("Condition is unresolved for: " + ", ".join(report["unresolved_jobs"]) + ". Do not substitute the pre-work geometry.")
        st.caption("Restoration evidenced by the stop: " + (", ".join(report.get("decision_known_restored_jobs", [])) or "None credited"))
    if report.get("warnings"):
        with st.expander("Assumptions and evidence limits"):
            st.json(report["warnings"], expanded=True)
    if report.get("jobs"):
        labels = {
            "not_scheduled_in_replay": "Not scheduled",
            "not_departed_at_cutoff": "Not departed in projection",
            "travelling_at_cutoff": "Travelling in projection",
            "planned_start_boundary_not_started": "At planned start; not started",
            "work_interrupted_in_projection": "Interrupted in projection",
            "replay_finish_boundary_unverified": "At predicted finish; unverified",
            "replay_finished_unverified": "Predicted finished; unverified",
            "no_evidence": "Evidence missing",
            "no_start_recorded_in_attested_log": "No start in declared log",
            "travelling_or_awaiting_work": "Travelling or awaiting work",
            "work_unfinished_or_unreported": "Unfinished or unreported",
            "work_interrupted_unverified": "Interrupted; unverified",
            "completion_reported_unverified": "Completion reported; unverified",
            "restored_documented": "Restoration documented",
            "baseline_restoration_documented": "Baseline restoration documented",
            "intermediate_condition_unsupported": "Intermediate condition; unsupported",
            "condition_unresolved": "Condition unresolved",
        }
        st.dataframe([{
            "Job": row["job_id"],
            "State at stop": labels.get(row["state"], row["state"].replace("_", " ")),
            "Predicted finish (min)": row.get("planned_finish_minute"),
            "Reported start (min)": row.get("observed_start_minute"),
            "Inspection time (min)": row.get("verification_minute"),
        } for row in report["jobs"]], hide_index=True, width="stretch")
        if report.get("mode") == "reported_observations":
            with st.expander("Later reports and full event timing"):
                st.dataframe(report["jobs"], hide_index=True, width="stretch")
    with st.expander("Complete timing audit"):
        st.json(report, expanded=False)
    st.download_button("Download timing audit", json.dumps(report, indent=2, allow_nan=False),
                       file_name="work-window-audit.json", key=f"{key}_download")


def render_work_window(case):
    from monsoon.planning import replay
    from monsoon.site_data import parse_json
    from monsoon.work_window import audit_observed_window, audit_replay_window

    st.title("Review an earlier stop")
    st.write("Inspect what an earlier stop means for a chosen work sequence. Keep the work deadline, the stop instruction and the observed physical condition separate.")
    mode = st.radio("Timing evidence", ["Synthetic timing example", "Observed records"], horizontal=True,
                    key="window_mode")
    if mode == "Synthetic timing example":
        st.info("A timing illustration using the frozen synthetic jobs. It supplies no inspection evidence or hydraulic approval. The example queue is not an approved work instruction.")
        queue_column, deadline_column = st.columns(2)
        with queue_column:
            text = st.text_input("Queue to inspect", "J4, J1, J3, J2", key="window_queue",
                                 help="An empty queue represents no additional work. This tool does not optimise or recommend the queue.")
        with deadline_column:
            deadline = st.number_input("Planned restoration-and-return deadline (minutes)", min_value=0,
                                       max_value=1440, value=180, step=5, key="window_deadline")
        scenarios = {s["id"]: s for s in case["scenarios"] if s["phase"] == "planning"}
        duration_column, cutoff_column = st.columns(2)
        with duration_column:
            selected = st.selectbox("Synthetic duration assumptions", list(scenarios),
                                    format_func=lambda key: f'{key} · {scenarios[key]["title"]}', key="window_scenario")
        with cutoff_column:
            cutoff = st.number_input("Hypothetical stop minute", min_value=0, max_value=1440,
                                     value=120, step=5, key="window_stop")
        st.caption("The chosen queue is replayed against its original deadline before the stop is inspected. The stop is never supplied to job selection. A forecast onset is not an instruction to keep working until that time.")
        try:
            queue = [part.strip().upper() for part in text.split(",") if part.strip()]
            planned = replay(queue, case["jobs"], deadline, case["travel_minutes"],
                             actual_durations=scenarios[selected]["durations"])
            report = audit_replay_window(planned, cutoff)
            st.session_state["window_hypothetical_report"] = report
            _report(report, "window_synthetic")
            with st.expander("Original timing sequence, before applying the hypothetical stop"):
                if planned["events"]:
                    st.dataframe(planned["events"], hide_index=True, width="stretch")
                else:
                    st.write("No jobs in this replay.")
                st.download_button("Download reference replay", json.dumps(planned, indent=2, allow_nan=False),
                                   file_name="synthetic-reference-replay.json", key="window_replay_download")
        except (ValueError, TypeError, KeyError) as exc:
            st.session_state.pop("window_hypothetical_report", None)
            st.error(f"Timing inputs could not be checked: {exc}")
    else:
        st.caption("Provide the intended replay and a separate observation bundle. Record actual occurrence and availability times. A completion report alone does not verify restoration; later evidence cannot change what was known at the stop.")
        intended = st.text_area("Intended replay JSON", height=150, key="window_observed_replay")
        observed = st.text_area("Observation bundle JSON", height=200, key="window_observed_bundle",
            help="Keys: observations, stop, as_of_minute; optional recovery and storm_timing. See the guide for the event contract. Do not paste invented evidence to complete this form.")
        if st.button("Audit observed window", disabled=not intended or not observed, key="window_observed_check"):
            try:
                plan = parse_json(intended)
                bundle = parse_json(observed)
                required = {"observations", "stop", "as_of_minute"}
                allowed = required | {"recovery", "storm_timing"}
                if not required <= set(bundle) or set(bundle) - allowed:
                    raise ValueError("Observation bundle requires observations, stop and as_of_minute; only recovery and storm_timing are optional.")
                report = audit_observed_window(plan, bundle["observations"], stop=bundle["stop"],
                    as_of_minute=bundle["as_of_minute"], recovery=bundle.get("recovery"),
                    storm_timing=bundle.get("storm_timing"))
                st.session_state["window_observed_report"] = report
                st.session_state["window_observed_checked"] = (intended, observed)
            except (ValueError, TypeError, KeyError) as exc:
                st.session_state.pop("window_observed_report", None)
                st.error(f"Observed record could not be checked: {exc}")
        report = st.session_state.get("window_observed_report")
        if report and st.session_state.get("window_observed_checked") == (intended, observed):
            _report(report, "window_observed")
        elif report:
            st.warning("The records changed. Audit again before using the result.")
    st.caption("This review cannot authorise field work or a hydraulic restart. An interrupted or unverified condition needs assessment; it is never automatically treated as the original geometry.")
    with st.expander("How to interpret a stop"):
        st.write("The original deadline determines the planned work. The stop time tests which activities could have happened by an earlier cutoff.")
        st.write("Predicted completion is not a condition inspection. Interrupted or unverified work remains unresolved until evidence establishes the actual condition.")
        st.caption("Observed records use minutes from the same shift origin. Include observation time and availability time; later reports cannot change what was known at the stop.")


def render_bench_preparation():
    from monsoon.bench_preparation import blank_bench_readiness, prepare_bench_pack

    st.subheader("Prepare the bench while development continues")
    st.write("Create an unfilled experiment pack now. Missing people, equipment or measurements remain visible in the preparation checklist and do not block a draft.")
    st.caption("The target is a commissioned rig by 17 October, subject to the laboratory's review. The pack is a preparation record, not evidence that construction or an experiment has happened.")
    _document("BENCH_BUILD.md", "Bench build plan")
    blank = blank_bench_readiness()
    st.download_button("Download blank readiness checklist", json.dumps(blank, indent=2, allow_nan=False),
                       file_name="bench-readiness-draft.json", key="bench_blank_download")
    uploaded = st.file_uploader("Readiness checklist (optional JSON)", type=["json"], key="bench_readiness_file")
    pasted = st.text_area("Or paste a readiness checklist", height=130, key="bench_readiness_text")
    source = uploaded.getvalue() if uploaded is not None else pasted
    if st.button("Prepare bench pack", key="bench_prepare"):
        try:
            result = prepare_bench_pack(source or None)
            st.session_state["bench_pack_result"] = result
            st.session_state["bench_pack_source"] = source
        except (ValueError, TypeError, KeyError) as exc:
            st.session_state.pop("bench_pack_result", None)
            st.error(f"Pack could not be prepared: {exc}")
    result = st.session_state.get("bench_pack_result")
    if result and st.session_state.get("bench_pack_source") == source:
        if not result.get("valid"):
            st.error("The checklist has invalid or unsupported fields. Correct them before preparing a pack.")
            st.json(result.get("errors", []), expanded=True)
            return
        st.info("Draft prepared. All experiment readings are blank. Documentary readiness does not establish commissioning, physical validation or permission to run an experiment.")
        if result.get("missing_items"):
            st.write(f'{len(result["missing_items"])} preparation items still need evidence or named participants.')
            with st.expander("Preparation still needed"):
                st.write(result["missing_items"])
        sheets = result.get("pack", {}).get("run_sheets", [])
        st.write(f"{len(sheets)} unfilled validation run sheets · fixed paired order · separate calibration required")
        st.dataframe([{key: sheet[key] for key in ("run_order", "event_id", "mechanism", "state", "paired_event_id")}
                      for sheet in sheets], hide_index=True, width="stretch")
        with st.expander("Readiness and pack details"):
            st.json(result, expanded=False)
        st.download_button("Download bench pack record", json.dumps(result, indent=2, allow_nan=False),
                           file_name="bench-preparation-pack.json", key="bench_pack_json")
        files = result.get("files", {})
        if files:
            buffer = BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, content in sorted(files.items()):
                    archive.writestr(name, content)
            st.download_button("Download complete bench pack", buffer.getvalue(),
                               file_name="Monsoon_Bench_Preparation.zip", mime="application/zip", key="bench_pack_zip")
    elif result:
        st.warning("The checklist changed. Prepare the pack again to update it.")
