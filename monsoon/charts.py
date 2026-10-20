"""Schematic and comparison charts, without scientific decision logic."""
from __future__ import annotations
from html import escape
from math import isfinite
from numbers import Real

import plotly.graph_objects as go

TEAL = "#008f86"
NAVY = "#173142"
AMBER = "#d89026"
MUTED = "#697c86"


def node_spill_rows(case: dict, values: dict | None, display_mode: str = "absolute",
                    epsilon_m3: float = 0.05) -> list[dict]:
    """Describe explicit absolute spill or signed-change values in node order.

    This helper does not compute a baseline or infer missing results. In change
    mode, ``within_tolerance`` means no increase above epsilon, including a
    decrease of any size; it does not mean abs(change) <= epsilon.
    """
    if display_mode not in {"absolute", "change"}:
        raise ValueError("display_mode must be 'absolute' or 'change'")
    if (isinstance(epsilon_m3, bool) or not isinstance(epsilon_m3, Real)
            or not isfinite(epsilon_m3) or epsilon_m3 < 0):
        raise ValueError("epsilon_m3 must be a finite nonnegative number")
    threshold = f"{epsilon_m3:g} m³"
    rows = []
    for node in case["nodes"]:
        raw = None if values is None else values.get(node["id"])
        missing_reason = None
        if raw is None:
            missing_reason = "not supplied"
        elif isinstance(raw, bool) or not isinstance(raw, Real) or not isfinite(raw):
            missing_reason = "invalid numeric value"
        elif display_mode == "absolute" and raw < 0:
            missing_reason = "negative absolute spill"
        value = None if missing_reason else float(raw)
        if value is None:
            status, status_label, value_label = "missing", "Value unavailable", "Unavailable"
        elif value > epsilon_m3:
            status = "above_tolerance"
            status_label = ("Spill" if display_mode == "absolute" else "Increase") + f" > {threshold}"
            value_label = f"{value:.6g} m³" if display_mode == "absolute" else f"Δ {value:+.6g} m³"
        else:
            status = "within_tolerance"
            status_label = f"Spill ≤ {threshold}" if display_mode == "absolute" else f"No increase > {threshold}"
            value_label = f"{value:.6g} m³" if display_mode == "absolute" else f"Δ {value:+.6g} m³"
        rows.append({"node_id": node["id"], "label": node.get("label", node["id"]),
                     "kind": node.get("kind", "junction"), "value_m3": value,
                     "value_label": value_label, "status": status,
                     "status_label": status_label, "missing_reason": missing_reason})
    return rows


def network_figure(case: dict, completed=(), spills: dict | None = None, *,
                   display_mode: str = "absolute", epsilon_m3: float = 0.05):
    """Draw a model schematic using values already selected by the caller.

    ``spills`` supplies absolute volumes in absolute mode, or signed differences
    from the matching no-additional-work result in change mode.
    """
    nodes = {n["id"]: n for n in case["nodes"]}
    rows = node_spill_rows(case, spills, display_mode, epsilon_m3)
    styles = {"above_tolerance": ("triangle-up", AMBER),
              "within_tolerance": ("circle", NAVY), "missing": ("x", MUTED)}
    fig = go.Figure()
    for link in case["links"]:
        a, b = nodes[link["from_node"]], nodes[link["to_node"]]
        restored = link.get("job_id") in completed
        fig.add_trace(go.Scatter(x=[a["x"], b["x"]], y=[a["y"], b["y"]], mode="lines",
                                line=dict(color=TEAL if restored else "#9cabb3", width=5 if restored else 3),
                                hoverinfo="text", text=link["id"], showlegend=False))
        fig.add_annotation(x=b["x"]*.68+a["x"]*.32, y=b["y"]*.68+a["y"]*.32,
                           ax=a["x"]*.68+b["x"]*.32, ay=a["y"]*.68+b["y"]*.32,
                           xref="x", yref="y", axref="x", ayref="y", showarrow=True,
                           arrowhead=2, arrowsize=1.2, arrowwidth=1.5, arrowcolor="#78939b")
    ns = list(nodes.values())
    fig.add_trace(go.Scatter(x=[n["x"] for n in ns], y=[n["y"] for n in ns], mode="markers+text",
        text=[escape(str(r["node_id"])) + (" (storage)" if r["kind"] == "storage" else "")
              + "<br>" + r["value_label"] for r in rows], textposition="top center",
        textfont=dict(size=12, color=NAVY),
        marker=dict(size=[25 if n.get("kind")=="storage" else 17 for n in ns],
                    color=[styles[r["status"]][1] for r in rows],
                    symbol=[styles[r["status"]][0] for r in rows],
                    line=dict(width=[3 if r["kind"] == "storage" else 1.5 for r in rows],
                              color=["#0d1d28" if r["kind"] == "storage" else "white" for r in rows])),
        hovertext=[f'{escape(str(r["node_id"]))}: {escape(str(r["label"]))}'
                   + f'<br>Type: {escape(str(r["kind"]))}<br>{r["value_label"]}<br>{r["status_label"]}'
                   + (f'<br>Reason: {r["missing_reason"]}' if r["missing_reason"] else "") for r in rows],
        hoverinfo="text", showlegend=False))
    threshold = f"{epsilon_m3:g} m³"
    labels = {"above_tolerance": ("Spill" if display_mode == "absolute" else "Increase") + f" > {threshold}",
              "within_tolerance": f"Spill ≤ {threshold}" if display_mode == "absolute" else f"No increase > {threshold}",
              "missing": "Value unavailable"}
    for status, (symbol, color) in styles.items():
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=labels[status],
                                marker=dict(symbol=symbol, color=color, size=12), hoverinfo="skip"))
    mode_title = "Absolute node spill (m³)" if display_mode == "absolute" else "Change vs. no additional work (Δ m³)"
    fig.update_layout(title=dict(text="Network schematic · " + mode_title
                                + "<br><sup>Storage nodes are labelled and outlined; arrows show model link direction.</sup>",
                                 font=dict(size=15), x=0.02),
                      height=380, margin=dict(l=25,r=25,t=75,b=55), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(visible=False,range=[-1,10]),yaxis=dict(visible=False,range=[-.5,3.7]),
                      legend=dict(orientation="h", y=-0.08, x=0, itemclick=False, itemdoubleclick=False),
                      dragmode=False)
    return fig


def timeline_figure(events: list[dict], deadline: float):
    fig=go.Figure()
    for e in events:
        start=e["start_minute"]
        end=e["finish_minute"]
        fig.add_trace(go.Bar(x=[end-start],y=["Crew 1"],base=[start],orientation="h",name=e["job_id"],
                            text=[e["job_id"]],textposition="inside",hovertemplate=f'{e["job_id"]}: {start:g}–{end:g} min<extra></extra>'))
    fig.add_vline(x=deadline,line_dash="dash",line_color=AMBER,annotation_text="Restore / return deadline")
    fig.update_layout(height=165,barmode="overlay",xaxis_title="Minutes after shift start",showlegend=False,
                      margin=dict(l=10,r=20,t=25,b=20),paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)",colorway=[TEAL,"#436c85",AMBER,"#777ab0"])
    return fig
