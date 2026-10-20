"""Private subprocess entry point: one SWMM global-state engine per process."""
from __future__ import annotations
import json
import math
from pathlib import Path
import re
import sys
import traceback

from swmm.toolkit import solver
from swmm.toolkit.shared_enum import NodeResult, LinkResult


def run(folder: Path):
    req = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    case = req["case"]
    nodes, links = case["nodes"], case["links"]
    result = {"run_id": req["run_id"], "status": "failed", "valid": False, "engine_version": req["engine"]["engine_version"],
              "total_spill_m3": None, "nodes": {}, "diagnostics": {}, "timeseries": [], "errors": []}
    opened = started = False
    try:
        solver.swmm_open(str(folder / "model.inp"), str(folder / "model.rpt"), str(folder / "model.out"))
        opened = True
        solver.swmm_start(True)
        started = True
        ni = {n["id"]: solver.project_get_index(solver.swmm_NODE, n["id"]) for n in nodes}
        li = {l["id"]: solver.project_get_index(solver.swmm_LINK, l["id"]) for l in links}
        def volume():
            return sum(solver.node_get_result(i, NodeResult.VOLUME.value) for i in ni.values()) + sum(solver.link_get_result(i, LinkResult.VOLUME.value) for i in li.values())
        initial = volume()
        duration = {n["id"]: 0. for n in nodes}
        prev_depth = {n["id"]: solver.node_get_result(ni[n["id"]], NodeResult.DEPTH.value) for n in nodes}
        min_link = {l["id"]: 0. for l in links}
        max_link = {l["id"]: 0. for l in links}
        final_time, next_sample, last_time = 0., 0., 0.
        integrated_spill = {n["id"]: 0. for n in nodes}
        while True:
            elapsed_days = solver.swmm_step()
            # The SWMM C API returns elapsed DAYS, despite an old toolkit docstring saying milliseconds.
            sec = elapsed_days * 86400 if elapsed_days > 0 else req["horizon_minutes"]*60
            dt = max(0., sec-last_time)
            depths = {n["id"]: solver.node_get_result(ni[n["id"]], NodeResult.DEPTH.value) for n in nodes}
            for n in nodes:
                nid = n["id"]
                threshold = case["depth_threshold_fraction"] * n["max_depth_m"]
                if n["kind"] != "outfall":
                    y0, y1 = prev_depth[nid]-threshold, depths[nid]-threshold
                    fraction = 1. if y0 > 0 and y1 > 0 else 0.
                    if y0*y1 < 0:
                        fraction = abs(y1)/(abs(y0)+abs(y1)) if y1 > 0 else abs(y0)/(abs(y0)+abs(y1))
                    duration[nid] += dt*fraction/60
                integrated_spill[nid] += max(0., solver.node_get_result(ni[nid], NodeResult.FLOOD.value))*dt
            flows = {lid: solver.link_get_result(i, LinkResult.FLOW.value) for lid, i in li.items()}
            for lid, q in flows.items():
                min_link[lid], max_link[lid] = min(min_link[lid], q), max(max_link[lid], q)
            if sec >= next_sample or elapsed_days <= 0:
                result["timeseries"].append({"minutes": sec/60, **{f"depth_{k}": v for k,v in depths.items()}, **{f"flow_{k}":v for k,v in flows.items()}})
                next_sample = (math.floor(sec/60)+1)*60
            prev_depth, last_time, final_time = depths, sec, sec
            if elapsed_days <= 0:
                break
        final_storage = volume()
        totals = solver.system_get_routing_totals()
        routed = {key: getattr(totals, key) for key in ["dwInflow","wwInflow","gwInflow","iiInflow","exInflow","flooding","outflow","evapLoss","seepLoss","initStorage","finalStorage","pctError"]}
        for n in nodes:
            ns = solver.node_get_stats(ni[n["id"]])
            result["nodes"][n["id"]] = {"spill_m3": ns.volFlooded, "max_depth_m": ns.maxDepth,
                 "duration_above_threshold_min": duration[n["id"]], "threshold_m": case["depth_threshold_fraction"]*n["max_depth_m"],
                 "flood_duration_min": ns.timeFlooded*60, "integrated_spill_m3": integrated_spill[n["id"]],
                 "nonconverged_steps": ns.nonConvergedCount}
        total_spill = sum(n["spill_m3"] for n in result["nodes"].values())
        solver.swmm_end()
        started = False
        mass_balance = solver.swmm_get_mass_balance()
        solver.swmm_report()
        solver.swmm_close()
        opened = False
        report = (folder / "model.rpt").read_text(encoding="utf-8", errors="replace")
        warnings = [line.strip() for line in report.splitlines() if "WARNING" in line or "ERROR" in line]
        inflow = sum(routed[k] for k in ["dwInflow","wwInflow","gwInflow","iiInflow","exInflow"])
        residual = initial+inflow-routed["outflow"]-total_spill-routed["evapLoss"]-routed["seepLoss"]-final_storage
        prescribed = 0.
        # Exact integral of input piecewise-linear flow series (separate from reverse boundary inflow).
        h=req["hydraulic"]
        unit_areas_min = {"triangle":22.5,"double":32.5,"plateau":45.0}
        prescribed = (h["peak_a_cms"]+h["peak_b_cms"])*unit_areas_min[h["hydrograph"]]*60
        result["diagnostics"] = {"continuity_error_percent": mass_balance[1], "inflow_m3": inflow,
             "outflow_m3": routed["outflow"], "initial_storage_m3": initial, "final_storage_m3": final_storage,
             "spill_m3": total_spill, "evaporation_m3": routed["evapLoss"], "seepage_m3": routed["seepLoss"],
             "balance_residual_m3": residual, "balance_residual_percent": 100*residual/max(1.,initial+inflow),
             "routing_total_spill_m3": routed["flooding"], "node_spill_sum_m3": total_spill,
             "routing_step_s": req["routing_step"], "horizon_minutes": final_time/60,
             "prescribed_inflow_integral_m3": prescribed, "boundary_inflow_approx_m3": max(0.,inflow-prescribed),
             "min_link_flow_cms": min_link, "max_link_flow_cms": max_link, "warnings": warnings,
             "raw_routing_totals": routed, "storage_units_note": "Storage is summed from node/link volume APIs in m3; raw routing init/final storage may be internal ft3.",
             "spill_definition": "SWMM node overflow irreversibly leaves model; absorbing collectors, not predicted property flood volume.",
             "threshold_duration_method": "Piecewise-linear threshold crossing at every routing step; depths relative to invert."}
        problems=[]
        if abs(mass_balance[1]) > 1:
            problems.append("Routing continuity error exceeds 1% QA bound")
        if abs(residual) > max(.1,.01*(initial+inflow)):
            problems.append("Independent volume balance exceeds 1% or 0.1 m3 near-zero tolerance")
        if abs(total_spill-routed["flooding"]) > max(.01,.001*total_spill):
            problems.append("Node spill sum does not reconcile with routing flooding total")
        if any("ERROR" in line for line in warnings):
            problems.append("SWMM report contains an error")
        if any(n["nonconverged_steps"] > 0 for n in result["nodes"].values()):
            problems.append("At least one node failed dynamic-wave convergence")
        if any(not math.isfinite(n[k]) for n in result["nodes"].values() for k in ["spill_m3","max_depth_m","duration_above_threshold_min"]):
            problems.append("Nonfinite hydraulic output")
        result.update(status="invalid" if problems else "succeeded", valid=not problems,
                      total_spill_m3=total_spill if not problems else None, errors=problems)
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
    finally:
        if started:
            try: solver.swmm_end()
            except Exception: pass
        if opened:
            try: solver.swmm_close()
            except Exception: pass
    (folder / "result.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")


if __name__ == "__main__":
    run(Path(sys.argv[1]))
