"""Additive research interfaces for continuous preparation and boundary replay."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

import plotly.graph_objects as go
import streamlit as st

from .service import ROOT, data_root
from .site_data import content_sha256, parse_json


def _json(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


def _input(label, key):
    uploaded = st.file_uploader(label + " file", type=["json"], max_upload_size=5, key=key + "_file")
    pasted = st.text_area("Or paste " + label.lower() + " JSON", key=key, height=125)
    return uploaded.getvalue() if uploaded is not None else pasted


def _signature(*values):
    return content_sha256([hashlib.sha256(v if isinstance(v, bytes) else str(v).encode()).hexdigest()
                           for v in values])


def _issues(report):
    if report.get("errors"):
        st.write("Issues retained with this attempt:")
        st.json(report["errors"], expanded=True)


def _guide(name, label):
    path = ROOT / name
    if path.is_file():
        with st.expander(label):
            st.markdown(path.read_text(encoding="utf-8"))
        st.download_button("Download " + label.lower(), path.read_bytes(), file_name=path.name,
                           key="next_guide_" + name)


def _seal_files(result, directory, verifier):
    """Anchor accepted result and each artifact before later cache display/export."""
    checked = verifier(result)
    if not checked.get("valid"):
        raise ValueError("Run evidence failed integrity verification: " + _json(checked.get("errors", [])))
    base = Path(directory).resolve()
    hashes = {}
    for name, filename in result.get("files", {}).items():
        relative = PurePosixPath(name)
        path = Path(filename).resolve()
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or not path.is_relative_to(base) or not path.is_file()):
            raise ValueError("Evidence file is missing or outside this research workspace.")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hashes:
        raise ValueError("Run evidence inventory is empty.")
    return {"result_sha256": content_sha256(result), "file_sha256": hashes}


def _bundle(result, seal, directory, verifier):
    if _seal_files(result, directory, verifier) != seal:
        raise ValueError("Run evidence changed after it was accepted. The previous result cannot be exported.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, filename in result["files"].items():
            path = Path(filename).resolve()
            if not path.is_relative_to(Path(directory).resolve()):
                raise ValueError("Run evidence moved outside this research workspace.")
            value = path.read_bytes()
            if hashlib.sha256(value).hexdigest() != seal["file_sha256"].get(name):
                raise ValueError("Run evidence changed during export.")
            archive.writestr(name, value)
    return output.getvalue()


def render_wet_preparation():
    from .bench_initialization import (run_prepared_bench, validate_prepared_bench_run,
                                       verify_prepared_bench_result)

    st.subheader("Carry water into the test")
    st.write("Run preparation and the test as one continuous simulation. The channel geometry stays fixed, and every compartment and conduit carries its water and flow into the test window.")
    st.caption("A finite preparation creates a modelled wet state. It is not a measurement of the starting state or proof that a physical rig has equilibrated. This workspace is separate from the boundary replay study.")
    mode = st.radio("Preparation input source", ["Supplied files", "Synthetic example"],
                    horizontal=True, key="wet_source")
    blobs = []
    if mode == "Synthetic example":
        st.info("Invented analytical compartment: a 7 L preparation pulse followed by a 2 L test pulse. The elevated outlet remains dry. No physical readings were collected.")
        names = ["synthetic_bench_prepared_site_v2.json", "synthetic_bench_prepared_model_v2.json",
                 "synthetic_bench_prepared_run_v1.json"]
        for name in names:
            blob = (ROOT / "data/templates" / name).read_bytes()
            blobs.append(blob)
            st.download_button("Download " + name, blob, file_name=name, key="wet_fixture_" + name)
    else:
        blobs = [_input(label, "wet_input_" + kind) for label, kind in
                 [("Bench site", "site"), ("Bench model", "model"), ("Continuous preparation and test", "run")]]
    signature = _signature(mode, *blobs)
    if st.button("Check preparation inputs", key="wet_check", disabled=not all(blobs)):
        st.session_state["wet_check_result"] = {"signature": signature,
                                                 "report": validate_prepared_bench_run(*blobs)}
    checked = st.session_state.get("wet_check_result")
    if checked and checked["signature"] == signature:
        if checked["report"].get("valid"):
            st.info("Inputs fit the supported research contract. Run both time steps to check the numerical result.")
        else:
            st.error("Preparation inputs need correction.")
        _issues(checked["report"])
    folder = data_root() / "prepared_bench_runs"
    if st.button("Run preparation and test", key="wet_run", type="primary", disabled=not all(blobs)):
        st.session_state.pop("wet_result", None)
        try:
            with st.spinner("Running the continuous history at both time steps…"):
                result = run_prepared_bench(*blobs, output_dir=folder)
                seal = _seal_files(result, folder, verify_prepared_bench_result) if result.get("files") else None
                st.session_state["wet_result"] = {"signature": signature, "report": result, "seal": seal}
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            st.error("The preparation attempt could not be completed: " + str(exc))
    saved = st.session_state.get("wet_result")
    if saved and saved["signature"] != signature:
        st.warning("The inputs changed. Run the current inputs before using a result.")
    if saved and saved["signature"] == signature:
        result = saved["report"]
        try:
            archive = _bundle(result, saved["seal"], folder, verify_prepared_bench_result) if saved["seal"] else None
            _wet_result(result)
            if archive:
                st.download_button("Download continuous-run evidence", archive,
                                   file_name="Monsoon_Prepared_Bench_Run.zip", key="wet_download")
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            st.error("Stored preparation evidence cannot be used: " + str(exc))
    _guide("BENCH_INITIALIZATION.md", "Continuous preparation guide")


def _wet_result(result):
    if result.get("valid"):
        st.success("Continuous preparation passed its numerical checks at both time steps.")
    else:
        st.warning("This preparation remains numerically unresolved. Retain the attempt and inspect the issues.")
    _issues(result)
    initial = result.get("initial_state", {})
    phases = result.get("phase_balances", {})
    if "storage_m3" in initial and "mass_balance_residual_m3" in phases.get("evaluation", {}):
        cols = st.columns(2)
        cols[0].metric("Water at test start", f"{1000 * initial['storage_m3']:.4f} L")
        cols[1].metric("Test balance residual", f"{1000 * phases['evaluation']['mass_balance_residual_m3']:.4f} L")
    if phases:
        rows = []
        for name, phase in phases.items():
            rows.append({"Window": name.title(), "Initial water (L)": 1000 * phase["initial_storage_m3"],
                         "Final water (L)": 1000 * phase["final_storage_m3"],
                         "Balance residual (L)": 1000 * phase["mass_balance_residual_m3"],
                         "Allowed numerical residual (L)": 1000 * phase["mass_balance_tolerance_m3"]})
        st.dataframe(rows, hide_index=True, width="stretch")
        prefix = phases.get("whole", {}).get("cumulative_balance_audit", {})
        if "checked_endpoints" in prefix:
            st.caption(f"Primary run: {prefix['checked_endpoints']:,} cumulative water-balance checks; "
                       f"{prefix['failed_endpoints']:,} outside the declared numerical budget. Both time steps must pass.")
    equilibrium = result.get("equilibrium", {})
    st.caption("Stationarity check: " + str(equilibrium.get("status", "not claimed")).replace("_", " ") +
               ". Numerical stationarity does not establish physical equilibrium.")
    samples = result.get("full_timeseries", [])
    if samples:
        graph = go.Figure()
        for node in samples[0].get("stage_m", {}):
            if node not in samples[0].get("receiving_stage_m", {}):
                graph.add_trace(go.Scatter(x=[r["elapsed_s"] for r in samples],
                                          y=[r["stage_m"][node] for r in samples], name="Compartment " + node))
        for node in samples[0].get("receiving_stage_m", {}):
            graph.add_trace(go.Scatter(x=[r["elapsed_s"] for r in samples],
                                      y=[r["receiving_stage_m"][node] for r in samples],
                                      name="Receiving boundary " + node, line={"dash": "dash"}))
        start = result.get("event_start_s", initial.get("simulation_elapsed_s"))
        if start is not None:
            graph.add_vline(x=start, line_dash="dot", annotation_text="Test begins")
        graph.update_layout(xaxis_title="Time since dry preparation began (s)", yaxis_title="Stage on declared datum (m)",
                            margin={"l": 10, "r": 10, "t": 35, "b": 10}, legend={"orientation": "h", "y": -0.25})
        st.plotly_chart(graph, width="stretch", key="wet_history")
    with st.expander("Complete numerical record"):
        st.json(result, expanded=False)


def _attachments(key):
    uploaded = st.file_uploader("Optional original source files", accept_multiple_files=True,
                                max_upload_size=8, key=key,
                                help="Up to eight files, 8 MiB each and 16 MiB in total.")
    if not uploaded:
        return None
    if len(uploaded) > 8 or sum(item.size for item in uploaded) > 16 * 1024 * 1024:
        raise ValueError("Retain at most eight source files and 16 MiB in total.")
    names = [item.name for item in uploaded]
    if len(set(names)) != len(names):
        raise ValueError("Source filenames must be distinct.")
    return {item.name: item.getvalue() for item in uploaded}


def render_boundary_replay():
    from .bench_replay import BenchReplayStore

    st.subheader("Replay the supplied water inputs")
    st.write("Freeze the model and input recipe, save the boundary traces, then compare the separate response readings. The simulation uses supplied flow and receiving-water levels; planned target curves remain a separate record.")
    st.caption("Dry-start research only. Wet preparation is a separate simulation capability and cannot be used in this replay study. Source references and local timestamps do not authenticate a physical experiment.")
    activity = st.radio("Boundary replay activity", ["Study workspace", "Software exercise"],
                        horizontal=True, key="replay_activity")
    if activity == "Software exercise":
        _replay_exercise()
    else:
        try:
            with BenchReplayStore(data_root() / "bench_replay.sqlite3") as store:
                _replay_studies(store)
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            st.error("Replay study could not proceed: " + str(exc))
    _guide("BENCH_REPLAY.md", "Boundary replay guide")


def _replay_studies(store):
    with st.expander("Create a separate replay study", expanded=not bool(store.list_studies())):
        title = st.text_input("Replay study title", key="replay_title")
        site = _input("Replay site package", "replay_site")
        if st.button("Create replay study", key="replay_create", disabled=not (title.strip() and site)):
            state = store.create_study(site, title=title)
            st.session_state["replay_selected"] = state["study_id"]
            st.rerun()
    studies = store.list_studies()
    if not studies:
        st.info("No replay study has been created. Start with the actual site package, or use the separately labelled software exercise to inspect the workflow.")
        return
    labels = {row["study_id"]: row["title"] + " · " + row["study_id"][:12] for row in studies}
    if st.session_state.get("replay_selected") not in labels:
        st.session_state["replay_selected"] = next(iter(labels))
    ident = st.selectbox("Replay study", list(labels), format_func=labels.get, key="replay_selected")
    state = store.get(ident)
    integrity = store.verify(ident)
    st.write("**Current stage:** " + state["status"].replace("_", " "))
    if state["evidence_kind"] == "synthetic_fixture":
        st.info("Synthetic study: its values are software fixtures, not physical measurements.")
    else:
        st.caption("Supplied measurement study. The recorded evidence still requires independent review.")
    if not integrity.get("valid"):
        st.error("Study integrity or current source identity does not match. Further recording is blocked.")
        st.json(integrity)
        return
    records = state["calibrations"] + state["validations"]
    _replay_records(records)
    pending = [r for r in records if r["prediction_status"] == "pending"]
    if pending:
        with st.expander("Retain an interrupted calculation", expanded=True):
            st.warning("A boundary receipt was saved before its calculation finished. It cannot be replaced or rerun under the same receipt. Close it as unresolved to preserve what happened.")
            receipt = st.selectbox("Interrupted receipt", [r["receipt_id"] for r in pending], key="replay_interrupted")
            reason = st.text_area("Interruption record", key="replay_interruption_reason")
            if st.button("Retain interrupted receipt as unresolved", key="replay_close_interrupted", disabled=not reason.strip()):
                store.close_interrupted_receipt(ident, state["version"], receipt_id=receipt, reason=reason)
                st.rerun()
    responses_due = [r for r in records if r["response_status"] == "pending" and r.get("prediction_seal_sha256")]
    if responses_due:
        with st.expander("Record a separate response receipt", expanded=True):
            by_id = {r["receipt_id"]: r for r in responses_due}
            receipt = st.selectbox("Sealed boundary receipt", list(by_id),
                                   format_func=lambda x: by_id[x]["event"]["event_id"], key="replay_response_receipt")
            responses = _input("Response readings", "replay_responses")
            sources = _attachments("replay_response_sources")
            st.caption("This receipt is final. Missing or invalid readings remain unresolved; this event cannot be replaced after seeing the result.")
            if st.button("Retain response readings", key="replay_record_responses", disabled=not responses):
                store.record_responses(ident, state["version"], receipt_id=receipt, responses=responses, raw_files=sources)
                st.rerun()
    if state["freeze"] is None:
        _replay_calibration(store, state)
        _replay_freeze(store, state)
    elif state["pending_validation_event_ids"]:
        _replay_withheld(store, state)
    else:
        st.info("All assigned boundary receipts are retained. Review response status and unresolved reasons below; this does not establish physical acceptance or complete the original protocol.")
    with st.expander("Integrity and full replay study"):
        st.json(integrity, expanded=False)
        st.json(state, expanded=False)
        st.download_button("Download replay study record", _json({"integrity_check": integrity, "study": state}),
                           file_name="bench-replay-study.json", key="replay_download_study")
        if st.button("Prepare complete evidence download", key="replay_prepare_export", disabled=bool(pending)):
            st.session_state.pop("replay_export", None)
            archive = store.export_evidence(ident)
            if store.get(ident)["head_sha256"] != state["head_sha256"]:
                raise ValueError("The study changed while preparing its export. Refresh before exporting.")
            st.session_state["replay_export"] = {"study_id": ident, "head_sha256": state["head_sha256"], "bytes": archive}
        saved = st.session_state.get("replay_export")
        if saved and saved["study_id"] == ident and saved["head_sha256"] == state["head_sha256"]:
            st.download_button("Download complete replay evidence", saved["bytes"],
                               file_name="Monsoon_Replay_Evidence.zip", key="replay_download_evidence")


def _replay_records(records):
    if not records:
        return
    rows, metrics = [], []
    for record in records:
        comparison = record.get("comparison") or {}
        prediction = record.get("prediction") or {}
        audit = record.get("balance_audit") or {}
        errors = (list(record.get("boundary_errors", [])) + list(comparison.get("errors", []))
                  + list(audit.get("errors", [])))
        rows.append({"Event": record["event"]["event_id"], "Boundary receipt": record["boundary_status"],
                     "Prediction": record["prediction_status"], "Numerical result": prediction.get("status", "No result"),
                     "Cumulative balance": (record.get("balance_audit") or {}).get("status", "Not available"),
                     "Qualified for comparison": record.get("prediction_qualified", False),
                     "Response receipt": record["response_status"], "Response errors": comparison.get("status", "Pending"),
                     "Unresolved reason": _json(errors) if errors else ""})
        for series in comparison.get("series", []):
            metrics.append({"Event": record["event"]["event_id"], "Response": series["series_id"],
                            "Unit": series["unit"], "Status": series["status"], "RMSE": series.get("rmse"),
                            "Bias": series.get("bias"), "Maximum absolute error": series.get("maximum_absolute_error")})
    st.subheader("Retained replay receipts")
    if any(row["Response errors"] == "unresolved" or row["Boundary receipt"] == "invalid"
           or (row["Prediction"] != "pending" and not row["Qualified for comparison"]) for row in rows):
        st.warning("An attempt remains unresolved. Its receipt and reason stay in the record.")
    st.dataframe(rows, hide_index=True, width="stretch")
    if metrics:
        st.dataframe(metrics, hide_index=True, width="stretch")
        st.caption("Response error is conditional on the supplied boundaries and model assumptions. It is not an acceptance decision or a measurement of parameter error alone.")


def _replay_calibration(store, state):
    with st.expander("Save calibration boundaries and calculate predictions"):
        values = [_input(label, "replay_cal_" + key) for label, key in
                  [("Calibration model", "model"), ("Replay recipe", "recipe"),
                   ("Calibration event assignment", "event"), ("Calibration boundary readings", "boundaries")]]
        sources = _attachments("replay_cal_sources")
        st.caption("The boundary receipt is saved before the calculation. Supply response readings separately after the prediction is sealed.")
        if st.button("Retain calibration boundaries", disabled=not all(values), key="replay_cal_record"):
            with st.spinner("Saving the boundary receipt and calculating both time steps…"):
                store.record_calibration_boundaries(state["study_id"], state["version"], model_spec=values[0],
                                                    recipe=values[1], event=values[2], boundaries=values[3], raw_files=sources)
            st.rerun()


def _replay_freeze(store, state):
    with st.expander("Freeze the model, recipe and future assignments"):
        candidates = {(r["model_sha256"], r["recipe_sha256"]): r for r in state["calibrations"]
                      if (r.get("prediction") or {}).get("valid") and r.get("prediction_qualified")
                      and (r.get("comparison") or {}).get("status") == "resolved_errors"}
        if not candidates:
            st.caption("First retain complete calibration boundaries and responses with a numerically supported prediction.")
            return
        chosen = st.selectbox("Calibration-used model and recipe", list(candidates),
                              format_func=lambda x: candidates[x]["event"]["event_id"] + " · " + x[0][:10],
                              key="replay_freeze_pair")
        st.caption('The plan contains one "events" list. Freeze future event windows and any planned targets here. Actual future boundary values arrive later and cannot be put in this plan as response measurements.')
        plan = _input("Future replay assignments", "replay_future_plan")
        rationale = st.text_area("Reason for selecting this model and recipe", key="replay_freeze_rationale")
        if st.button("Freeze replay study", key="replay_freeze", disabled=not (plan and rationale.strip())):
            parsed = parse_json(plan)
            if not isinstance(parsed, dict) or set(parsed) != {"events"}:
                raise ValueError('The future plan requires exactly one "events" list.')
            store.freeze_study(state["study_id"], state["version"], selected_model_sha256=chosen[0],
                               selected_recipe_sha256=chosen[1], validation_plan=parsed["events"], rationale=rationale)
            st.rerun()


def _replay_withheld(store, state):
    with st.expander("Save the next withheld boundary receipt", expanded=True):
        event_id = state["pending_validation_event_ids"][0]
        st.write("**Next frozen assignment:** " + event_id)
        boundaries = _input("Withheld boundary readings", "replay_val_boundaries")
        sources = _attachments("replay_val_sources")
        st.caption("The frozen recipe and model turn these inputs into the prediction. An accepted failed or missing-data attempt consumes the assignment and remains visible.")
        if st.button("Retain withheld boundaries", key="replay_val_record", disabled=not boundaries):
            with st.spinner("Saving the withheld boundaries and sealing the prediction…"):
                store.record_validation_boundaries(state["study_id"], state["version"], event_id=event_id,
                                                   boundaries=boundaries, raw_files=sources)
            st.rerun()


def _replay_exercise():
    from .bench_next_demo import run_replay_exercise, verify_replay_exercise

    st.info("Software exercise only: invented boundary inputs and responses generated by the same solver with declared offsets. This tests recording order and error arithmetic; it is not independent hydraulic validation.")
    if st.button("Run synthetic boundary exercise", type="primary", key="replay_exercise_run"):
        st.session_state.pop("replay_exercise_result", None)
        try:
            with st.spinner("Exercising boundary receipt, prediction seal, freeze and separate responses…"):
                st.session_state["replay_exercise_result"] = run_replay_exercise(data_root() / "replay_exercises")
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            st.error("The software exercise did not complete: " + str(exc))
    result = st.session_state.get("replay_exercise_result")
    if not result:
        return
    try:
        verified = verify_replay_exercise(result, data_root() / "replay_exercises")
        if not verified["valid"]:
            raise ValueError(_json(verified["errors"]))
        archive_path = Path(result["evidence_zip"])
        archive = archive_path.read_bytes()
        if hashlib.sha256(archive).hexdigest() != result["file_sha256"].get(archive_path.name):
            raise ValueError("The synthetic evidence export changed during download preparation.")
        if result["status"] == "passed":
            st.success("The boundary-first sequence and declared error arithmetic passed.")
        else:
            st.warning("The software exercise did not pass. Inspect its retained record.")
        st.dataframe(result["summary_rows"], hide_index=True, width="stretch")
        st.caption("No physical readings, calibration fit, independent accuracy result or operational approval are created by this exercise.")
        with st.expander("Exercise record"):
            st.json(result, expanded=False)
        st.download_button("Download boundary exercise record", _json(result),
                           file_name="synthetic-boundary-exercise.json", key="replay_exercise_download")
        st.download_button("Download synthetic replay evidence", archive,
                           file_name="Monsoon_Synthetic_Replay_Evidence.zip", key="replay_exercise_evidence")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        st.error("Saved exercise evidence cannot be used: " + str(exc))
