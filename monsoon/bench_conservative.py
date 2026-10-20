"""Separate conservative rectangular-channel bench research engine.

This adapter does not repair SWMM, replace its historical evidence, activate a
site, or establish physical validation. Qualification requires three fixed runs,
an independently recomputed transfer ledger and unchanged convergence limits.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import bench_model
from .bench_process import run_bounded_worker
from .site_data import canonical_json, content_sha256, parse_json

SCHEMA = "monsoon.conservative-bench/1"
ENGINE = "Monsoon rectangular open-channel finite-volume bench / 1"
SOURCE_NAMES = ("__init__.py", "bench_process.py", "bench_conservative.py", "_bench_conservative_worker.py", "bench_fv.py", "bench_model.py", "site_data.py")
_LOADED_SOURCES = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest()
                   for n in SOURCE_NAMES if Path(__file__).with_name(n).exists()}
MAXIMUM_STEPS = 300000
WORKER_TIMEOUT_S = 600
CLAIMS = {"physical_validation_established": False, "operational_activation_allowed": False,
          "engineering_approval_established": False, "native_swmm_correction": False}
LIMITATIONS = [
    "Separate research engine; historical SWMM results and failures are unchanged.",
    "Rectangular prismatic open channels, zero offsets and zero minor losses only.",
    "Positive-area compartments and declared absorbing spill collectors; no lateral overtopping, pressure flow, leakage or re-entry.",
    "A continuous nominally dry history is required; measured wet resets and hotstarts are unsupported.",
    "Numerical qualification is not independent physical validation, operator acceptance or scheduling benefit.",
]


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(canonical_json(value) + "\n", encoding="utf-8", newline="\n")


def conservative_identity():
    sources = {n: _hash(Path(__file__).with_name(n)) for n in SOURCE_NAMES}
    if sources != _LOADED_SOURCES:
        raise ValueError("Conservative source changed after import; restart before execution or verification.")
    import numpy
    dist = importlib.metadata.distribution("numpy")
    binaries = {str(p): _hash(dist.locate_file(p)) for p in dist.files or []
                if str(p).lower().endswith((".dll", ".pyd", ".so", ".dylib", ".py")) or ".so." in str(p).lower()}
    base=Path(sys.base_prefix)
    runtime_files=list(base.glob("*.dll"))+list((base/"DLLs").glob("*.dll"))+list((base/"DLLs").glob("*.pyd"))
    python_runtime={p.relative_to(base).as_posix():_hash(p) for p in runtime_files}
    if getattr(sys,"_base_executable",None):
        python_runtime["base_executable"]=_hash(sys._base_executable)
    return {"engine": ENGINE, "source_sha256": sources, "python_version": sys.version,
            "python_executable_sha256": _hash(sys.executable), "numpy_version": numpy.__version__,
            "numpy_runtime_sha256": binaries,"python_runtime_sha256":python_runtime,
            "units": "m / s / m3", "native_swmm_used": False}


def _contract(site, model, run, split_times):
    report, snapshot = bench_model._validate(site, model, run)
    report.update(schema_version=SCHEMA, engine=ENGINE, limitations=list(LIMITATIONS), **CLAIMS)
    if not report["valid"]:
        return report, None, None
    s, m, r = (snapshot[k] for k in ("site", "model", "run"))
    errors = report["errors"]
    def error(path, code, message):
        errors.append({"path": path, "code": code, "message": message})
    if len(s["nodes"]) > 12 or len(s["links"]) > 8:
        error("$.site", "conservative_size_limit", "At most 12 nodes and 8 channels (2048 refined cells).")
    nodes = {n["id"]: n for n in s["nodes"]}
    params = {p["link_id"]: p for p in m["link_parameters"]}
    for link in snapshot["effective_links"]:
        if link["cross_section"]["shape"] != "open_rectangle":
            error("$.site.links." + link["id"], "unsupported_shape", "The conservative engine requires open_rectangle; no shape substitution.")
        if (link["inlet_invert_m"] != nodes[link["from_node"]]["invert_m"] or
                link["outlet_invert_m"] != nodes[link["to_node"]]["invert_m"]):
            error("$.site.links." + link["id"], "unsupported_offset", "End offsets must be exactly zero.")
        if any(params[link["id"]][k] != 0 for k in ("entrance_loss_coefficient", "exit_loss_coefficient", "average_loss_coefficient")):
            error("$.model.link_parameters." + link["id"], "unsupported_minor_losses", "Minor losses require an independently verified extension; all three coefficients must be zero.")
    valid_splits = isinstance(split_times, (list, tuple)) and len(split_times) <= 8
    if valid_splits:
        valid_splits = all(type(t) in (int, float) and math.isfinite(t) and 0 < t < r["duration_s"]
                           and t % m["numerics"]["report_step_s"] == 0 for t in split_times)
    if valid_splits:
        valid_splits = list(split_times) == sorted(set(split_times))
    if not valid_splits:
        error("$.split_times", "invalid_phase_boundaries", "Use at most eight strictly increasing interior times on the report grid.")
    report.update(valid=not errors, status="research_contract_valid" if not errors else "invalid_contract")
    if errors:
        return report, None, None
    network = {"nodes": {nid: {"invert_m": nodes[nid]["invert_m"], "maximum_stage_m": nodes[nid]["ground_m"],
                               "stage_area": [[p["stage_m"], p["area_m2"]] for p in curve]}
                         for nid, curve in snapshot["curves"].items()},
               "channels": [{**{k: l[k] for k in ("id", "from_node", "to_node", "length_m", "inlet_invert_m", "outlet_invert_m")},
                             "width_m": l["cross_section"]["width_m"], "height_m": l["cross_section"]["height_m"],
                             "roughness_n": params[l["id"]]["roughness_n"]} for l in snapshot["effective_links"]],
               "inflows": {row["node_id"]: [[p["elapsed_s"], p["value_m3_s"]] for p in row["points"]] for row in r["inflows"]},
               "boundaries": {row["node_id"]: [[p["elapsed_s"], p["stage_m"]] for p in row["points"]] for row in r["receiving_stages"]},
               "duration_s": r["duration_s"], "report_step_s": m["numerics"]["report_step_s"]}
    return report, snapshot, network


def validate_conservative_run(site, model, run, *, split_times=(50.,)):
    return _contract(site, model, run, split_times)[0]


def build_conservative_network(site, model, run, *, split_times=(50.,)):
    report, _, network = _contract(site, model, run, split_times)
    if not report["valid"]:
        raise ValueError(canonical_json(report["errors"]))
    return network


def qualification_settings(model):
    step = model["numerics"]["routing_step_s"]
    return {label: {"cells_per_channel": cells, "max_step_s": step * factor, "cfl": cfl,
                    "spatial_order": 2, "maximum_steps": MAXIMUM_STEPS}
            for label, cells, cfl, factor in (("primary", 128, .4, 1), ("temporal", 128, .2, .5), ("spatial", 256, .4, 1))}


def _integral(points, start, end):
    total = 0.
    for (a, x), (b, y) in zip(points, points[1:]):
        lo, hi = max(start, a), min(end, b)
        if hi > lo:
            v0, v1 = x + (y-x)*(lo-a)/(b-a), x + (y-x)*(hi-a)/(b-a)
            total += (hi-lo)*(v0+v1)/2
    return total


def _storage_stage(curve, volume):
    """Invert the declared piecewise-linear area integral without solver state."""
    remaining=volume
    for (z0,a0),(z1,a1) in zip(curve,curve[1:]):
        capacity=(z1-z0)*(a0+a1)/2
        if remaining <= capacity:
            slope=(a1-a0)/(z1-z0)
            rise=remaining/a0 if slope == 0 else 2*remaining/(a0+math.sqrt(a0*a0+2*slope*remaining))
            return z0+rise
        remaining -= capacity
    if remaining > 1e-12:
        raise ValueError("Retained compartment water exceeds the declared spill elevation.")
    return curve[-1][0]


def audit_conservative_trace(network, settings, split_times, rows):
    """Recompute whole/phase and individual compartment/channel budgets.

    Reads actual applied interval volumes, never trapezoids point reports or
    reconstructs a missing boundary flux from the desired mass residual.
    """
    nodes = set(network["nodes"])
    links = {l["id"]: l for l in network["channels"]}
    outfalls = set(network["boundaries"])
    cuts = [0., *map(float, split_times), float(network["duration_s"])]
    result = {"valid": False, "rule": "every_endpoint_max_1mL_or_1percent_initial_plus_gross_entered/1",
              "endpoint_count": 0, "violations": 0, "errors": [], "maximum_absolute_residual_m3": 0.,
              "maximum_component_residual_m3": 0., "maximum_forcing_error_m3": 0., "maximum_cfl": 0., "phases": [],
              "spill_by_node_m3":dict.fromkeys(nodes,0.),"discharge_by_outfall_m3":dict.fromkeys(outfalls,0.),
              "backflow_by_outfall_m3":dict.fromkeys(outfalls,0.),"report_states":[],"maximum_stage_m":{}}
    previous = None
    totals = dict(external=0., backflow=0., discharge=0., spill=0.)
    start_totals = totals.copy()
    initial = None
    phase_start = 0.
    phase_stock = 0.
    phase_worst = 0.
    phase_bad = 0
    phase_index = 1
    def fail(message):
        result["violations"] += 1
        if len(result["errors"]) < 20:
            result["errors"].append(message)
    def mapping(row, key, expected, signed=False):
        value = row.get(key)
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError("Incomplete trace inventory: " + key)
        if any(type(v) not in (int, float) or not math.isfinite(v) or (not signed and v < 0) for v in value.values()):
            raise ValueError("Nonfinite or inadmissible trace value: " + key)
        return value
    try:
        for row in rows:
            t, dt, stock = row["elapsed_s"], row["dt_s"], row["storage_m3"]
            if any(type(v) not in (int,float) or not math.isfinite(v) for v in (t,dt,stock)) or stock < 0:
                raise ValueError("Nonfinite/negative state in routing trace.")
            ns = mapping(row, "node_storage_m3", nodes)
            ls = mapping(row, "link_storage_m3", set(links))
            stages={nid:_storage_stage(network["nodes"][nid]["stage_area"],v) for nid,v in ns.items()
                    if "stage_area" in network["nodes"][nid]}
            for nid,z in stages.items():
                result["maximum_stage_m"][nid]=max(result["maximum_stage_m"].get(nid,z),z)
            if abs(stock - sum(ns.values()) - sum(ls.values())) > 1e-12:
                fail("Total storage does not include exactly every channel and compartment.")
            if previous is None:
                if t != 0 or dt != 0 or stock != 0:
                    raise ValueError("Supplied-data runs must begin at exactly zero time with exactly zero water.")
                previous, initial, phase_stock = row, stock, stock
                result["report_states"].append({"elapsed_s":t,"storage_m3":stock,"node_storage_m3":ns,"link_storage_m3":ls,"internal_stage_m":stages})
                continue
            if dt <= 0 or abs(t - previous["elapsed_s"] - dt) > 1e-9 or dt > settings["max_step_s"] * (1+1e-9):
                raise ValueError("Routing history is not contiguous or violates its fixed step cap.")
            if t > network["duration_s"]+1e-9:
                raise ValueError("Routing history exceeds the declared horizon.")
            cfl = row["maximum_cfl"]
            if type(cfl) not in (float,int) or not math.isfinite(cfl) or cfl < 0 or cfl > settings["cfl"]*(1+1e-8):
                fail("Actual routing CFL exceeds the predeclared limit.")
            result["maximum_cfl"] = max(result["maximum_cfl"], cfl)
            ext = mapping(row, "interval_external_by_node_m3", nodes)
            back = mapping(row, "interval_receiving_by_boundary_m3", outfalls)
            discharge = mapping(row, "interval_discharge_by_boundary_m3", outfalls)
            spill = mapping(row, "interval_spill_by_node_m3", nodes)
            up = mapping(row, "interval_channel_upstream_m3", set(links), True)
            down = mapping(row, "interval_channel_downstream_m3", set(links), True)
            stage1=mapping(row,"boundary_exchange_stage_1_m3",outfalls,True)
            stage2=mapping(row,"boundary_exchange_stage_2_m3",outfalls,True)
            for oid in outfalls:
                if (abs(back[oid]-max(-stage1[oid],0)-max(-stage2[oid],0)) > 1e-14 or
                        abs(discharge[oid]-max(stage1[oid],0)-max(stage2[oid],0)) > 1e-14):
                    fail("Gross receiving exchange must split the actual weighted stage transfers before summing.")
            for name,values in (("external_inflow",ext),("receiving_backflow",back),("discharge",discharge),("spill",spill)):
                scalar=row["interval_"+name+"_m3"]
                if type(scalar) not in (float,int) or not math.isfinite(scalar) or abs(scalar-sum(values.values())) > 1e-12:
                    fail("Scalar interval total differs from the complete location ledger.")
            for nid, value in ext.items():
                difference = abs(value - _integral(network["inflows"].get(nid,[]), previous["elapsed_s"], t))
                result["maximum_forcing_error_m3"] = max(result["maximum_forcing_error_m3"], difference)
                if difference > 1e-12:
                    fail("Applied external forcing differs from its prescribed piecewise-linear integral.")
            for lid, link in links.items():
                residual = ls[lid] - previous["link_storage_m3"][lid] - up[lid] + down[lid]
                result["maximum_component_residual_m3"] = max(result["maximum_component_residual_m3"], abs(residual))
                if abs(residual) > 1e-10:
                    fail("Channel mass transfer does not match its retained water change.")
                if link["to_node"] in outfalls:
                    oid = link["to_node"]
                    if abs(down[lid] - discharge[oid] + back[oid]) > 1e-12:
                        fail("Receiving boundary gross ledger does not equal the actual channel transfer.")
            for nid in nodes:
                entered = ext.get(nid,0.) + sum(down[lid] for lid,l in links.items() if l["to_node"] == nid)
                left = spill[nid] + sum(up[lid] for lid,l in links.items() if l["from_node"] == nid)
                residual = ns[nid] - previous["node_storage_m3"][nid] - entered + left
                result["maximum_component_residual_m3"] = max(result["maximum_component_residual_m3"], abs(residual))
                if abs(residual) > 1e-10:
                    fail("Compartment mass transfer does not match its retained water change.")
            for name, values in (("external",ext),("backflow",back),("discharge",discharge),("spill",spill)):
                totals[name] += sum(values.values())
            for key, values in (("spill_by_node_m3",spill),("discharge_by_outfall_m3",discharge),("backflow_by_outfall_m3",back)):
                for location,v in values.items():
                    result[key][location] += v
            if t % network.get("report_step_s",1) == 0:
                result["report_states"].append({"elapsed_s":t,"storage_m3":stock,"node_storage_m3":ns,"link_storage_m3":ls,"internal_stage_m":stages})
            residual = initial + totals["external"] + totals["backflow"] - totals["discharge"] - totals["spill"] - stock
            tolerance = max(1e-6, .01*(initial+totals["external"]+totals["backflow"]))
            result["maximum_absolute_residual_m3"] = max(result["maximum_absolute_residual_m3"],abs(residual))
            if abs(residual) > tolerance:
                fail("Cumulative water balance exceeded the unchanged 1mL/1% limit.")
            phase = {k: totals[k]-start_totals[k] for k in totals}
            pres = phase_stock+phase["external"]+phase["backflow"]-phase["discharge"]-phase["spill"]-stock
            ptol = max(1e-6,.01*(phase_stock+phase["external"]+phase["backflow"]))
            phase_worst = max(phase_worst,abs(pres))
            if abs(pres) > ptol:
                phase_bad += 1
                fail("Phase water balance exceeded the unchanged 1mL/1% limit.")
            if phase_index < len(cuts) and t > cuts[phase_index]+1e-9:
                raise ValueError("Missing exact phase boundary; no interpolation or reset is allowed.")
            if phase_index < len(cuts) and abs(t-cuts[phase_index]) < 1e-9:
                result["phases"].append({"start_s":phase_start,"end_s":t,"initial_storage_m3":phase_stock,"final_storage_m3":stock,
                    **{k+"_m3":v for k,v in phase.items()},"residual_m3":pres,"maximum_absolute_residual_m3":phase_worst,"violations":phase_bad})
                phase_start, phase_stock, start_totals, phase_worst, phase_bad = t,stock,totals.copy(),0.,0
                phase_index += 1
            result["endpoint_count"] += 1
            if result["endpoint_count"] > settings["maximum_steps"]:
                raise ValueError("Step budget exceeded.")
            previous = row
        if previous is None or abs(previous["elapsed_s"] - network["duration_s"]) > 1e-9 or len(result["phases"]) != len(cuts)-1:
            raise ValueError("Incomplete routing history or phase inventory.")
        result.update(initial_storage_m3=initial,final_storage_m3=previous["storage_m3"],
                      totals_m3=totals,valid=result["violations"] == 0)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        fail(str(exc))
    return result


def _trace_rows(path):
    # Streaming keeps the full per-step audit available without duplicating it
    # into every summary; the worker itself also has a fixed 300000-step cap.
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def _qualify_attempt(folder, request):
    result = parse_json((folder / "worker-result.json").read_bytes())
    audit = audit_conservative_trace(request["network"], request["settings"], request["split_times"],
                                     _trace_rows(folder / "routing.jsonl.gz"))
    expected = [float(t) for t in range(0, int(request["network"]["duration_s"])+1, int(request["network"]["report_step_s"]))]
    times = [r.get("elapsed_s") for r in result.get("timeseries",[])]
    errors = list(result.get("errors",[]))
    if result.get("engine_identity") != request["engine_identity"] or result.get("request_sha256") != content_sha256(request):
        errors.append({"code":"worker_identity", "message":"Worker/source/input identity mismatch."})
    if times != expected:
        errors.append({"code":"report_grid", "message":"Exact complete report grid required; no interpolation or dropped records."})
    stocks=("elapsed_s","storage_m3","node_storage_m3","link_storage_m3")
    if [{k:row.get(k) for k in stocks} for row in result.get("timeseries",[])] != [{k:row[k] for k in stocks} for row in audit["report_states"]]:
        errors.append({"code":"report_state_binding","message":"Reported water states differ from exact routing endpoints."})
    if len(result.get("timeseries",[])) == len(audit["report_states"]):
        for row, audited in zip(result["timeseries"],audit["report_states"]):
            if any(abs(row["stage_m"].get(nid,1e100)-z) > 1e-12 for nid,z in audited["internal_stage_m"].items()):
                errors.append({"code":"reported_stage_binding","message":"Reported internal stage differs from the declared compartment water."})
                break
    for key in ("spill_by_node_m3","discharge_by_outfall_m3","backflow_by_outfall_m3"):
        supplied=result.get("diagnostics",{}).get(key,{})
        if set(supplied) != set(audit[key]) or any(abs(supplied[n]-v) > 1e-12 for n,v in audit[key].items()):
            errors.append({"code":"diagnostic_ledger_binding","message":"Diagnostic location totals differ from actual applied transfers: "+key})
    if result.get("valid"):
        peaks={**audit["maximum_stage_m"],**{k:max(p[1] for p in points) for k,points in request["network"]["boundaries"].items()}}
        actual_peaks=result.get("diagnostics",{}).get("maximum_stage_m",{})
        if set(peaks) != set(actual_peaks) or any(abs(actual_peaks[n]-z)>1e-12 for n,z in peaks.items()):
            errors.append({"code":"peak_stage_binding","message":"Peak stage diagnostics differ from complete water states and boundary history."})
        phases=dict(result.get("phase_balances",{}))
        whole={"start_s":0.,"end_s":request["network"]["duration_s"],"initial_storage_m3":audit.get("initial_storage_m3"),
               "final_storage_m3":audit.get("final_storage_m3"),**{k+"_m3":v for k,v in audit.get("totals_m3",{}).items()}}
        expected_phases={"whole":whole,**{"phase_"+str(i+1):p for i,p in enumerate(audit["phases"])}}
        if set(phases) != set(expected_phases):
            errors.append({"code":"phase_inventory","message":"Whole-run and consecutive phase records are incomplete."})
        else:
            for key,p in expected_phases.items():
                for name in ("start_s","end_s","initial_storage_m3","final_storage_m3","external_m3","backflow_m3","discharge_m3","spill_m3"):
                    target={"external_m3":"external_inflow_m3","backflow_m3":"receiving_backflow_m3"}.get(name,name)
                    if p.get(name) is None or abs(phases[key].get(target,1e100)-p[name]) > 1e-12:
                        errors.append({"code":"phase_ledger_binding","message":"Phase summary differs from independently accumulated applied transfers: "+key+"/"+target})
                residual=p["initial_storage_m3"]+p["external_m3"]+p["backflow_m3"]-p["discharge_m3"]-p["spill_m3"]-p["final_storage_m3"]
                tolerance=max(1e-6,.01*(p["initial_storage_m3"]+p["external_m3"]+p["backflow_m3"]))
                if abs(phases[key].get("residual_m3",1e100)-residual)>1e-12 or not math.isclose(phases[key].get("tolerance_m3",1e100),tolerance,rel_tol=1e-12,abs_tol=1e-18) or phases[key].get("passed") != (abs(residual)<=tolerance):
                    errors.append({"code":"phase_decision_binding","message":"Phase decision or numerical limit differs from independent recomputation: "+key})
        if not audit["valid"]:
            result["valid"]=False
        final=result.get("final_state",{})
        if final.get("elapsed_s") != request["network"]["duration_s"]:
            errors.append({"code":"final_clock","message":"Final state does not reach the complete declared horizon."})
        final_channels=final.get("channels",{})
        final_nodes=final.get("nodes",{})
        if set(final_channels) != {l["id"] for l in request["network"]["channels"]} or set(final_nodes) != set(request["network"]["nodes"]):
            errors.append({"code":"final_inventory","message":"Final cells and compartments are incomplete."})
        else:
            last=audit["report_states"][-1]
            for nid,node in final_nodes.items():
                if (abs(node["volume_m3"]-last["node_storage_m3"][nid])>1e-12 or
                        abs(node["stage_m"]-last["internal_stage_m"][nid])>1e-12):
                    errors.append({"code":"final_compartment","message":"Final compartment volume or stage differs from its routing endpoint: "+nid})
            total=math.fsum(n["volume_m3"] for n in final_nodes.values())
            for link in request["network"]["channels"]:
                cells=final_channels[link["id"]]
                depths=cells["depth_m"]
                count=request["settings"]["cells_per_channel"]
                if len(depths) != count or any(type(d) not in (int,float) or d < 0 or d>link["height_m"]*(1+32*sys.float_info.epsilon) or not math.isfinite(d) for d in depths):
                    errors.append({"code":"final_cell_state","message":"Final cell inventory or depth is invalid."})
                expected_dx=link["length_m"]/count
                expected_x=[(i+.5)*expected_dx for i in range(count)]
                expected_z=[link["inlet_invert_m"]+(link["outlet_invert_m"]-link["inlet_invert_m"])*x/link["length_m"] for x in expected_x]
                q=cells.get("unit_discharge_m2_s",[])
                if len(q)!=count or any(type(v) not in (int,float) or not math.isfinite(v) for v in q):
                    errors.append({"code":"final_momentum_inventory","message":"Final discharge array is incomplete or nonfinite."})
                if (cells.get("dx_m") != expected_dx or len(cells.get("x_m",[]))!=count or len(cells.get("bed_m",[]))!=count or
                        any(abs(x-y)>1e-12 for x,y in zip(cells.get("x_m",[]),expected_x)) or
                        any(abs(x-y)>1e-12 for x,y in zip(cells.get("bed_m",[]),expected_z))):
                    errors.append({"code":"final_grid","message":"Final cells do not represent the declared channel geometry."})
                volume=math.fsum(depths)*link["width_m"]*expected_dx
                if abs(volume-last["link_storage_m3"][link["id"]])>1e-12:
                    errors.append({"code":"final_channel_water","message":"Final channel cell water differs from its routing endpoint: "+link["id"]})
                total += volume
            if abs(total-audit.get("final_storage_m3",-1)) > 1e-12:
                errors.append({"code":"final_volume","message":"Final cell/compartment water does not equal the retained ledger."})
        diagnostic=result.get("diagnostics",{})
        expected_diagnostics={"step_count":audit["endpoint_count"],"cells_per_channel":request["settings"]["cells_per_channel"],
                              "max_step_s":request["settings"]["max_step_s"],"requested_cfl":request["settings"]["cfl"],
                              "maximum_steps":request["settings"]["maximum_steps"],"spatial_order":2,
                              "completed_duration_s":request["network"]["duration_s"],"initialization":"exact_dry_zero_flow"}
        if any(diagnostic.get(k)!=v for k,v in expected_diagnostics.items()):
            errors.append({"code":"diagnostic_settings","message":"Worker diagnostics do not match the declared actual execution."})
    if not audit["valid"]:
        errors.append({"code":"independent_transfer_audit", "message":"Applied water transfer audit failed; complete trace retained."})
    result.update(valid=result.get("valid") is True and not errors, errors=errors, transfer_audit=audit)
    result["status"] = "numerically_qualified_attempt" if result["valid"] else "numerically_unresolved"
    return result


def _run_attempt(folder, request):
    folder.mkdir()
    _write(folder / "request.json", request)
    try:
        exit_code = run_bounded_worker([sys.executable, str(Path(__file__).with_name("_bench_conservative_worker.py")), str(folder)],
                                      cwd=folder, timeout=WORKER_TIMEOUT_S, log_path=folder / "worker.log")
        if exit_code != 0:
            raise ValueError(f"Conservative worker exited {exit_code}; inspect retained log.")
        result = _qualify_attempt(folder, request)
    except Exception as exc:
        with (folder / "worker.log").open("a",encoding="utf-8") as log:
            log.write(f"\nAdapter failure: {type(exc).__name__}: {exc}\n")
        result = {"valid":False,"status":"worker_failed","errors":[{"code":"conservative_worker", "message":f"{type(exc).__name__}: {exc}"}],
                  "timeseries":[],"diagnostics":{},"transfer_audit":{"valid":False,"errors":["Worker did not produce complete auditable history."]}}
    _write(folder / "audit.json", result["transfer_audit"])
    return result


def _assemble(report, snapshot, identity, attempts):
    # JSON object ordering is immaterial. Error arrays, however, must retain
    # the declared execution order when a saved failed attempt is reloaded.
    attempts = {label: attempts[label] for label in ("primary", "temporal", "spatial")}
    checks = {"temporal":bench_model._step_comparison(attempts["primary"],attempts["temporal"],snapshot["site"]),
              "spatial":bench_model._step_comparison(attempts["primary"],attempts["spatial"],snapshot["site"])}
    qualified = all(a["valid"] for a in attempts.values()) and all(c["passed"] for c in checks.values())
    errors = [{"attempt":label,**e} if isinstance(e,dict) else {"attempt":label,"message":str(e)}
              for label,a in attempts.items() for e in a["errors"]]
    for label, check in checks.items():
        if not check["passed"]:
            errors.append({"code":label+"_convergence_unresolved","message":"Unchanged 2%/absolute convergence check did not pass."})
    return {**report, "valid":qualified,"status":"numerically_qualified" if qualified else "numerically_unresolved",
            "errors":errors,"engine_identity":identity,"timeseries":attempts["primary"]["timeseries"],
            "diagnostics":attempts["primary"].get("diagnostics",{}),"convergence":checks,
            "attempts":{label:{k:v for k,v in a.items() if k not in ("timeseries","final_state","routing_trace","engine_identity")}
                        for label,a in attempts.items()}, **CLAIMS}


def run_conservative_bench(site, model, run, output_dir, *, split_times=(50.,)):
    """Retain a fixed primary/time/space triple; never refine until a pass."""
    report, snapshot, network = _contract(site,model,run,split_times)
    if not report["valid"]:
        return {**report,"files":{},"timeseries":[],"attempts":{}}
    identity = conservative_identity()
    settings = qualification_settings(snapshot["model"])
    request = {"schema_version":SCHEMA,"site":snapshot["site"],"model":snapshot["model"],"run":snapshot["run"],
               "network":network,"settings":settings,"split_times":list(split_times),"engine_identity":identity,
               "worker_timeout_s":WORKER_TIMEOUT_S}
    root = Path(output_dir).resolve()
    root.mkdir(parents=True,exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="conservative-bench-",dir=root))
    _write(folder / "request.json",request)
    attempts = {}
    for label, setting in settings.items():
        child = {"network":network,"settings":setting,"split_times":list(split_times),"engine_identity":identity,
                 "parent_request_sha256":content_sha256(request),"attempt":label}
        attempts[label] = _run_attempt(folder / label,child)
    result = _assemble(report,snapshot,identity,attempts)
    try:
        if conservative_identity() != identity:
            raise ValueError("Engine identity changed across verification triple.")
    except Exception as exc:
        result.update(valid=False,status="numerically_unresolved")
        result["errors"].append({"code":"changed_identity","message":str(exc)})
    result["request_sha256"] = content_sha256(request)
    result["files"] = {p.relative_to(folder).as_posix():_hash(p) for p in folder.rglob("*") if p.is_file()}
    _write(folder / "result.json",result)
    _write(folder / "manifest.json",{"schema_version":"monsoon.conservative-evidence/1", "request_sha256":result["request_sha256"],
                                     "file_sha256":{p.relative_to(folder).as_posix():_hash(p) for p in folder.rglob("*") if p.is_file()}})
    return {**result,"artifact_directory":str(folder)}


def verify_conservative_result(value):
    """Verify portable local evidence and rederive every acceptance decision.

    This proves local byte consistency, not authenticity of a supplied survey.
    artifact_directory may be rebased after copying the entire evidence folder.
    """
    report = {"valid":False,"status":"integrity_unresolved","errors":[],**CLAIMS}
    try:
        value = parse_json(value)
        folder = Path(value["artifact_directory"]).resolve()
        stored = parse_json((folder / "result.json").read_bytes())
        if {k:v for k,v in value.items() if k != "artifact_directory"} != stored:
            raise ValueError("Returned result differs from its retained result.")
        actual = {}
        for p in folder.rglob("*"):
            if p.is_symlink() or not p.resolve().is_relative_to(folder):
                raise ValueError("Evidence may not contain links or escaping paths.")
            if p.is_file():
                actual[p.relative_to(folder).as_posix()] = p
        manifest = parse_json((folder / "manifest.json").read_bytes())
        if manifest.get("schema_version") != "monsoon.conservative-evidence/1":
            raise ValueError("Unexpected evidence schema.")
        hashes = manifest["file_sha256"]
        if set(hashes) != set(actual)-{"manifest.json"} or any(_hash(actual[n]) != h for n,h in hashes.items()):
            raise ValueError("Missing, extra or changed evidence file.")
        if stored["files"] != {n:h for n,h in hashes.items() if n != "result.json"}:
            raise ValueError("Incomplete result artifact inventory.")
        request = parse_json((folder / "request.json").read_bytes())
        if content_sha256(request) != stored["request_sha256"] or manifest["request_sha256"] != stored["request_sha256"]:
            raise ValueError("Request fingerprint changed.")
        contract, snapshot, network = _contract(request["site"],request["model"],request["run"],request["split_times"])
        if not contract["valid"] or request["network"] != network or request["settings"] != qualification_settings(snapshot["model"]):
            raise ValueError("Retained input contract or fixed qualification settings differ.")
        identity = conservative_identity()
        if request["engine_identity"] != identity or stored["engine_identity"] != identity or request["worker_timeout_s"] != WORKER_TIMEOUT_S:
            raise ValueError("Retained engine/runtime differs from the currently loaded verified source.")
        attempts = {}
        for label,setting in qualification_settings(snapshot["model"]).items():
            child = parse_json((folder / label / "request.json").read_bytes())
            expected = {"network":network,"settings":setting,"split_times":request["split_times"],"engine_identity":identity,
                        "parent_request_sha256":content_sha256(request),"attempt":label}
            if child != expected:
                raise ValueError("Child request is not the declared fixed triple.")
            if stored["attempts"][label].get("status") == "worker_failed":
                if stored["valid"] or stored["attempts"][label].get("valid"):
                    raise ValueError("A failed worker cannot be qualified.")
                attempts[label] = {**stored["attempts"][label],"timeseries":[]}
            else:
                attempts[label] = _qualify_attempt(folder / label,child)
            if attempts[label]["transfer_audit"] != parse_json((folder / label / "audit.json").read_bytes()):
                raise ValueError("Retained audit differs from independently recomputed history.")
        rebuilt = _assemble(contract,snapshot,identity,attempts)
        for key in rebuilt:
            if rebuilt[key] != stored[key]:
                raise ValueError("Retained qualification decision differs from recomputation: " + key)
        report.update(valid=True,status="local_integrity_and_decisions_verified",numerical_qualification=stored["valid"])
    except Exception as exc:
        report["errors"] = [{"code":"artifact_integrity","message":f"{type(exc).__name__}: {exc}"}]
    return report
