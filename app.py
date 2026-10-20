"""Local research application. Run with: streamlit run app.py."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from monsoon.charts import network_figure, timeline_figure, node_spill_rows
from monsoon.presentation import decision_verdict, audit_case_options, audit_location_rows
from monsoon.audit_view import bound_trace, spill_values
from monsoon import __version__
from monsoon.assurance import validate_audit
from monsoon.briefing import render_briefing
from monsoon.service import (ROOT, canonical_hash, context, data_root, find_run,
                             initialise, plan_snapshot, rehearse, audit_selected_plan)

st.set_page_config(page_title="Monsoon Rehearsal", page_icon="🌧️", layout="wide")
st.markdown("""<style>
.block-container {padding-top:3rem;padding-bottom:3rem;max-width:1280px;}
[data-testid="stSidebar"] {background:#edf3f5;border-right:1px solid #dce5ea;}
h1 {letter-spacing:-.035em;} h2,h3 {letter-spacing:-.02em;}
[data-testid="stExpander"] {background:#fff;border:1px solid #dce5ea;border-radius:12px;}
@media(max-width:640px){.block-container{padding-top:2rem;} .mr-hero{padding:22px!important;} .mr-hero h1{font-size:1.8rem!important;}}
.mr-kicker {font-size:.73rem;letter-spacing:.17em;font-weight:700;color:#00867d;margin-bottom:8px;}
.mr-hero {background:linear-gradient(110deg,#153343,#215563);padding:28px 32px;border-radius:17px;color:white;margin-bottom:22px;}
.mr-hero h1 {font-size:2.35rem;letter-spacing:-.04em;color:white;padding:0 0 10px;margin:0;}
.mr-hero p {margin:0;color:#cfdee3;font-size:1rem;max-width:770px;}
.mr-badge {display:inline-block;background:#dceeea;color:#12675e;padding:5px 10px;border-radius:20px;font-size:.73rem;font-weight:700;margin-bottom:14px;}
[data-testid="stMetric"] {background:white;border:1px solid #dce5ea;border-radius:12px;padding:14px 18px;}
.stButton>button {border-radius:9px;}
</style>""", unsafe_allow_html=True)


def action(label, call, *, key=None, disabled=False, primary=False):
    if st.button(label, key=key, disabled=disabled, type="primary" if primary else "secondary"):
        try:
            result = call()
            st.session_state["notice"] = f"{label} completed."
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def show_assurance(audit, gate=None):
    """Read the exact audit, independently of the planning-scenario selector."""
    st.subheader("Plan-specific stress audit")
    st.caption("Checks of this queue and its completed work states under the declared scenarios. Passing these model checks does not certify field safety.")
    if not audit:
        st.info("This plan has no stress audit. It can be saved as a blocked draft; review, approval and dispatch require complete passing evidence.")
        return
    if not gate or not gate.get("valid"):
        st.warning("Audit evidence is unavailable, changed or unverified. Details below are historical diagnostic records; approval remains blocked.")
    for reason in (gate or {}).get("reasons", []):
        st.write(f"• {reason}")
    cases = audit_case_options(audit)
    if cases:
        options = {str(i): row for i, row in enumerate(cases)}
        selected = st.selectbox("Inspect audited case / prefix", list(options),
            format_func=lambda key: f'{options[key].get("scenario_id", "Unknown")} · {options[key].get("status", "unresolved")}',
            key="audit_case_" + str(audit.get("audit_sha256", "unbound"))[:16])
        row = options[selected]
        st.write(row.get("title", row.get("scenario_id", "Audit case")))
        for reason in row.get("reasons", []):
            st.caption(reason)
        locations = audit_location_rows(audit, row.get("scenario_id"))
        if locations:
            st.caption("Recorded location-level violations across this case. Each card identifies its own achieved work state.")
            for location in locations:
                with st.container(border=True):
                    completed_label = location.get("Completed jobs")
                    st.write(f'**{location.get("Location", "Unknown location")}** · completed: {"unavailable" if completed_label is None else completed_label or "none"}')
                    st.caption(f'{location.get("Stage") or "state"} {location.get("Prefix") if location.get("Prefix") is not None else ""} · {location.get("State status") or "unresolved"}')
                    def fmt(value, signed=False):
                        if value is None: return "unavailable"
                        return f"{value:+.4f}" if signed else f"{value:.4f}"
                    st.write(f'Baseline **{fmt(location.get("Baseline spill (m³)"))} m³** → result **{fmt(location.get("Resulting spill (m³)"))} m³**')
                    st.caption(f'Change {fmt(location.get("Change (m³)"), True)} m³ · allowed increase {fmt(location.get("Limit (m³)"))} m³')
        else:
            st.caption("No location-level violation is recorded for this case. Check its state and numerical findings before interpreting that absence.")
        states = row.get("states", [])
        if states:
            first_adverse = next((i for i, state in enumerate(states) if state.get("status") == "failed"),
                                 next((i for i, state in enumerate(states) if state.get("status") == "unresolved"), 0))
            state_index = st.selectbox("Achieved work state", list(range(len(states))),
                format_func=lambda i: f'{states[i].get("stage", "state")} {states[i].get("prefix_index", "")} · {", ".join(states[i].get("completed_jobs", [])) or "none"} · {states[i].get("status", "unresolved")}',
                index=first_adverse,
                key="audit_state_" + str(audit.get("audit_sha256", "unbound"))[:16] + "_" + str(row.get("scenario_id")))
            state = states[state_index]
            st.caption(f'Result run: {state.get("run_id") or "unavailable"} · reference run: {state.get("reference_run_id") or "unavailable"}')
            with st.expander("Node comparisons for this exact state"):
                st.dataframe(state.get("node_comparisons", []), hide_index=True, width="stretch")
            if st.checkbox("Show bound depth traces", key="audit_trace_" + str(audit.get("audit_sha256", "unbound"))[:16]):
                for label, run_id in [("Selected work state", state.get("run_id")), ("No additional work reference", state.get("reference_run_id"))]:
                    run = bound_trace(audit, run_id) if gate and gate.get("valid") else None
                    if run and run.get("timeseries"):
                        frame = pd.DataFrame(run["timeseries"])
                        columns = [c for c in frame if c.startswith("depth_")]
                        if "minutes" in frame and columns:
                            st.plotly_chart(px.line(frame, x="minutes", y=columns, title=label,
                                labels={"value":"Depth (m)", "minutes":"Event time (min)", "variable":"Location"}), width="stretch")
                            continue
                    st.info(f'{label}: compact audit metrics remain available; an intact, checksum-bound time series for run {str(run_id or "unavailable")[:12]} is not available locally.')
    with st.expander("All cases, numerical checks and evidence identity"):
        st.dataframe([{"Case": r.get("scenario_id"), "Status": r.get("status"), "Details": "; ".join(r.get("reasons", []))} for r in audit.get("cases", [])], hide_index=True, width="stretch")
        st.json(audit, expanded=False)


def render_verdict(plan, audit, gate, *, stale=False, condition_unknown=False):
    verdict = decision_verdict(plan, audit, gate, stale=stale, condition_unknown=condition_unknown)
    getattr(st, verdict["level"])(f'**{verdict["title"]}**\n\n{verdict["explanation"]}')
    if plan:
        st.write("**Selected queue:**", " → ".join(plan.get("queue", [])) or "No additional discretionary work")
    return verdict


def choose_plan(identifier):
    st.session_state["inspect_plan_id"] = identifier


def open_workspace(name):
    st.session_state["workspace"] = name


def render_comparison(case, episode, chosen):
    recommendation = episode.get("recommended")
    if recommendation is None:
        st.warning("No supported recommendation. Inspect the rejected or unresolved alternatives below.")
    else:
        st.caption("Original planning-search result for the selected planning scenarios. The selected queue and its stress-audit verdict above govern review; this comparison summary does not replace them.")
        cols=st.columns(3)
        cols[0].metric("Jobs in priority queue",len(recommendation["queue"]))
        cols[1].metric("Worst scenario spill", f'{recommendation["worst_spill_m3"]:,.2f} m³')
        cols[2].metric("Crew time, worst scenario", f'{recommendation["worst_crew_minutes"]:g} min')
        st.write("**Priority queue:**", " → ".join(recommendation["queue"]) or "No additional work")
        st.caption("The crew scans this priority queue for the next eligible job that fits. The completed subset can differ by duration scenario. The per-location screen applies to the selected finite scenarios; it is not a field safety certification.")

    rows=episode.get("comparisons",[])
    if rows:
        frame=pd.DataFrame(rows)
        labels=episode.get("baseline_definitions",{})
        if isinstance(labels,dict):
            frame["Method"]=frame["method"].map(lambda x: labels.get(x,{}).get("label",x) if isinstance(labels.get(x),dict) else labels.get(x,x))
        else:
            frame["Method"]=frame["method"].str.replace("_"," ").str.title()
        plot_frame=frame.dropna(subset=["total_spill_m3"])
        unsupported=frame[frame["status"]!="supported"]
        if not unsupported.empty:
            st.warning(f"{len(unsupported)} baseline/scenario outcomes are inadmissible or unresolved. Hatched bars fail the location-level screen; lower total spill does not make them acceptable.")
        if not plot_frame.empty:
            fig=px.bar(plot_frame,x="scenario_id",y="total_spill_m3",color="Method",barmode="group",
                       pattern_shape="status",pattern_shape_map={"supported":"","inadmissible":"/","unresolved":"x"},
                       hover_data=["status","completed_jobs"],
                       labels={"scenario_id":"Planning scenario","total_spill_m3":"Drainage spill (m³)"},
                       color_discrete_sequence=["#008f86","#173142","#d89026","#768c9b","#a4b6bb","#777ab0"])
            fig.update_layout(height=350,margin=dict(l=10,r=10,t=15,b=10),legend=dict(orientation="h",y=-.2),
                              paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig,width="stretch")
        columns=[c for c in ["Method","scenario_id","total_spill_m3","status","completed_jobs","crew_minutes"] if c in frame]
        with st.expander("All baseline results and definitions"):
            st.dataframe(frame[columns],hide_index=True,width="stretch")
            st.json(labels,expanded=False)

    if chosen:
        scenario_results=chosen.get("scenario_results",[])
        if isinstance(scenario_results,dict): scenario_results=list(scenario_results.values())
        if scenario_results:
            st.dataframe([{"Scenario": r["scenario_id"],
                           "Completed before deadline": ", ".join(r.get("replay", {}).get("completed_jobs", [])) or "None",
                           "Crew minutes": r.get("crew_minutes"), "Outcome": r.get("status")}
                          for r in scenario_results], hide_index=True, width="stretch")
            scenario_options={r["scenario_id"]:r for r in scenario_results}
            scenario_id=st.selectbox("Inspect scenario",list(scenario_options),key="inspect_scenario_id")
            sr=scenario_options[scenario_id]
            with st.expander("Scenario schematic and accessible node summary", expanded=True):
                mode_label = st.radio("Node measure", ["Absolute spill", "Change vs no additional work"], horizontal=True, key="node_measure")
                change = mode_label == "Change vs no additional work"
                no_work = next((p for p in episode.get("plans", []) if p.get("queue") == []), {})
                reference_results = no_work.get("scenario_results", [])
                if isinstance(reference_results, dict): reference_results = list(reference_results.values())
                reference = next((r for r in reference_results if r.get("scenario_id") == scenario_id), None)
                values = spill_values(sr, reference, change=change)
                mode = "change" if change else "absolute"
                completed = sr.get("completed_jobs", [])
                st.caption(f'Modelled scenario {scenario_id} · achieved jobs: {", ".join(completed) or "none"}. This hypothetical state is separate from verified work.')
                epsilon = case.get("epsilon_m3", .05)
                st.plotly_chart(network_figure(case, completed, values, display_mode=mode, epsilon_m3=epsilon), width="stretch")
                st.dataframe([{"Location": r["node_id"], "Measure": r["value_label"], "Finding": r["status_label"]} for r in node_spill_rows(case, values, mode, epsilon_m3=epsilon)], hide_index=True, width="stretch")
                if change and reference is None: st.warning("Matching no-additional-work reference is unavailable; changes are unknown.")
            replay=sr.get("replay",{})
            if replay.get("skipped"):
                with st.expander("Why queued jobs do not finish in this scenario"):
                    st.dataframe([{"Job":r["job_id"],"Reason":r["reason"].replace("_"," ")} for r in replay["skipped"]],hide_index=True,width="stretch")
            if replay.get("events"):
                st.plotly_chart(timeline_figure(replay["events"],episode["inputs"]["deadline_minutes"]),width="stretch")
                st.caption("Bars include all on-site occupation. Gaps represent travel; the feasibility gate also reserves final return time.")
            node_rows=[{"Location":k,**v} for k,v in sr.get("nodes",{}).items()]
            if node_rows: st.dataframe(node_rows,hide_index=True,width="stretch")
            run=find_run(sr.get("run_id",""))
            if run:
                left,right=st.columns([2,1])
                with left:
                    ts=pd.DataFrame(run.get("timeseries",[]))
                    depth_cols=[c for c in ts if c.startswith("depth_")]
                    if depth_cols and "minutes" in ts:
                        fig=px.line(ts,x="minutes",y=depth_cols,labels={"value":"Water depth (m)","minutes":"Event time (min)","variable":"Location"})
                        fig.update_layout(height=290,margin=dict(l=5,r=5,t=10,b=5),paper_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig,width="stretch")
                with right:
                    st.caption("Engine diagnostics")
                    diagnostic=run.get("diagnostics",{})
                    st.metric("Water balance error",f'{diagnostic.get("continuity_error_percent",0):.4f}%')
                    st.caption(f'Event horizon: {diagnostic.get("horizon_minutes", "—")} min · routing step: {diagnostic.get("routing_step_s", "—")} s')
                    with st.expander("Detailed engine diagnostics"):
                        st.json(diagnostic,expanded=False)
                for label,field in [("SWMM input","input"),("SWMM report","report")]:
                    p=Path(run.get("files",{}).get(field,""))
                    if p.is_file(): st.download_button(f"Download {label}",p.read_bytes(),file_name=p.name,key=f"download_{field}")
    with st.expander("Rejected and unresolved alternatives"):
        rejected=[{"Queue":" → ".join(p["queue"]) or "None","Status":p.get("status"),"Reasons":"; ".join(p.get("reasons",[]))}
                  for p in episode.get("plans",[]) if not p.get("admissible")]
        st.dataframe(rejected,hide_index=True,width="stretch") if rejected else st.write("No rejected alternatives for these inputs.")


def planning_page(case,store,state):
    st.title("Monsoon Rehearsal")
    st.caption("Synthetic maintenance-consequence and achieved-prefix review · EPA SWMM")
    decision_slot = st.container()
    left,right=st.columns([1.1,1],gap="large")
    with right, st.expander("Reference network and verified work"):
        st.plotly_chart(network_figure(case,state["completed_jobs"]),width="stretch",config={"displayModeBar":False})
        st.caption("A1–A2: Branch A · B1–B2: Branch B · S: designed storage · J–T: shared trunk · O: receiving water. Hover a node for its name.")
        st.caption("Schematic, not a surveyed map. Teal links have verified restoration. Spill leaves the model at named nodes; no property flood extent is inferred.")
    with left:
        st.subheader("Work opportunity")
        deadline=st.number_input("Restore and return by (minutes after shift start)",min_value=0,max_value=1440,value=case.get("default_deadline_minutes",180),step=15,key="deadline")
        st.caption("Use the reviewed restoration-and-return deadline. A forecast rain time alone does not establish the work window. Inspect earlier stop signals in Work window.")
        planning=[s for s in case["scenarios"] if s["phase"]=="planning"]
        ids=st.multiselect("Planning scenarios",[s["id"] for s in planning],default=[s["id"] for s in planning],format_func=lambda x:next(s["title"] for s in planning if s["id"]==x),key="scenario_ids")
        scenarios=[s for s in planning if s["id"] in ids]
        user_text=st.text_input("Your comparison queue (optional)",placeholder="J1, J2, J3, J4",help="A user-entered comparator. No expert or field validation is implied.")
        operator_queue=[x.strip().upper() for x in user_text.split(",") if x.strip()] or None
        st.caption(f'Verified jobs: {", ".join(state["completed_jobs"]) or "none"} · crew clock {state["elapsed_minutes"]:g} min · location {state["crew_location"]}')
        try:
            inputs=context(case,scenarios,deadline,state)
            inputs["operator_queue"]=operator_queue
            fingerprint=canonical_hash(inputs)
            current_context=store.set_context(case["id"],fingerprint,inputs,actor="Planner",expected_version=state["version"])
            current_version=current_context["version"]
            input_error=None
        except Exception as exc:
            fingerprint=None
            current_version=None
            input_error=str(exc)
            st.warning(input_error)
        if st.button("Run rehearsal",type="primary",disabled=bool(input_error),width="stretch"):
            try:
                with st.status("Running the hydraulic comparisons…",expanded=True) as status:
                    count=st.empty()
                    def progress(n,run): count.write(f'{n} distinct state/scenario results · latest {run["scenario_id"]}')
                    result=rehearse(case,scenarios,deadline,store,operator_queue=operator_queue,progress=progress)
                    st.session_state["episode"]=result
                    st.session_state.pop("selected_plan",None)
                    st.session_state.pop("inspect_plan_id",None)
                    status.update(label="Rehearsal complete",state="complete",expanded=False)
            except Exception as exc:
                st.error(f"Rehearsal could not be completed: {exc}")
    with st.expander("Jobs, physical changes, and input assumptions"):
        st.dataframe([{k:j.get(k) for k in ["id","title","asset_id","nominal_minutes","max_minutes","description"]} for j in case["jobs"]],hide_index=True,width="stretch")
        st.write("All four jobs are discretionary in this reference case. Times are synthetic, include on-site restoration, and exclude the separate travel allowance. Maintenance ends before the hydraulic event; wet-work interruption is outside this prototype's supported envelope.")
        for s in scenarios: st.write(f'**{s["title"]}:** {s["description"]}')
    episode=st.session_state.get("episode")
    with decision_slot:
        st.caption(f'Context revision {current_version if current_version is not None else state["version"]} · crew clock {state["elapsed_minutes"]:g} min · location {state["crew_location"]} · verified jobs: {", ".join(state["completed_jobs"]) or "none"}')
        if not episode:
            render_verdict(None, None, None, condition_unknown=state["condition_unknown"])
    if not episode:
        return
    stale=episode["context_fingerprint"] != fingerprint or episode["state_version"] != current_version
    options={p["id"]:p for p in episode.get("plans", []) if p.get("admissible")}
    recommendation=episode.get("recommended")
    with decision_slot:
        if options:
            if st.session_state.get("inspect_plan_id") not in options:
                st.session_state["inspect_plan_id"] = recommendation["id"] if recommendation and recommendation["id"] in options else next(iter(options))
            chosen_id=st.selectbox("Plan", list(options), format_func=lambda pid: " → ".join(options[pid]["queue"]) or "No additional discretionary work", key="inspect_plan_id")
            selected=options[chosen_id]
        else:
            selected=None
        st.session_state["selected_plan"] = selected
        audit_key=canonical_hash({"fingerprint":episode["context_fingerprint"],"version":episode["state_version"],"plan":selected}) if selected else None
        audits=st.session_state.setdefault("plan_audits",{})
        audit=audits.get(audit_key)
        # Populate after actions so a newly completed audit is visible immediately.
        verdict_slot=st.container()
        c1,c2=st.columns(2)
        with c1:
            if st.button("Audit selected plan", disabled=stale or not selected or state["condition_unknown"], key="audit_selected", type="primary", width="stretch"):
                try:
                    with st.status("Checking achieved work states and numerical stability…",expanded=True) as status:
                        count=st.empty()
                        audit=audit_selected_plan(case,episode,selected,store,progress=lambda n,r:count.write(f'{n} distinct states checked at two routing steps and two event horizons.'))
                        audits[audit_key]=audit
                        status.update(label="Stress audit complete",state="complete",expanded=False)
                except Exception as exc: st.error(f"Stress audit could not be completed: {exc}")
        with c2:
            empty=next((p for p in options.values() if p.get("queue") == []), None)
            st.button("Select no additional work", disabled=stale or empty is None or selected is empty or state["condition_unknown"],
                on_click=choose_plan, args=(empty["id"] if empty else None,), key="choose_no_work", width="stretch")
        snapshot=plan_snapshot(case,episode,selected,audit) if selected and not stale else None
        gate=validate_audit(snapshot) if snapshot and audit else None
        with verdict_slot:
            render_verdict(selected, audit, gate, stale=stale, condition_unknown=state["condition_unknown"])
            st.caption(f'Rehearsal: {"historical" if stale else "complete"} · audit: {(audit or {}).get("status", "outstanding")} · supervisor review: {"available separately" if gate and gate.get("approval_allowed") and not stale else "blocked"}')
        if audit:
            with st.expander("Inspect audit findings", expanded=True): show_assurance(audit,gate)
        c1,c2=st.columns([2,1])
        with c1:
            actor=st.text_input("Planner name",value="Research planner",key="planner_name")
            st.caption("Named actors are local audit labels, not authenticated production roles.")
        with c2:
            if st.button("Save selected plan for review",type="primary",disabled=stale or not selected or state["condition_unknown"],width="stretch"):
                try:
                    plan=store.save_plan(case["id"],snapshot,actor=actor)
                    if plan.get("assurance_gate",{}).get("approval_allowed"):
                        st.success(f'Plan {plan["id"][:8]} saved. Open Work tickets for supervisor review.')
                    else:
                        st.info(f'Plan {plan["id"][:8]} saved as a blocked draft. Review and approval remain blocked.')
                except Exception as exc: st.error(str(exc))
        st.button("Open Work tickets", on_click=open_workspace, args=("Work tickets",), key="go_tickets")
        if snapshot:
            st.download_button("Download printable plan briefing",render_briefing(case,episode,snapshot),file_name="monsoon-plan-briefing.html",mime="text/html")
    st.divider()
    with st.expander("Planning comparisons, achieved work and scenario details", expanded=False):
        render_comparison(case,episode,selected)
    st.download_button("Export this rehearsal",json.dumps(episode,indent=2),file_name="monsoon-rehearsal.json",mime="application/json")


def tickets_page(case,store,state):
    st.markdown('<div class="mr-kicker">REVIEW / EXECUTION / VERIFIED CONDITION</div>',unsafe_allow_html=True)
    st.title("Work tickets")
    st.write("Review a saved plan, approve its exact scope, and verify the observed condition before the next rehearsal.")
    if state["condition_unknown"]:
        st.warning("Condition unresolved — further supported planning is blocked. Restoration is not credited until verification resolves the affected asset. Earlier results remain historical.")
    metrics=st.columns(3)
    metrics[0].metric("Verified restorations",len(state["completed_jobs"]))
    metrics[1].metric("Crew clock",f'{state["elapsed_minutes"]:g} min')
    metrics[2].metric("Physical state revision",state["version"])
    actor=st.text_input("Acting person's name",value="Research supervisor",key="workflow_actor")
    notes=st.text_input("Review / action notes",value="Synthetic prototype exercise",key="workflow_notes")
    with st.expander("Record a crew delay before the next dispatch"):
        st.caption("Advance the observed clock while the crew stays at its current location. This invalidates unstarted approvals and requires a fresh rehearsal.")
        delayed=st.number_input("Observed crew clock after waiting (minutes)",min_value=float(state["elapsed_minutes"]),value=float(state["elapsed_minutes"]),step=5.0,key="delay_clock")
        action("Record delay and require replanning",lambda:store.record_delay(case["id"],delayed,actor,notes),key="delay",disabled=state["condition_unknown"] or delayed<=state["elapsed_minutes"])
    plans=store.list_plans(case["id"])
    if not plans:
        st.info("No saved plans. Rehearse and audit a queue, then save a reviewable plan or an explicitly blocked draft.")
        st.button("Go to Rehearse", on_click=open_workspace, args=("Rehearse",), key="tickets_rehearse")
        return
    plan_options={p["id"]:p for p in plans}
    selected_plan_id=st.selectbox("Saved plan",list(plan_options),format_func=lambda pid:f'{pid[:8]} · {plan_options[pid]["status"]}',key="workflow_plan_id")
    plan=store.get_plan(selected_plan_id)
    snapshot=plan.get("snapshot",{})
    st.write("**Queue:**", " → ".join(snapshot.get("queue",[])) or "No jobs")
    st.caption(f'Plan status: {plan["status"]} · approvals refer to the saved input fingerprint.')
    if plan["is_stale"]:
        st.warning("This saved plan is historical. Current inputs or observed work have changed; rehearse again before issuing or starting another job.")
    gate=plan.get("assurance_gate",{})
    blocked=not gate.get("approval_allowed",False)
    if gate.get("required"):
        render_verdict(snapshot, snapshot.get("assurance"), gate, stale=plan["is_stale"], condition_unknown=state["condition_unknown"])
        with st.expander("Inspect saved-plan audit", expanded=False):
            show_assurance(snapshot.get("assurance"),gate)
    else:
        st.warning("Historical plan: this record predates the required stress audit. It is retained as legacy workflow evidence, not evidence of a passing audit.")
    a,b=st.columns(2)
    with a: action("Mark reviewed",lambda:store.review(plan["id"],actor,notes),key="review",disabled=plan["status"]!="draft" or plan["is_stale"] or blocked)
    with b: action("Approve reviewed plan",lambda:store.approve(plan["id"],actor,notes),key="approve",disabled=plan["status"]!="reviewed" or plan["is_stale"] or blocked,primary=True)
    jobs=snapshot.get("queue",[])
    if not jobs:
        st.info("This records a decision to do no additional discretionary work. No work ticket can be issued from this queue. Existing flood risk remains; an audit pass does not declare the catchment or work site safe.")
    if jobs:
        job=st.selectbox("Job to ticket",jobs,key="ticket_job")
        action("Create work ticket",lambda:store.create_ticket(plan["id"],job,actor),key="create_ticket",disabled=plan["status"]!="approved" or plan["is_stale"] or blocked)
    tickets=store.list_tickets(case["id"])
    st.divider()
    if not tickets:
        st.caption("No work tickets issued yet.")
    else:
        ticket_options={t["id"]:t for t in tickets}
        selected_ticket_id=st.selectbox("Work ticket",list(ticket_options),format_func=lambda tid:f'{ticket_options[tid]["job_id"]} · {ticket_options[tid]["status"]} · {tid[:8]}',key="work_ticket_id")
        ticket=store.get_ticket(selected_ticket_id)
        ticket_plan=store.get_plan(ticket["plan_id"])
        ticket_stale=ticket_plan["is_stale"] or not ticket_plan.get("assurance_gate",{}).get("approval_allowed",False)
        st.write(f'**{ticket["job_id"]}** · {ticket["status"]}')
        if ticket["status"] == "completion_reported":
            st.warning("Completion reported — condition unresolved. Restoration is not credited; further supported planning is blocked pending verification.")
        crew=st.text_input("Assigned crew",value="Crew 1")
        action("Assign crew",lambda:store.assign(ticket["id"],crew,actor),key="assign",disabled=ticket["status"]!="approved" or ticket_stale)
        start=st.number_input("Actual on-site start (minutes)",min_value=0.0,value=float(state["elapsed_minutes"]+case.get("travel_minutes",10)),step=1.0)
        if ticket_plan.get("assurance_gate",{}).get("required"):
            st.caption("A later start changes the audited schedule. Record the delay, rehearse and audit again before starting.")
        action("Start job",lambda:store.start(ticket["id"],start,actor),key="start",disabled=ticket["status"]!="assigned" or ticket_stale)
        action("Cancel unstarted ticket",lambda:store.cancel(ticket["id"],actor,notes),key="cancel",disabled=ticket["status"] not in ("approved","assigned"))
        job_data=next(j for j in ticket_plan["snapshot"]["jobs"] if j["id"]==ticket["job_id"])
        actual_start=float(ticket.get("start_minute") or start)
        finish=st.number_input("Actual finish, including restoration (minutes)",min_value=0.0,value=actual_start+float(job_data["nominal_minutes"]),step=1.0)
        evidence=st.text_area("Completion / inspection evidence",placeholder="Describe the observed restored condition and evidence reference. Use synthetic evidence only for this exercise.")
        action("Report completion",lambda:store.report_completion(ticket["id"],finish,evidence,actor),key="report",disabled=ticket["status"] not in ("in_progress","revision_needed"))
        c1,c2=st.columns(2)
        with c1: action("Verify restored condition",lambda:store.verify(ticket["id"],True,evidence,actor,observed_condition="restored"),key="verify",disabled=ticket["status"]!="completion_reported",primary=True)
        with c2: action("Record failed verification",lambda:store.verify(ticket["id"],False,evidence,actor,observed_condition="uncertain"),key="reject_verification",disabled=ticket["status"]!="completion_reported")
        action("Close verified ticket",lambda:store.close(ticket["id"],actor),key="close",disabled=ticket["status"]!="verified")
        st.caption("Reporting work advances the observed crew clock. Only accepted restoration evidence changes the hydraulic condition. Earlier unstarted work is then replanned against the remaining time.")
        with st.expander("Ticket record"): st.json(ticket)
    with st.expander("Audit trail"):
        st.dataframe(store.events(case["id"]),hide_index=True,width="stretch")
    manifest=store.export_manifest(case["id"])
    st.download_button("Export workflow evidence",json.dumps(manifest,indent=2),file_name="monsoon-workflow.json",mime="application/json")
    st.download_button("Download saved plan briefing",render_briefing(case,plan=plan,workflow=manifest),file_name="monsoon-saved-plan.html",mime="text/html")


def decision_review_panel():
    from monsoon.decision_review import load_decision_review

    st.subheader("Why a plan can help, harm or remain unresolved")
    st.caption("Read-only examples from retained synthetic SWMM runs. These are historical explanations, not a current plan audit or evidence of scheduling superiority. They cannot approve or dispatch work.")
    review=load_decision_review(ROOT)
    if review.get("status")!="verified":
        st.error("Decision examples are unavailable because their retained evidence is missing or has changed.")
        with st.expander("Decision evidence checks"):
            st.json(review.get("errors",[]),expanded=False)
        return
    for card in review["cards"]:
        with st.container(border=True):
            st.markdown(f"#### {card['title']}")
            st.write(card["explanation"])
            st.caption(f"Scenario {card['scenario_id']} · Queue: {', '.join(card['queue']) or 'none'} · Completed jobs: {', '.join(card['completed_jobs']) or 'none'}")
            rows=[]
            for metric in card["metrics"]:
                difference=metric["absolute_difference"] if metric.get("comparison")=="routing_step_halving" else metric["difference"]
                row={"Measure":metric["label"],"Location":metric.get("location_id",""),
                     "Scenario":metric.get("scenario_id",card["scenario_id"]),
                     "Reference":f"{metric['baseline_label']}: {metric['baseline_value']:.6f}",
                     "Compared":f"{metric['action_label']}: {metric['action_value']:.6f}",
                     "Difference used by check":difference,"Unit":metric["unit"]}
                if "tolerance_value" in metric:
                    row["Allowed difference"]=metric["tolerance_value"]
                rows.append(row)
            st.dataframe(rows,hide_index=True,width="stretch")
            if any(metric.get("comparison")=="routing_step_halving" for metric in card["metrics"]):
                st.caption("The routing-step check compares the absolute difference. Protected-location checks compare the signed increase in spill.")
            with st.expander(f"Sources for {card['title']}"):
                st.json(card["source_records"],expanded=False)
    with st.expander("How these historical examples are checked"):
        st.caption(review["integrity_scope"])
        st.json(review["sources"],expanded=False)


def evidence_page(case,store):
    st.markdown('<div class="mr-kicker">MODEL / RESULTS / ASSURANCE</div>', unsafe_allow_html=True)
    st.title("Model & assurance")
    st.write("Understand the model behind each recommendation and the checks required before a plan can proceed.")
    left, middle, right = st.columns(3)
    left.metric("Hydraulic engine", "EPA SWMM")
    middle.metric("Network · one crew", "4 jobs")
    right.metric("Data basis", "Synthetic")
    st.info("This demonstration uses synthetic geometry and inflows. It is not calibrated to a real site and does not authorise field work.")

    st.subheader("How a plan is checked")
    for title, description in [
        ("01 · Achievable work", "Job duration, travel, prerequisites and the return deadline determine which jobs can finish."),
        ("02 · Hydraulic consequences", "Completed restoration states are compared with no additional work and alternative schedules under the same assumptions."),
        ("03 · Location safeguards", "A lower total spill is insufficient: numerical checks and every protected location must also pass."),
        ("04 · Review and verification", "Approval requires a passing audit bound to the exact plan. Reporting completion alone does not update the hydraulic state."),
    ]:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.write(description)

    st.subheader("Results and limits")
    st.write("The reference planner ties the adaptive marginal baseline. The separate outlet-restoration example ties downstream-first. Neither comparison establishes scheduling superiority.")
    holdout_file = ROOT / "evidence" / "holdouts.json"
    if holdout_file.exists():
        holdouts = json.loads(holdout_file.read_text(encoding="utf-8"))
        st.warning("In stress case H2, the robust and adaptive marginal policies both fail the per-location no-worsening screen. A lower total spill does not override increased spill at a protected location.")
        with st.expander("Stress-case results"):
            frame = pd.DataFrame(holdouts.get("comparisons", []))
            cols = [c for c in ["method", "scenario_id", "status", "total_spill_m3", "completed_jobs"] if c in frame]
            st.dataframe(frame[cols], hide_index=True, width="stretch")
            st.download_button("Download stress-case results", holdout_file.read_bytes(),
                               file_name="holdouts.json", mime="application/json")
    else:
        st.warning("Stress-case evidence is unavailable. Do not infer a passing result.")
    with st.expander("Model scope and assumptions"):
        st.write("One crew, four independent clear-width restorations, prescribed inflows and receiving-water levels, and a common restoration-and-return deadline. Only completed, verified work receives restoration credit.")
        st.write("The model reports drainage spill at represented nodes. It does not predict surface flood extent, property damage, live weather or the hydraulic effects of interrupted excavation.")
        st.write("The demonstration has no completed field calibration or operator validation. Named actors in the ticket workflow are prototype audit labels, not verified professional identities.")
    with st.expander("Reference network inputs"):
        st.json(case, expanded=False)
    st.caption("Use Demonstration to inspect the maintenance case, boundary limits and transferred-harm example. Use Rehearse to calculate and audit a specific plan.")


def workspace(case,store):
    state=store.project_state(case["id"])
    with st.sidebar:
        st.markdown("### Monsoon\n### Rehearsal")
        st.caption("Plan the achievable work.")
        research=False
        if os.environ.get("MONSOON_ENABLE_RESEARCH_UI") == "1":
            research=st.checkbox("Show research tools",value=False,key="research_tools_enabled",
                                 help="Internal research workspaces; unavailable in the public interface.")
        else:
            st.session_state["research_tools_enabled"]=False
        pages=["Rehearse","Demonstration","Work window","Work tickets","Evidence"]
        if research:
            pages.insert(3,"Validation")
        if st.session_state.get("workspace") not in pages:
            st.session_state["workspace"]="Rehearse"
        page=st.radio("Workspace",pages,key="workspace",label_visibility="collapsed")
        st.caption("Rehearsal hydraulics: EPA SWMM · synthetic reference")
        st.divider()
        st.caption("REFERENCE CATCHMENT")
        st.write(case["title"])
        st.caption("Synthetic data · one crew · four jobs")
        st.caption("Demonstration environment · no live dispatch")
    notice=st.session_state.pop("notice",None)
    if notice: st.success(notice)
    if case.get("runtime_warning"): st.warning(case["runtime_warning"])
    if page=="Rehearse": planning_page(case,store,state)
    elif page=="Demonstration":
        from monsoon.demo_ui import render_demo
        render_demo()
    elif page=="Work window":
        from monsoon.preparation_ui import render_work_window
        render_work_window(case)
    elif page=="Work tickets": tickets_page(case,store,state)
    elif page=="Validation":
        from monsoon.validation_ui import render_validation
        render_validation()
    else: evidence_page(case,store)


def main():
    case,store=initialise()
    try:
        workspace(case,store)
    finally:
        store.disconnect()


if __name__=="__main__":
    main()
