"""A read-only walkthrough. No planner, store or ticket mutation dependencies."""
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .decision_review import load_decision_review
from .maintenance_benchmark import load_results

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "evidence/v0.9/maintenance-benchmark"
MANIFEST_SHA256 = "f8a90c8ec51de812c545a3d4f5afa81e2df34b19f458f10b4475ac6b44e4001d"


def render_demo():
    st.markdown('<div class="mr-hero"><div class="mr-kicker" style="color:#a9e5da">'
                'MONSOON REHEARSAL · GUIDED DEMONSTRATION</div>'
                '<h1>Choose the work that can finish.<br>Check where the water goes.</h1>'
                '<p>A three-minute walkthrough of maintenance benefit, deadline constraints '
                'and the reasons a promising plan may need to stop.</p></div>', unsafe_allow_html=True)
    st.caption("Read-only synthetic demonstration · no work is approved or dispatched · operator review pending")
    step = st.radio("Explore the decision", ["1 · Maintenance benefit", "2 · Work before rain",
                                           "3 · Catch transferred harm", "4 · Decision controls"],
                    horizontal=True, key="demo_step")
    if step.startswith(("1", "2")):
        loaded = load_results(BENCHMARK, MANIFEST_SHA256)
        if loaded["status"] != "verified":
            st.error("Benchmark evidence is missing or changed. Results are unavailable.")
            st.write(loaded["errors"])
            return
        result = loaded["result"]
        if step.startswith("1"):
            st.subheader("Restore the final outlet before inflow arrives")
            st.write("Two feeder branches enter storage, then discharge through one restricted final reach. "
                     "The model changes that reach from 0.10 m to its declared 1.00 m clear width. "
                     "This geometry is synthetic; a real site would need a survey and measured response.")
            choices = {c["id"]: c for c in result["comparisons"]}
            selected = st.selectbox("Boundary and inflow case", list(choices),
                                    format_func=lambda k: f'{k} · {choices[k]["title"]}')
            c = choices[selected]
            if c["status"] == "unresolved":
                st.warning("Unresolved — the receiving-water boundary keeps supplying water. "
                           "Extending the event changes spill beyond the unchanged 0.05 m³ limit.")
                st.write(c["errors"])
                st.info("No reliable benefit claim or work recommendation is available for this boundary.")
            else:
                left, middle, right = st.columns(3)
                left.metric("Restricted outlet · spill", f'{c["baseline_total_m3"]:,.1f} m³')
                middle.metric("Restored outlet · spill", f'{c["restored_total_m3"]:,.1f} m³')
                right.metric("Modelled reduction", f'{c["reduction_m3"]:,.1f} m³')
                fig = go.Figure()
                for label, key, color in [("Restricted outlet", "baseline_m3", "#bc6249"),
                                           ("Restored outlet", "restored_m3", "#168477")]:
                    fig.add_bar(name=label, x=[r["node"] for r in c["rows"]],
                                y=[r[key] for r in c["rows"]], marker_color=color)
                fig.update_layout(barmode="group", height=330, margin=dict(l=10,r=10,t=20,b=10),
                                  yaxis_title="Modelled spill (m³)", xaxis_title="Model location",
                                  legend=dict(orientation="h", y=1.15))
                st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
                st.success("Numerical checks and all represented-location limits pass for this case.")
                with st.expander("Location checks and recorded values"):
                    st.dataframe(pd.DataFrame(c["rows"]), hide_index=True, width="stretch")
            st.info(result["baseline_comparison"])
            st.caption("All six cases are retained: four declared benefit cases, a zero-inflow control, "
                       "and an unresolved high-backwater control. 36 native SWMM runs; source and raw-file checksums checked on opening.")
        else:
            st.subheader("A job must fit with its duration bound and the crew's return")
            window = st.radio("Time before crew-stop cutoff", [120, 50],
                              format_func=lambda n: f"{n} minutes", horizontal=True)
            timing = result["timing"][str(window)]
            st.write("Travel out: **10 min** · maximum job duration: **45 min** · return: **10 min**. "
                     "The scheduler needs a **65-minute** window before allowing the job to start.")
            if timing["completed_jobs"]:
                st.success("Job M1 fits. In this recorded replay it takes 35 minutes and the crew returns at minute 55.")
                st.dataframe(timing["events"], hide_index=True, width="stretch")
            else:
                st.warning("Skip M1: its bounded work and return cannot fit. The model keeps the original restriction.")
            st.caption("The 35-minute actual duration is a synthetic replay input, not an operator observation. "
                       "Completed jobs change pre-event geometry; unfinished work receives no restoration credit. "
                       "This assumes stopping work leaves the original hydraulic condition unchanged; "
                       "an operator must confirm that assumption for each proposed job.")
    elif step.startswith("3"):
        st.subheader("A lower total can hide a worse outcome downstream")
        loaded = load_decision_review(ROOT)
        if loaded["status"] != "verified":
            st.error("Original decision evidence is missing or changed.")
            return
        card = next(c for c in loaded["cards"] if c["id"] == "h2_transfer_harm")
        st.write(card["explanation"])
        for m in card["metrics"]:
            with st.container(border=True):
                st.write(f'**{m["label"]}**')
                st.write(f'{m["baseline_value"]:,.1f} → **{m["action_value"]:,.1f} m³** '
                         f'({m["difference"]:+,.1f} m³)')
        st.error("STOP · B2 exceeds its 0.05 m³ allowed increase. The original plan cannot proceed to approval.")
        st.write("The service requires an intact plan-specific audit, review and approval before ticket dispatch. "
                 "The new outlet example cannot supply that audit for the original four-job network.")
        st.caption("This panel reads checksum-bound historical summaries. It does not rerun native files or approve work.")
    else:
        st.subheader("From a candidate plan to verified work")
        st.write("Each stage has a separate control. A recommendation alone cannot become a work instruction.")
        for title, description in [
            ("Audit the exact plan", "Required numerical and protected-location checks must pass for the selected queue and completed work states."),
            ("Review before approval", "A failed, unresolved or outdated audit blocks approval and dispatch."),
            ("Report, then verify", "A crew completion report does not restore the model automatically. Verified condition evidence is required."),
            ("Rehearse after a change", "Changes to work timing, conditions or the model require a new supported decision."),
        ]:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.write(description)
        st.info("This is a synthetic demonstration, not a field-validated operating system. No completed operator review or observed trial is claimed.")
        st.caption("Open Work tickets to inspect the approval controls. This walkthrough cannot approve or dispatch work.")
