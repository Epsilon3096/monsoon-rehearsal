"""Private one-engine-per-process entry point for the isolated bench adapter."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import traceback

from swmm.toolkit import solver
from swmm.toolkit.shared_enum import LinkResult, NodeResult

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _signed_integral(q0, q1, dt):
    """Positive/negative volumes of the piecewise-linear signed endpoint flow."""
    if q0 * q1 < 0:
        first = dt * abs(q0) / (abs(q0) + abs(q1))
        a, b = abs(q0) * first / 2, abs(q1) * (dt - first) / 2
        return (a, b) if q0 > 0 else (b, a)
    return dt * (max(q0, 0) + max(q1, 0)) / 2, dt * (max(-q0, 0) + max(-q1, 0)) / 2


def run(folder):
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    site, model, spec = (request[k] for k in ("site", "model", "run"))
    nodes = {n["id"]: n for n in site["nodes"]}
    links = {l["id"]: l for l in request["effective_links"]}
    internal = sorted(n for n in nodes if nodes[n]["kind"] != "outfall")
    outfalls = sorted(set(nodes) - set(internal))
    inflows = site["boundaries"]["inflow_node_ids"]
    result = {"status": "failed", "valid": False, "timeseries": [], "diagnostics": {}, "errors": [],
              "column_roles": {"prescribed_inputs": {"prescribed_inflow_m3_s": inflows, "receiving_stage_m": outfalls},
                               "engine_applied_inputs": {"inflow_m3_s": inflows},
                               "boundary_response_not_validation_target": {"stage_m": outfalls},
                               "model_responses": {"stage_m": internal, "outflow_m3_s": outfalls, "spill_m3_s": internal, "storage_m3": ["SYSTEM"]}},
              "operational_activation_allowed": False, "physical_validation_established": False}
    opened = started = False
    try:
        engine = request["fingerprint"]["engine"]
        expected = request["fingerprint"]["engine"]["source_sha256"]
        for name, digest in expected.items():
            if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest:
                raise ValueError("Adapter source changed between parent validation and worker execution: " + name)
        if expected["_bench_worker.py"] != _LOADED_SOURCE_SHA256:
            raise ValueError("Loaded worker does not match requested source fingerprint.")
        dist = importlib.metadata.distribution("swmm-toolkit")
        if solver.swmm_get_version() != engine["engine_version_int"] or dist.version != engine["toolkit_version"]:
            raise ValueError("Loaded engine version differs from the request.")
        for name, digest in engine["runtime_file_sha256"].items():
            if hashlib.sha256(Path(dist.locate_file(name)).read_bytes()).hexdigest() != digest:
                raise ValueError("Engine runtime bytes changed before worker execution.")
        if hashlib.sha256((folder / "model.inp").read_bytes()).hexdigest() != request["fingerprint"]["input_sha256"]:
            raise ValueError("SWMM input differs from the validated fingerprint.")
        for key, field in (("site", "site_sha256"), ("model", "model_sha256"), ("run", "run_sha256")):
            digest = hashlib.sha256(json.dumps(request[key], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
            if digest != request["fingerprint"][field]:
                raise ValueError("Request snapshot hash mismatch: " + key)
        derived = {"curves": request["curves"], "effective_links": request["effective_links"]}
        digest = hashlib.sha256(json.dumps(derived, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        if digest != request["fingerprint"]["derived_geometry_sha256"]:
            raise ValueError("Derived worker geometry differs from the validated fingerprint.")
        solver.swmm_open(str(folder / "model.inp"), str(folder / "model.rpt"), str(folder / "model.out"))
        opened = True
        solver.swmm_start(True)
        started = True
        ni = {k: solver.project_get_index(solver.swmm_NODE, k) for k in nodes}
        li = {k: solver.project_get_index(solver.swmm_LINK, k) for k in links}

        def nr(nid, code):
            value = solver.node_get_result(ni[nid], code.value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite node result: " + nid)
            return value

        def lr(lid, code):
            value = solver.link_get_result(li[lid], code.value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite link result: " + lid)
            return value

        def sample(t):
            def prescribed(collection, field):
                values = {}
                for row in spec[collection]:
                    for a, b in zip(row["points"], row["points"][1:]):
                        if a["elapsed_s"] - 1e-6 <= t <= b["elapsed_s"] + 1e-6:
                            fraction = min(1.0, max(0.0, (t - a["elapsed_s"]) / (b["elapsed_s"] - a["elapsed_s"])))
                            values[row["node_id"]] = a[field] + fraction * (b[field] - a[field])
                            break
                return values
            nv = {k: nr(k, NodeResult.VOLUME) for k in nodes}
            lv = {k: lr(k, LinkResult.VOLUME) for k in links}
            exchange = {}
            for oid in outfalls:
                outgoing = nr(oid, NodeResult.TOTAL_OUTFLOW)
                # node_getSystemOutflow makes inflow positive during backflow;
                # subtracting the two getters would therefore incorrectly give zero.
                exchange[oid] = -outgoing if outgoing > 0 else nr(oid, NodeResult.TOTAL_INFLOW)
            return {"elapsed_s": t, "stage_m": {k: nr(k, NodeResult.HEAD) for k in nodes},
                    "link_flow_m3_s": {k: lr(k, LinkResult.FLOW) for k in links},
                    "link_depth_m": {k: lr(k, LinkResult.DEPTH) for k in links},
                    "node_storage_m3": nv, "link_storage_m3": lv, "storage_m3": sum(nv.values()) + sum(lv.values()),
                    "inflow_m3_s": {k: nr(k, NodeResult.LATERAL_INFLOW) for k in inflows},
                    "prescribed_inflow_m3_s": prescribed("inflows", "value_m3_s"),
                    "receiving_stage_m": prescribed("receiving_stages", "stage_m"),
                    "outflow_m3_s": exchange, "spill_m3_s": {k: nr(k, NodeResult.FLOOD) for k in internal}}

        first = previous = sample(0.0)
        result["timeseries"].append(first)
        discharge, reverse, spill = ({k: 0.0 for k in ids} for ids in (outfalls, outfalls, internal))
        external = {k: 0.0 for k in inflows}
        maximum_stage = dict(first["stage_m"])
        maximum_link_depth = dict(first["link_depth_m"])
        overtopped = set()
        expected_dt, report_step, horizon = model["numerics"]["routing_step_s"], model["numerics"]["report_step_s"], spec["duration_s"]
        next_report, steps, min_dt, max_dt = report_step, 0, math.inf, 0.0
        while True:
            elapsed_days = solver.swmm_step()
            # EPA's API returns decimal DAYS; a successful final step returns zero.
            # With fixed routing and an aligned horizon, zero means this final endpoint.
            t = elapsed_days * 86400 if elapsed_days > 0 else float(horizon)
            dt = t - previous["elapsed_s"]
            if dt <= 0 or dt > expected_dt + 1e-6 or t > horizon + 1e-6:
                raise ValueError("Engine timestep/endpoint does not match the declared fixed grid.")
            steps += 1
            if steps > 100001:
                raise ValueError("Routing step budget exceeded.")
            min_dt, max_dt = min(min_dt, dt), max(max_dt, dt)
            current = sample(t)
            for nid in nodes:
                maximum_stage[nid] = max(maximum_stage[nid], current["stage_m"][nid])
            for lid, link in links.items():
                maximum_link_depth[lid] = max(maximum_link_depth[lid], current["link_depth_m"][lid])
                x = link["cross_section"]
                if x["shape"] != "circular":
                    top = x["height_m"]
                    tol = model["numerics"]["head_tolerance_m"]
                    if (current["link_depth_m"][lid] > top + tol or
                            current["stage_m"][link["from_node"]] > link["inlet_invert_m"] + top + tol or
                            current["stage_m"][link["to_node"]] > link["outlet_invert_m"] + top + tol):
                        overtopped.add(lid)
            for nid in inflows:
                external[nid] += dt * (previous["inflow_m3_s"][nid] + current["inflow_m3_s"][nid]) / 2
            for oid in outfalls:
                positive, negative = _signed_integral(previous["outflow_m3_s"][oid], current["outflow_m3_s"][oid], dt)
                discharge[oid] += positive
                reverse[oid] += negative
            for nid in internal:
                spill[nid] += dt * (previous["spill_m3_s"][nid] + current["spill_m3_s"][nid]) / 2
            if t >= next_report - 1e-6:
                if not math.isclose(t, next_report, abs_tol=1e-6):
                    raise ValueError("Report grid not reached exactly; no interpolation of model results is permitted.")
                current["elapsed_s"] = float(next_report)
                result["timeseries"].append(current)
                next_report += report_step
            previous = current
            if elapsed_days <= 0:
                break
        totals = solver.system_get_routing_totals()
        raw = {k: getattr(totals, k) for k in ("dwInflow", "wwInflow", "gwInflow", "iiInflow", "exInflow", "flooding", "outflow", "evapLoss", "seepLoss", "initStorage", "finalStorage", "pctError")}
        if any(not math.isfinite(v) for v in raw.values()):
            raise ValueError("Nonfinite routing totals.")
        nonconverged = {nid: solver.node_get_stats(ni[nid]).nonConvergedCount for nid in internal}
        solver.swmm_end()
        started = False
        continuity = solver.swmm_get_mass_balance()[1]
        solver.swmm_report()
        solver.swmm_close()
        opened = False
        warnings = [line.strip() for line in (folder / "model.rpt").read_text(encoding="utf-8", errors="replace").splitlines() if "WARNING" in line or "ERROR" in line]
        prescribed = sum((b["elapsed_s"] - a["elapsed_s"]) * (a["value_m3_s"] + b["value_m3_s"]) / 2 for row in spec["inflows"] for a, b in zip(row["points"], row["points"][1:]))
        vin, back, vout, vspill = sum(external.values()), sum(reverse.values()), sum(discharge.values()), sum(spill.values())
        initial, final = first["storage_m3"], previous["storage_m3"]
        residual = initial + vin + back - vout - vspill - raw["evapLoss"] - raw["seepLoss"] - final
        tolerance = max(1e-6, 0.01 * (initial + vin + back))
        diagnostics = {"initial_storage_m3": initial, "final_storage_m3": final, "external_inflow_m3": vin,
                       "prescribed_inflow_m3": prescribed, "receiving_backflow_m3": back, "discharge_m3": vout,
                       "spill_m3": vspill, "spill_by_node_m3": spill, "discharge_by_outfall_m3": discharge, "backflow_by_outfall_m3": reverse,
                       "evaporation_m3": raw["evapLoss"], "seepage_m3": raw["seepLoss"], "mass_balance_residual_m3": residual,
                       "mass_balance_tolerance_m3": tolerance, "continuity_error_percent": continuity, "routing_steps": steps,
                       "minimum_actual_step_s": min_dt, "maximum_actual_step_s": max_dt, "final_elapsed_s": previous["elapsed_s"],
                       "maximum_stage_m": maximum_stage, "maximum_link_depth_m": maximum_link_depth,
                       "unsupported_open_link_overtopping": sorted(overtopped), "nonconverged_steps": nonconverged, "warnings": warnings,
                       "raw_routing_totals": raw, "raw_storage_units": "Raw routing initStorage/finalStorage are internal ft3 in the pinned toolkit; never used as m3. All reported storage comes from converted live node/link VOLUME getters.",
                       "balance_method": "Actual routing intervals; trapezoidal external/spill flows; exact positive/negative split of linearly interpolated signed outfall endpoint flow. Sampling and solver approximations remain.",
                       "numerical_qa_only": True}
        result["diagnostics"] = diagnostics
        problems = []
        diagnostics["initial_numerical_storage_tolerance_m3"] = model["numerics"]["initial_numerical_storage_tolerance_m3"]
        diagnostics["initial_state_note"] = "Nominally dry input; actual engine-initialized node/link water is retained at t=0 and included in the balance, including SWMM's small dry-link depth floor."
        if (initial > model["numerics"]["initial_numerical_storage_tolerance_m3"] or
                any(abs(q) > 1e-12 for q in first["link_flow_m3_s"].values()) or
                any(abs(v) > 1e-12 for v in first["node_storage_m3"].values())):
            problems.append(("initial_state", "Engine initialization exceeds the declared nominal-dry volume allowance or has nonzero node storage/link flow."))
        if len(result["timeseries"]) != horizon // report_step + 1:
            problems.append(("incomplete_grid", "Missing reporting endpoints."))
        if abs(residual) > tolerance:
            problems.append(("mass_balance", "Independent balance exceeds max(1 mL, 1% of initial storage plus entering water)."))
        if abs(continuity) > 1 and initial + vin + back > 1e-6:
            problems.append(("engine_continuity", "SWMM routing continuity exceeds 1%."))
        if abs(prescribed - vin) > max(1e-6, 0.01 * prescribed):
            problems.append(("forcing_integration", "Engine-applied inflow differs materially from the prescribed piecewise-linear integral."))
        if abs(raw["exInflow"] - vin - back) > tolerance or abs(raw["outflow"] - vout) > tolerance or abs(raw["flooding"] - vspill) > tolerance:
            problems.append(("routing_units_or_accounting", "Independently integrated SI exchange/spill does not reconcile with routing volume totals."))
        if any(nonconverged.values()):
            problems.append(("nonconvergence", "At least one routing step did not converge at an internal node."))
        if overtopped:
            problems.append(("unsupported_lateral_spill", "An open conduit reaches unrepresented lateral overtopping; node collectors do not account for this pathway."))
        if warnings:
            problems.append(("engine_warning", "SWMM reported a warning/error; review the retained report."))
        result.update(status="numerically_unresolved" if problems else "succeeded", valid=not problems,
                      errors=[{"path": "$.simulation", "code": code, "message": message} for code, message in problems])
    except Exception as exc:
        result["errors"].append({"path": "$.simulation", "code": "engine_failure", "message": f"{type(exc).__name__}: {exc}"})
        traceback.print_exc()
    finally:
        if started:
            try:
                solver.swmm_end()
            except Exception:
                pass
        if opened:
            try:
                solver.swmm_close()
            except Exception:
                pass
    (folder / "worker-result.json").write_text(json.dumps(result, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    run(Path(sys.argv[1]))
