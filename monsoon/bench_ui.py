"""Local bench research workspace; no imported record activates a drainage site."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile

import streamlit as st

from .service import ROOT, data_root
from .site_data import parse_json


def _json(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)


def _input(label, key):
    uploaded = st.file_uploader(label + " file", type=["json"], key=key + "_file")
    with st.expander("Or paste " + label.lower()):
        pasted = st.text_area(label + " JSON", key=key, height=160)
    if uploaded is not None:
        st.caption("The uploaded file takes precedence over pasted text.")
        return uploaded.getvalue()
    return pasted.encode("utf-8") if pasted.strip() else None


def _issues(report):
    if report.get("errors"):
        st.dataframe(report["errors"], hide_index=True, width="stretch")
    if report.get("warnings"):
        with st.expander("Review notes"):
            st.json(report["warnings"])


def _fingerprint(*inputs):
    digest = hashlib.sha256()
    for item in inputs:
        value = item if isinstance(item, bytes) else str(item).encode("utf-8")
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _guides():
    with st.expander("Model and study instructions"):
        for name in ("BENCH_MODEL.md", "BENCH_STUDY.md"):
            path = ROOT / name
            if path.is_file():
                st.download_button("Download " + name.replace("_", " ").removesuffix(".md").lower(),
                                   path.read_bytes(), file_name=name, key="bench_guide_" + name)
        st.write("Prepare a site survey, a model specification and an event forcing file. Every internal compartment needs a measured stage–area curve and a declared spill collector. The initial state must be dry and empty; wet or equilibrated starts are not yet supported.")


def _manifest_hash(result):
    path = Path(result["files"]["manifest.json"]).resolve()
    if not path.is_relative_to((data_root() / "bench_runs").resolve()):
        raise ValueError("The run manifest is outside this research workspace.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_bundle(result, manifest_sha256):
    """Verify the complete retained pair before returning any exported bytes."""
    from .bench_model import verify_bench_result

    if _manifest_hash(result) != manifest_sha256:
        raise ValueError("The saved bench manifest changed after the run.")
    manifest_data = Path(result["files"]["manifest.json"]).read_bytes()
    if hashlib.sha256(manifest_data).hexdigest() != manifest_sha256:
        raise ValueError("The bench manifest changed during evidence verification.")
    expected = {**parse_json(manifest_data)["file_sha256"], "manifest.json": manifest_sha256}
    verification = verify_bench_result(result)
    if not verification.get("valid"):
        raise ValueError("Bench evidence verification failed: " + _json(verification.get("errors", [])))
    base = (data_root() / "bench_runs").resolve()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in result.get("files", {}).items():
            path = Path(value).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise ValueError("The complete bench evidence is missing or outside this workspace.")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected.get(name):
                raise ValueError("Bench artifact changed during export: " + name)
            archive.writestr(name, content)
    return buffer.getvalue()


def _model_run():
    from .bench_model import run_bench_model, validate_bench_run

    st.subheader("Run a separate bench model")
    mode = st.radio("Input source", ["Supplied files", "Synthetic example"], horizontal=True, key="bench_input_source")
    if mode == "Synthetic example":
        st.info("Invented geometry and boundary conditions for a software exercise. No apparatus or measurements are represented.")
        blobs = []
        for kind in ("site", "model", "run"):
            path = ROOT / f"data/templates/synthetic_bench_{kind}_v1.json"
            blob = path.read_bytes()
            blobs.append(blob)
            st.download_button("Download example " + kind, blob, file_name=path.name, key="bench_example_" + kind)
    else:
        blobs = [_input(label, "bench_" + key + "_json") for label, key in
                 (("Site package", "site"), ("Model specification", "model"), ("Event forcing", "run"))]
    ready = all(blobs)
    signature = _fingerprint(mode, *blobs)
    left, right = st.columns(2)
    with left:
        if st.button("Check model inputs", disabled=not ready, key="bench_check"):
            st.session_state["bench_contract_check"] = {"signature": signature, "report": validate_bench_run(*blobs)}
    with right:
        if st.button("Run bench simulation", disabled=not ready, type="primary", key="bench_run"):
            st.session_state.pop("bench_run_result", None)
            try:
                with st.spinner("Running the isolated bench model and numerical checks…"):
                    result = run_bench_model(*blobs, data_root() / "bench_runs")
                st.session_state["bench_run_result"] = {"signature": signature, "report": result,
                                                         "manifest_sha256": _manifest_hash(result) if "manifest.json" in result.get("files", {}) else None}
            except Exception as exc:
                st.error(str(exc))
    if not ready:
        st.caption("Supply all three files to check or run your model. Nothing has been imported into the reference catchment.")
    checked = st.session_state.get("bench_contract_check")
    if checked and checked["signature"] == signature:
        report = checked["report"]
        if report["valid"]:
            st.success("Input structure is supported. Numerical and physical checks are separate.")
        else:
            st.error("Input structure is not supported; review the listed issues.")
        _issues(report)
    saved = st.session_state.get("bench_run_result")
    if not saved:
        return
    if saved["signature"] != signature:
        st.warning("The model inputs changed. Run again to see a result for the current files.")
        return
    result = saved["report"]
    bundle = None
    if result.get("files") and saved["manifest_sha256"] is not None:
        try:
            bundle = _run_bundle(result, saved["manifest_sha256"])
        except Exception as exc:
            st.error(str(exc))
            st.warning("This cached run cannot be presented as current verified evidence. Run again after resolving the source or artifact change.")
            return
    elif result.get("valid"):
        st.error("A successful bench result is missing its complete evidence manifest. Run again after resolving the missing artifacts.")
        return
    elif result.get("files"):
        st.warning("The failed attempt retained partial files locally. A complete verified evidence download is unavailable; inspect the failure details below.")
    if result.get("valid"):
        st.success("The bench simulation passed its numerical checks. This is a model result; physical validation remains pending.")
    else:
        st.warning("This bench simulation is unresolved or failed. Its result cannot support validation acceptance.")
    _issues(result)
    _run_view(result)
    st.download_button("Download bench result", _json(result), file_name="bench-result.json", key="bench_result_download")
    if bundle is not None:
        st.download_button("Download complete run evidence", bundle, file_name="Monsoon_Bench_Run.zip", key="bench_run_bundle")


def _run_view(result):
    import plotly.graph_objects as go

    diagnostics = result.get("diagnostics", {})
    columns = st.columns(2)
    for index, (label, field) in enumerate(zip(
            ("Applied inflow", "Receiving backflow", "Final stored water", "Balance residual"),
            ("external_inflow_m3", "receiving_backflow_m3", "final_storage_m3", "mass_balance_residual_m3"))):
        value = diagnostics.get(field)
        columns[index % 2].metric(label, "—" if value is None else f"{1000 * value:.4f} L")
    st.caption("Stored water includes every compartment and connecting channel. Signed outlet exchange includes reverse flow from the receiving boundary.")
    samples = result.get("timeseries", [])
    if samples:
        chart = go.Figure()
        prescribed = result.get("column_roles", {}).get("boundary_response_not_validation_target", {}).get("stage_m", [])
        for node in samples[0].get("stage_m", {}):
            chart.add_trace(go.Scatter(x=[row["elapsed_s"] for row in samples],
                                      y=[row["receiving_stage_m" if node in prescribed else "stage_m"][node] for row in samples],
                                      name=node + (" · prescribed boundary" if node in prescribed else " · model response"),
                                      mode="lines", line={"dash": "dash" if node in prescribed else "solid"}))
        chart.update_layout(height=330, xaxis_title="Elapsed time (s)", yaxis_title="Water level (m, supplied datum)",
                            margin={"l": 8, "r": 8, "t": 15, "b": 10}, legend={"orientation": "h", "y": -0.23})
        st.plotly_chart(chart, width="stretch")
        st.caption("The receiving water level is prescribed input, not an independent validation response.")
    with st.expander("Numerical checks", expanded=True):
        if result.get("step_halving"):
            st.write("**Repeat at half the time step:**", result["step_halving"]["status"].replace("_", " "))
            st.caption("Both runs must pass conservation and convergence checks and agree within the declared numerical tolerances. This checks the calculation, not the physical apparatus.")
            st.json(result["step_halving"], expanded=False)
        st.json(diagnostics, expanded=False)
    with st.expander("Complete model result"):
        st.json(result, expanded=False)


def render_bench_model():
    st.write("Turn surveyed bench geometry into a reproducible model, then keep calibration separate from later response checks.")
    st.caption("Local research records only. This workspace cannot approve maintenance or certify physical validation. The original synthetic catchment and its adverse findings are preserved.")
    st.warning("This version supports dry, empty starts and fixed geometry. Wet or equilibrated starts—and therefore the complete 24-run physical protocol—remain unsupported.")
    _guides()
    activity = st.radio("Bench activity", ["Model run", "Calibration & freeze", "Software exercise"], horizontal=True, key="bench_activity")
    if activity == "Model run":
        _model_run()
    elif activity == "Calibration & freeze":
        _studies()
    else:
        _exercise()


def _exercise():
    from .bench_demo import run_exercise
    from .bench_study import BenchStudyStore

    st.subheader("Practice the complete record sequence")
    st.info("Synthetic software exercise only. The response values come from the same solver plus known offsets; they cannot independently validate the hydraulics.")
    st.write("This exercise records a calibration response, freezes the model and a different future pulse, then records the withheld response. It checks that the reported errors match the deliberately introduced 1 mm and 10 mm offsets. It creates a separate practice ledger.")
    if st.button("Run synthetic study exercise", type="primary", key="bench_exercise_run"):
        st.session_state.pop("bench_exercise_result", None)
        try:
            with st.spinner("Running the calibration, freeze and withheld-response software exercise…"):
                st.session_state["bench_exercise_result"] = run_exercise(data_root() / "bench_exercises")
        except Exception as exc:
            st.error(str(exc))
    result = st.session_state.get("bench_exercise_result")
    if result:
        try:
            folder = Path(result["folder"]).resolve()
            if not folder.is_relative_to((data_root() / "bench_exercises").resolve()) or not (folder / "exercise.sqlite3").is_file():
                raise ValueError("The synthetic exercise record is missing or outside this workspace.")
            with BenchStudyStore(folder / "exercise.sqlite3") as store:
                check = store.verify(result["study_id"])
            if not check.get("valid") or check.get("head_sha256") != result["integrity_check"].get("head_sha256"):
                raise ValueError("The stored exercise or current runtime no longer matches the completed exercise.")
        except Exception as exc:
            st.error(str(exc))
            return
        if result["status"] == "passed":
            st.success("The software record sequence and known-error arithmetic passed. Physical validation remains pending.")
        else:
            st.error("The software exercise did not pass. Inspect the retained result.")
        st.dataframe([{"Partition": label, "Response": series["series_id"], "RMSE (m)": series["rmse"],
                       "Bias (m)": series["bias"], "Maximum error (m)": series["maximum_absolute_error"]}
                      for field, label in (("calibration_comparison", "Calibration"), ("withheld_comparison", "Withheld"))
                      for series in result[field]["series"]], hide_index=True, width="stretch")
        st.json(result, expanded=False)
        st.download_button("Download software exercise result", _json(result), file_name="synthetic-bench-exercise.json", key="bench_exercise_download")


def _studies():
    from .bench_study import BenchStudyStore

    st.subheader("Keep calibration and later responses separate")
    st.write("Record calibration responses against a candidate model. Freeze one candidate and its future event plan before adding the withheld responses. Errors are reported for review; they do not automatically certify model accuracy.")
    st.caption("This is a local research ledger without operational account roles. Receipt timestamps and file hashes support reproducibility; they do not prove who performed an experiment or that the supplied measurements are authentic.")
    st.caption("Response errors use the declared inflow and receiving-water conditions. This version does not compare measured boundary traces with that prescription; boundary mismatch can therefore contribute to the reported errors.")
    try:
        store = BenchStudyStore(data_root() / "bench_studies.sqlite3")
    except Exception as exc:
        st.error(str(exc))
        return
    try:
        _study_controls(store)
    except Exception as exc:
        st.error(str(exc))
    finally:
        store.close()


def _attachments(key):
    files = st.file_uploader("Raw source attachments (optional for synthetic records)",
                             accept_multiple_files=True, key=key)
    result = {}
    for item in files or []:
        if item.name.casefold() in {name.casefold() for name in result}:
            raise ValueError("Raw attachment names must be unique, ignoring case.")
        result[item.name] = item.getvalue()
    return result


def _study_controls(store):
    with st.expander("Create a research study"):
        title = st.text_input("Study title", key="bench_study_title")
        site = _input("Study site package", "bench_study_site")
        if st.button("Create bench study", disabled=not (site and title.strip()), key="bench_create_study"):
            created = store.create_study(site, title=title)
            st.session_state["bench_selected_study"] = created["study_id"]
            st.rerun()
    entries = store.list_studies()
    if not entries:
        st.info("No bench studies have been recorded here. Actual observation forms start blank.")
        return
    labels = {entry["study_id"]: f'{entry["title"]} · {entry["evidence_kind"]} · {entry["study_id"][-8:]}' for entry in entries}
    study_id = st.selectbox("Research study", list(labels), format_func=labels.get, key="bench_selected_study")
    state = store.get(study_id)
    if state["evidence_kind"] == "synthetic_fixture":
        st.info("Synthetic software exercise. These records do not represent measurements from a physical rig.")
    else:
        st.info("Supplied bench observations are unverified research records. No physical validation or professional approval is established.")
    columns = st.columns(3)
    columns[0].metric("Calibration records", len(state["calibrations"]))
    columns[1].metric("Withheld response records", len(state["validations"]))
    columns[2].metric("Pending withheld events", len(state["pending_validation_event_ids"]))
    st.caption(f'Record version {state["version"]} · {state["status"].replace("_", " ")}')
    if state["freeze"] is None:
        _calibration_controls(store, state)
        _freeze_controls(store, state)
    else:
        st.write("**Model and event plan frozen:**", state["freeze"]["frozen_at"])
        st.caption("To revise the model after seeing these responses, start a new development study and use new withheld events. Do not relabel these disclosed responses as unseen evidence.")
        _validation_controls(store, state)
    rows, records = [], []
    for partition in ("calibrations", "validations"):
        for record in state[partition]:
            records.append({"Partition": "Calibration" if partition == "calibrations" else "Withheld",
                            "Event": record["event"]["event_id"], "Model run": record["prediction"]["status"],
                            "Response check": record["comparison"]["status"].replace("_", " "),
                            "Reason": "; ".join(record["comparison"].get("errors", []))})
            for series in record["comparison"].get("series", []):
                rows.append({"Partition": "Calibration" if partition == "calibrations" else "Withheld",
                             "Event": record["event"]["event_id"], "Response": series["series_id"],
                             "Unit": series["unit"], "Status": series["status"],
                             "RMSE": series.get("rmse"), "Bias": series.get("bias"),
                             "Maximum error": series.get("maximum_absolute_error"), "Missing": series["missing_count"]})
    if records:
        st.subheader("Retained event records")
        if any(row["Response check"] == "unresolved" for row in records):
            st.warning("One or more retained response checks remain unresolved. Their reasons are listed below; a saved record is not a successful validation.")
        st.dataframe(records, hide_index=True, width="stretch")
    if rows:
        st.subheader("Response errors")
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption("Calculated error is not an acceptance decision. A missing response or unresolved model run remains unresolved.")
    with st.expander("Study integrity and full record"):
        check = store.verify(study_id)
        if check.get("valid"):
            st.success("Local study integrity checks passed.")
        else:
            st.error("Local study integrity checks failed. Review the reported issues.")
        st.json(check, expanded=False)
        st.json(state, expanded=False)
        st.download_button("Download study record", _json({"integrity_check": check, "study": state}),
                           file_name="bench-study-record.json", key="bench_study_download")


def _calibration_controls(store, state):
    with st.expander("Add a calibration response"):
        model = _input("Calibration model specification", "bench_cal_model")
        event = _input("Calibration event", "bench_cal_event")
        observations = _input("Calibration observations", "bench_cal_observations")
        raw = _attachments("bench_cal_raw")
        if st.button("Record calibration response", disabled=not all((model, event, observations)), key="bench_record_cal"):
            with st.spinner("Reproducing the model and retaining the calibration record…"):
                store.record_calibration(state["study_id"], state["version"], model_spec=model,
                                         event=event, observations=observations, raw_files=raw)
            st.rerun()


def _freeze_controls(store, state):
    with st.expander("Freeze the model and future event plan"):
        candidates = {r["model_sha256"]: r for r in state["calibrations"]
                      if r["prediction"].get("valid") and r["comparison"]["status"] == "resolved_errors"}
        if not candidates:
            st.caption("First retain a complete calibration response and a numerically resolved model run.")
            return
        selected = st.selectbox("Calibration-used model", list(candidates),
                                format_func=lambda value: candidates[value]["model_spec"]["model_id"] + " · " + value[:12], key="bench_freeze_model")
        st.caption('The plan file must be an object with one "events" list. Each event fixes its forcing, response series and future collection window. Synthetic exercise windows must be null.')
        plan = _input("Withheld event plan", "bench_freeze_plan")
        rationale = st.text_area("Why this model and these withheld events?", key="bench_freeze_rationale")
        if st.button("Freeze model and event plan", disabled=not (plan and rationale.strip()), key="bench_freeze"):
            parsed = parse_json(plan)
            if set(parsed) != {"events"}:
                raise ValueError('The plan file requires exactly one "events" list.')
            store.freeze_study(state["study_id"], state["version"], selected_model_sha256=selected,
                               validation_plan=parsed["events"], rationale=rationale)
            st.rerun()


def _validation_controls(store, state):
    pending = state["pending_validation_event_ids"]
    if not pending:
        st.info("Every event in this limited study has a retained response record. This does not complete the 24-run physical protocol or establish physical validation.")
        return
    with st.expander("Add a withheld response", expanded=True):
        event_id = st.selectbox("Frozen event", pending, key="bench_validation_event")
        observations = _input("Withheld observations", "bench_validation_observations")
        raw = _attachments("bench_validation_raw")
        if st.button("Record withheld response", disabled=not observations, key="bench_record_validation"):
            with st.spinner("Reproducing the frozen model and comparing the supplied response…"):
                store.record_validation(state["study_id"], state["version"], event_id=event_id,
                                        observations=observations, raw_files=raw)
            st.rerun()
