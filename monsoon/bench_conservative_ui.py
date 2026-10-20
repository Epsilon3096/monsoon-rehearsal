"""Explicit separate-engine research interface with sealed evidence exports."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import zipfile

import plotly.graph_objects as go
import streamlit as st
from .service import ROOT, data_root
from .site_data import canonical_json, parse_json
from .bench_next_ui import _input, _signature


def synthetic_inputs(kind):
    values = [parse_json((ROOT / "data/templates" / f"synthetic_bench_{name}_v1.json").read_bytes())
              for name in ("site","model","run")]
    if kind == "Receiving-stage reversal":
        values[2]["inflows"][0]["points"] = [{"elapsed_s":0,"value_m3_s":0},{"elapsed_s":120,"value_m3_s":0}]
        values[2]["receiving_stages"][0]["points"] = [{"elapsed_s":t,"stage_m":h} for t,h in ((0,0),(20,.06),(50,.06),(90,0),(120,0))]
    return values


def evidence_bundle(result, manifest_hash, directory):
    from .bench_conservative import verify_conservative_result
    folder = Path(result["artifact_directory"]).resolve()
    if not folder.is_relative_to(Path(directory).resolve()):
        raise ValueError("Evidence folder is outside this research workspace.")
    manifest = (folder/"manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != manifest_hash:
        raise ValueError("Evidence manifest changed after the run.")
    check = verify_conservative_result(result)
    if not check["valid"]:
        raise ValueError("Evidence cannot be used: " + canonical_json(check["errors"]))
    hashes = {**parse_json(manifest)["file_sha256"],"manifest.json":manifest_hash}
    output=io.BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for name,expected in hashes.items():
            path=(folder/name).resolve()
            if not path.is_relative_to(folder):
                raise ValueError("Evidence path escapes the research folder.")
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("Evidence changed during export.")
            archive.writestr(name,raw)
    return output.getvalue()


def _show_result(result):
    if result["valid"]:
        st.success("This run passed the fixed water-accounting, time-step and mesh checks.")
    else:
        st.warning("This run is numerically unresolved. All available attempts and failed checks are retained.")
    st.caption("Numerical qualification only. These results do not establish physical accuracy, operator acceptance or a scheduling advantage.")
    rows=[]
    for label,attempt in result.get("attempts",{}).items():
        audit=attempt.get("transfer_audit",{})
        residual=audit.get("maximum_absolute_residual_m3")
        rows.append({"Run":label,"Qualified":attempt.get("valid",False),"Water check":audit.get("valid",False),
                     "Routing endpoints":audit.get("endpoint_count"),"Largest imbalance (mL)":None if residual is None else residual*1e6})
    if rows:
        st.dataframe(rows,hide_index=True,width="stretch")
    ts=result.get("timeseries",[])
    if ts:
        figure=go.Figure()
        for nid in ts[0]["stage_m"]:
            figure.add_trace(go.Scatter(x=[x["elapsed_s"] for x in ts],y=[x["stage_m"][nid] for x in ts],name=nid,mode="lines"))
        figure.update_layout(xaxis_title="Elapsed time (s)",yaxis_title="Water surface elevation (m)",height=350,margin=dict(l=20,r=20,t=20,b=20))
        st.plotly_chart(figure,width="stretch")
    with st.expander("Time and mesh checks, phase budgets and retained issues"):
        st.json({"convergence":result.get("convergence"),"attempts":result.get("attempts"),"errors":result.get("errors")},expanded=False)


def render_conservative_bench():
    from .bench_conservative import run_conservative_bench, validate_conservative_run
    st.subheader("Track every water transfer")
    st.write("A separate conservative bench engine for rectangular open channels. Each channel and compartment shares the same recorded transfer at their connection.")
    st.info("The earlier SWMM failures remain part of the evidence. This workspace uses a different numerical method; it does not mark those runs as corrected.")
    summary=ROOT/"evidence/v0.7/release-summary.json"
    if summary.is_file():
        with st.expander("Latest verified development results"):
            st.json(parse_json(summary.read_bytes()),expanded=False)
        st.download_button("Download verification summary",summary.read_bytes(),file_name="conservative-bench-verification.json",key="fv_summary_download")
    mode=st.radio("Conservative input source",["Supplied files","Synthetic example"],horizontal=True,key="fv_source")
    if mode == "Synthetic example":
        kind=st.selectbox("Synthetic event",["Seven-litre pulse","Receiving-stage reversal"],key="fv_example")
        values=[canonical_json(v) for v in synthetic_inputs(kind)]
        st.warning("Invented geometry and forcing for software verification. No physical measurements or operator validation are implied.")
    else:
        values=[_input(label,"fv_input_"+name) for label,name in (("Site package","site"),("Model specification","model"),("Run boundaries","run"))]
    split_text=st.text_input("Phase boundaries in seconds (comma separated; blank for the whole run)",value="50",key="fv_phases")
    try:
        splits=tuple(float(x.strip()) for x in split_text.split(",") if x.strip())
        phase_error=None
    except ValueError:
        splits=()
        phase_error="Phase boundaries must be numeric seconds."
        st.error(phase_error)
    signature=_signature(mode,*values,split_text)
    available=all(values) and phase_error is None
    st.caption("Fixed verification: 128 cells, a smaller time step and a separate 256-cell run. Every routing endpoint uses the original 1 mL or 1% water limit. Time and mesh agreement use the unchanged 2% and absolute limits.")
    if st.button("Check conservative model",disabled=not available,key="fv_check"):
        st.session_state["fv_contract"]={"signature":signature,"report":validate_conservative_run(*values,split_times=splits)}
    saved_check=st.session_state.get("fv_contract")
    if saved_check and saved_check["signature"] == signature:
        if saved_check["report"]["valid"]:
            st.success("The supplied contract is within the conservative engine's declared scope.")
        else:
            st.error("The supplied contract cannot be run.")
            st.json(saved_check["report"]["errors"],expanded=True)
    if st.button("Run fixed three-part verification",disabled=not available,key="fv_run"):
        st.session_state.pop("fv_result",None)
        try:
            with st.spinner("Checking the primary run, smaller time step and finer mesh; retaining every routing endpoint…"):
                result=run_conservative_bench(*values,data_root()/"conservative_bench_runs",split_times=splits)
            folder=result.get("artifact_directory")
            seal=hashlib.sha256((Path(folder)/"manifest.json").read_bytes()).hexdigest() if folder else None
            st.session_state["fv_result"]={"signature":signature,"report":result,"manifest_sha256":seal}
        except Exception as exc:
            st.error("The attempt could not finish: "+str(exc))
    saved=st.session_state.get("fv_result")
    if saved:
        if saved["signature"] != signature:
            st.warning("Inputs changed. The earlier result cannot qualify these inputs; run verification again.")
        elif saved["report"].get("artifact_directory"):
            try:
                bundle=evidence_bundle(saved["report"],saved["manifest_sha256"],data_root()/"conservative_bench_runs")
                _show_result(saved["report"])
                st.download_button("Download complete conservative evidence",bundle,file_name="monsoon-conservative-bench-evidence.zip",key="fv_evidence_download")
            except Exception as exc:
                st.error("Evidence cannot be used: "+str(exc))
        else:
            st.error("The supplied contract could not be executed.")
            st.json(saved["report"].get("errors",[]))
    guide=ROOT/"CONSERVATIVE_BENCH.md"
    if guide.is_file():
        with st.expander("Method, scope and verification guide"):
            st.markdown(guide.read_text(encoding="utf-8"))
        st.download_button("Download conservative bench guide",guide.read_bytes(),file_name=guide.name,key="fv_guide_download")
