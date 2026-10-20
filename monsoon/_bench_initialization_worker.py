"""Private worker for one continuous dry preparation plus event SWMM run."""
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
try:
    from . import _bench_worker as dry_worker
except ImportError:  # Direct worker invocation in its isolated child process.
    import _bench_worker as dry_worker

_signed_integral = dry_worker._signed_integral

_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _forcing_value(spec, collection, field, t):
    values = {}
    for row in spec[collection]:
        for a, b in zip(row["points"], row["points"][1:]):
            if a["elapsed_s"] - 1e-6 <= t <= b["elapsed_s"] + 1e-6:
                f = min(1.0, max(0.0, (t - a["elapsed_s"]) / (b["elapsed_s"] - a["elapsed_s"])))
                values[row["node_id"]] = a[field] + f * (b[field] - a[field])
                break
    return values


def _prescribed_volume(spec, start, end):
    total = 0.0
    for row in spec["inflows"]:
        for a, b in zip(row["points"], row["points"][1:]):
            left, right = max(start, a["elapsed_s"]), min(end, b["elapsed_s"])
            if right > left:
                slope = (b["value_m3_s"] - a["value_m3_s"]) / (b["elapsed_s"] - a["elapsed_s"])
                total += (right - left) * (2 * a["value_m3_s"] + slope * (left + right - 2 * a["elapsed_s"])) / 2
    return total


class _Ledger:
    def __init__(self, first):
        self.first = self.last = first
        self.external = {k: 0.0 for k in first["inflow_m3_s"]}
        self.discharge = {k: 0.0 for k in first["outflow_m3_s"]}
        self.backflow = dict(self.discharge)
        self.spill = {k: 0.0 for k in first["spill_m3_s"]}
        self.maximum_stage = dict(first["stage_m"])
        self.maximum_link_depth = dict(first["link_depth_m"])
        self.steps = 0
        self.cumulative = {"checked_endpoints": 1, "failed_endpoints": 0, "maximum_absolute_residual_m3": 0.0,
                           "maximum_residual_to_tolerance_ratio": 0.0, "worst_endpoint": None,
                           "first_failed_simulation_elapsed_s": None, "last_failed_simulation_elapsed_s": None}

    def add(self, previous, current):
        dt = current["elapsed_s"] - previous["elapsed_s"]
        if abs(self.last["elapsed_s"] - previous["elapsed_s"]) > 1e-6:
            raise ValueError("Discontinuous phase integration history.")
        for nid in self.external:
            self.external[nid] += dt * (previous["inflow_m3_s"][nid] + current["inflow_m3_s"][nid]) / 2
        for oid in self.discharge:
            positive, negative = _signed_integral(previous["outflow_m3_s"][oid], current["outflow_m3_s"][oid], dt)
            self.discharge[oid] += positive
            self.backflow[oid] += negative
        for nid in self.spill:
            self.spill[nid] += dt * (previous["spill_m3_s"][nid] + current["spill_m3_s"][nid]) / 2
        for nid in self.maximum_stage:
            self.maximum_stage[nid] = max(self.maximum_stage[nid], current["stage_m"][nid])
        for lid in self.maximum_link_depth:
            self.maximum_link_depth[lid] = max(self.maximum_link_depth[lid], current["link_depth_m"][lid])
        self.last = current
        self.steps += 1
        entering = self.first["storage_m3"] + sum(self.external.values()) + sum(self.backflow.values())
        residual = entering - sum(self.discharge.values()) - sum(self.spill.values()) - current["storage_m3"]
        tolerance = max(1e-6, 0.01 * entering)
        ratio = abs(residual) / tolerance
        audit = self.cumulative
        audit["checked_endpoints"] += 1
        audit["maximum_absolute_residual_m3"] = max(audit["maximum_absolute_residual_m3"], abs(residual))
        if audit["worst_endpoint"] is None or ratio > audit["maximum_residual_to_tolerance_ratio"]:
            audit["maximum_residual_to_tolerance_ratio"] = ratio
            audit["worst_endpoint"] = {"simulation_elapsed_s": current["elapsed_s"], "mass_balance_residual_m3": residual,
                                       "mass_balance_tolerance_m3": tolerance, "initial_plus_entering_water_m3": entering,
                                       "storage_m3": current["storage_m3"]}
        if ratio > 1:
            audit["failed_endpoints"] += 1
            if audit["first_failed_simulation_elapsed_s"] is None:
                audit["first_failed_simulation_elapsed_s"] = current["elapsed_s"]
            audit["last_failed_simulation_elapsed_s"] = current["elapsed_s"]

    def finish(self, spec):
        initial, final = self.first["storage_m3"], self.last["storage_m3"]
        vin, back = sum(self.external.values()), sum(self.backflow.values())
        out, spill = sum(self.discharge.values()), sum(self.spill.values())
        residual = initial + vin + back - out - spill - final
        tolerance = max(1e-6, 0.01 * (initial + vin + back))
        start, end = self.first["elapsed_s"], self.last["elapsed_s"]
        return {"start_simulation_elapsed_s": start, "end_simulation_elapsed_s": end, "duration_s": end - start,
                "initial_storage_m3": initial, "final_storage_m3": final,
                "external_inflow_m3": vin, "external_inflow_by_node_m3": self.external,
                "prescribed_inflow_m3": _prescribed_volume(spec, start, end),
                "receiving_backflow_m3": back, "discharge_m3": out, "spill_m3": spill,
                "signed_outfall_exchange_m3": out - back,
                "spill_by_node_m3": self.spill, "discharge_by_outfall_m3": self.discharge, "backflow_by_outfall_m3": self.backflow,
                "evaporation_m3": 0.0, "seepage_m3": 0.0, "leakage_m3": 0.0,
                "mass_balance_residual_m3": residual, "mass_balance_tolerance_m3": tolerance,
                "balance_passed": abs(residual) <= tolerance,
                "cumulative_balance_passed": self.cumulative["failed_endpoints"] == 0,
                "cumulative_balance_audit": self.cumulative, "routing_steps": self.steps,
                "maximum_stage_m": self.maximum_stage, "maximum_link_depth_m": self.maximum_link_depth,
                "balance_method": "Actual routing intervals, trapezoidal lateral/spill flows and signed outfall zero-crossing splits. The shared event boundary is a state, not a second volume input.",
                "loss_assumption": "Explicit excluded_zero model declaration; engine zero evaporation/seepage totals are checked for the whole history.",
                "numerical_qa_only": True}


class _Stationarity:
    def __init__(self, recipe, event):
        self.recipe = recipe
        self.event = event
        self.start = event - recipe.get("window_s", 0)
        self.ranges = {}
        self.count = 0
        self.first = self.last = None

    def add(self, row):
        if self.recipe["kind"] != "required_constant_forcing" or not self.start - 1e-6 <= row["elapsed_s"] <= self.event + 1e-6:
            return
        if self.first is None:
            self.first = row["elapsed_s"]
        self.last = row["elapsed_s"]
        self.count += 1
        fields = ("stage_m", "node_depth_m", "link_depth_m", "node_storage_m3", "link_storage_m3",
                  "link_flow_m3_s", "node_total_inflow_m3_s", "node_total_outflow_m3_s", "node_lateral_inflow_m3_s",
                  "outflow_m3_s", "spill_m3_s")
        for field in fields:
            for ident, value in row[field].items():
                key = field + ":" + ident
                low, high = self.ranges.get(key, (value, value))
                self.ranges[key] = (min(low, value), max(high, value))
        low, high = self.ranges.get("storage_m3:SYSTEM", (row["storage_m3"], row["storage_m3"]))
        self.ranges["storage_m3:SYSTEM"] = min(low, row["storage_m3"]), max(high, row["storage_m3"])

    def finish(self, step):
        if self.recipe["kind"] == "not_claimed":
            return {"required": False, "passed": None, "status": "not_claimed", "metrics": [], "physical_equilibration_established": False,
                    "interpretation": "Finite continuous preparation only; no numerical or physical equilibrium claim."}
        metrics = []
        for key, (low, high) in sorted(self.ranges.items()):
            field = key.split(":", 1)[0]
            limit = (self.recipe["flow_range_tolerance_m3_s"] if field.endswith("m3_s") else
                     self.recipe["storage_range_tolerance_m3"] if field.endswith("m3") else self.recipe["stage_range_tolerance_m"])
            metrics.append({"metric": key, "minimum": low, "maximum": high, "range": high - low, "tolerance": limit, "passed": high - low <= limit})
        expected = round(self.recipe["window_s"] / step) + 1
        complete = (self.count == expected and self.first is not None and abs(self.first - self.start) < 1e-6 and abs(self.last - self.event) < 1e-6)
        passed = complete and bool(metrics) and all(x["passed"] for x in metrics)
        return {"required": True, "passed": passed, "status": "numerically_stationary_window" if passed else "unresolved",
                "start_simulation_elapsed_s": self.start, "end_simulation_elapsed_s": self.event,
                "routing_state_samples": self.count, "expected_routing_state_samples": expected, "complete_window": complete,
                "constant_forcing_contract_checked": True, "metrics": metrics, "physical_equilibration_established": False,
                "interpretation": "Every actual-routing endpoint in the declared constant-forcing window was checked. Bounded numerical stationarity only, not measured equilibration or proof of future steadiness."}


def run(folder):
    result = {"status": "failed", "valid": False, "timeseries": [], "full_timeseries": [], "diagnostics": {}, "errors": [],
              "physical_validation_established": False, "physical_equilibration_established": False,
              "engineering_approval_established": False, "operational_activation_allowed": False}
    opened = started = False
    try:
        if Path.cwd().resolve() != folder.resolve():
            raise ValueError("Preparation worker must execute in its isolated artifact folder.")
        request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
        site, model, spec, prepared = (request[k] for k in ("site", "model", "run", "prepared_run"))
        event, horizon = prepared["event_start_s"], spec["duration_s"]
        nodes = {n["id"]: n for n in site["nodes"]}
        links = {l["id"]: l for l in request["effective_links"]}
        internal = sorted(k for k in nodes if nodes[k]["kind"] != "outfall")
        outfalls = sorted(set(nodes) - set(internal))
        inflows = site["boundaries"]["inflow_node_ids"]
        engine = request["fingerprint"]["engine"]
        for name, digest in engine["source_sha256"].items():
            if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest:
                raise ValueError("Source changed before worker execution: " + name)
        if engine["source_sha256"]["_bench_initialization_worker.py"] != _LOADED_SOURCE_SHA256:
            raise ValueError("Loaded preparation worker differs from the requested source.")
        if engine["source_sha256"]["_bench_worker.py"] != dry_worker._LOADED_SOURCE_SHA256:
            raise ValueError("Loaded signed-flow helper differs from the requested frozen source.")
        dist = importlib.metadata.distribution("swmm-toolkit")
        if solver.swmm_get_version() != engine["engine_version_int"] or dist.version != engine["toolkit_version"]:
            raise ValueError("Loaded engine version differs from the request.")
        for name, digest in engine["runtime_file_sha256"].items():
            if hashlib.sha256(Path(dist.locate_file(name)).read_bytes()).hexdigest() != digest:
                raise ValueError("Runtime bytes changed before worker execution.")
        if hashlib.sha256((folder / "model.inp").read_bytes()).hexdigest() != request["fingerprint"]["input_sha256"]:
            raise ValueError("SWMM input fingerprint mismatch.")
        for key, field in (("site", "site_sha256"), ("model", "model_sha256"), ("run", "run_sha256"), ("prepared_run", "prepared_run_sha256")):
            if _digest(request[key]) != request["fingerprint"][field]:
                raise ValueError("Request snapshot hash mismatch: " + key)
        if prepared["continuous_run"] != spec:
            raise ValueError("Preparation wrapper and continuous run disagree.")
        if _digest({"curves": request["curves"], "effective_links": request["effective_links"]}) != request["fingerprint"]["derived_geometry_sha256"]:
            raise ValueError("Derived fixed geometry fingerprint mismatch.")
        # The isolated child already runs in folder. Short native filenames
        # avoid SWMM's fixed-size path buffer truncating a long output name.
        solver.swmm_open("model.inp", "model.rpt", "model.out")
        opened = True
        solver.swmm_start(True)
        started = True
        ni = {k: solver.project_get_index(solver.swmm_NODE, k) for k in nodes}
        li = {k: solver.project_get_index(solver.swmm_LINK, k) for k in links}

        def nr(nid, code):
            value = solver.node_get_result(ni[nid], code.value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite live node state: " + nid)
            return value

        def lr(lid, code):
            value = solver.link_get_result(li[lid], code.value)
            if not math.isfinite(value):
                raise ValueError("Nonfinite live link state: " + lid)
            return value

        def sample(t):
            nv = {k: nr(k, NodeResult.VOLUME) for k in nodes}
            lv = {k: lr(k, LinkResult.VOLUME) for k in links}
            node_in = {k: nr(k, NodeResult.TOTAL_INFLOW) for k in nodes}
            node_out = {k: nr(k, NodeResult.TOTAL_OUTFLOW) for k in nodes}
            lateral = {k: nr(k, NodeResult.LATERAL_INFLOW) for k in nodes}
            # Preserve the reviewed v1 mapping: backflow is positive node outflow;
            # subtracting total getters would erase it after system bookkeeping.
            exchange = {k: -node_out[k] if node_out[k] > 0 else node_in[k] for k in outfalls}
            return {"elapsed_s": t, "stage_m": {k: nr(k, NodeResult.HEAD) for k in nodes},
                    "node_depth_m": {k: nr(k, NodeResult.DEPTH) for k in nodes},
                    "node_total_inflow_m3_s": node_in, "node_total_outflow_m3_s": node_out, "node_lateral_inflow_m3_s": lateral,
                    "link_flow_m3_s": {k: lr(k, LinkResult.FLOW) for k in links}, "link_depth_m": {k: lr(k, LinkResult.DEPTH) for k in links},
                    "node_storage_m3": nv, "link_storage_m3": lv, "storage_m3": sum(nv.values()) + sum(lv.values()),
                    "inflow_m3_s": {k: lateral[k] for k in inflows},
                    "prescribed_inflow_m3_s": _forcing_value(spec, "inflows", "value_m3_s", t),
                    "receiving_stage_m": _forcing_value(spec, "receiving_stages", "stage_m", t),
                    "outflow_m3_s": exchange, "spill_m3_s": {k: nr(k, NodeResult.FLOOD) for k in internal}}

        result["column_roles"] = {
            "prescribed_inputs": {"prescribed_inflow_m3_s": inflows, "receiving_stage_m": outfalls},
            "engine_applied_inputs": {"inflow_m3_s": inflows},
            "boundary_response_not_validation_target": {"stage_m": outfalls},
            "model_responses": {"stage_m": internal, "outflow_m3_s": outfalls, "spill_m3_s": internal,
                                "link_flow_m3_s": sorted(links), "node_storage_m3": sorted(nodes), "link_storage_m3": sorted(links), "storage_m3": ["SYSTEM"]},
            "engine_state_diagnostics": {"node_depth_m": sorted(nodes), "link_depth_m": sorted(links), "node_total_inflow_m3_s": sorted(nodes),
                                         "node_total_outflow_m3_s": sorted(nodes), "node_lateral_inflow_m3_s": sorted(nodes)}}
        first = previous = sample(0.0)
        result["full_timeseries"].append(first)
        whole, preparation, evaluation = _Ledger(first), _Ledger(first), None
        stationary = _Stationarity(prepared["preparation"]["equilibrium"], event)
        stationary.add(first)
        step, report_step = model["numerics"]["routing_step_s"], model["numerics"]["report_step_s"]
        next_report, steps, minimum_dt, maximum_dt = report_step, 0, math.inf, 0.0
        overtopped = set()
        while True:
            elapsed_days = solver.swmm_step()
            t = elapsed_days * 86400 if elapsed_days > 0 else float(horizon)
            dt = t - previous["elapsed_s"]
            if dt <= 0 or dt > step + 1e-6 or t > horizon + 1e-6:
                raise ValueError("Engine timestep/endpoint differs from the declared fixed routing grid.")
            if previous["elapsed_s"] < event - 1e-6 and t > event + 1e-6:
                raise ValueError("Routing interval crosses the event split without an exact state.")
            steps += 1
            if steps > 100001:
                raise ValueError("Routing step budget exceeded.")
            minimum_dt, maximum_dt = min(minimum_dt, dt), max(maximum_dt, dt)
            current = sample(t)
            whole.add(previous, current)
            if t <= event + 1e-6:
                preparation.add(previous, current)
            else:
                if evaluation is None:
                    raise ValueError("Event initial state missing; no interpolation or fabricated state is permitted.")
                evaluation.add(previous, current)
            stationary.add(current)
            if abs(t - event) < 1e-6:
                evaluation = _Ledger(current)
            for lid, link in links.items():
                x = link["cross_section"]
                if x["shape"] != "circular":
                    top, tolerance = x["height_m"], model["numerics"]["head_tolerance_m"]
                    if (current["link_depth_m"][lid] > top + tolerance or
                            current["stage_m"][link["from_node"]] > link["inlet_invert_m"] + top + tolerance or
                            current["stage_m"][link["to_node"]] > link["outlet_invert_m"] + top + tolerance):
                        overtopped.add(lid)
            if t >= next_report - 1e-6:
                if not math.isclose(t, next_report, abs_tol=1e-6):
                    raise ValueError("Reporting grid not reached exactly; no interpolation is permitted.")
                current["elapsed_s"] = float(next_report)
                result["full_timeseries"].append(current)
                next_report += report_step
            previous = current
            if elapsed_days <= 0:
                break
        if evaluation is None:
            raise ValueError("Missing evaluation phase.")
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
        phase_balances = {name: ledger.finish(spec) for name, ledger in (("whole", whole), ("preparation", preparation), ("evaluation", evaluation))}
        full = {**phase_balances["whole"], "continuity_error_percent": continuity, "minimum_actual_step_s": minimum_dt, "maximum_actual_step_s": maximum_dt,
                "final_elapsed_s": previous["elapsed_s"], "unsupported_open_link_overtopping": sorted(overtopped), "nonconverged_steps": nonconverged,
                "warnings": warnings, "raw_routing_totals": raw,
                "raw_storage_units": "Raw initStorage/finalStorage are internal ft3; live node/link VOLUME getters supply SI storage, using the pinned engine conversion.",
                "initial_numerical_storage_tolerance_m3": model["numerics"]["initial_numerical_storage_tolerance_m3"],
                "initial_state_note": "Actual numerical dry-link water at simulation start is retained in every applicable balance. Event initial state is reached without any reset."}
        equilibrium = stationary.finish(step)
        result.update(phase_balances=phase_balances, full_diagnostics=full, diagnostics=phase_balances["evaluation"], equilibrium=equilibrium,
                      dry_initial_state=first,
                      timeseries=[{**r, "simulation_elapsed_s": r["elapsed_s"], "elapsed_s": r["elapsed_s"] - event}
                                  for r in result["full_timeseries"] if r["elapsed_s"] >= event],
                      initialization={"kind": "continuous_dry_start", "geometry_policy": "same fixed geometry throughout preparation and evaluation",
                                      "simulation_duration_s": horizon, "event_start_s": event, "evaluation_duration_s": horizon - event,
                                      "state_reset_performed": False, "physical_equilibration_established": False})
        result["initial_state"] = result["timeseries"][0]
        problems = []
        if (first["storage_m3"] > model["numerics"]["initial_numerical_storage_tolerance_m3"] or
                any(abs(q) > 1e-12 for q in first["link_flow_m3_s"].values()) or any(abs(v) > 1e-12 for v in first["node_storage_m3"].values())):
            problems.append(("initial_state", "Nominal-dry engine initialization exceeds its explicit allowance or has nonzero node water/link flow."))
        if len(result["full_timeseries"]) != horizon // report_step + 1 or len(result["timeseries"]) != (horizon - event) // report_step + 1:
            problems.append(("incomplete_grid", "Missing full-history or event reporting endpoints."))
        for name, balance in phase_balances.items():
            if not balance["balance_passed"]:
                problems.append(("phase_mass_balance", name + " independent balance exceeds max(1 mL, 1% of its initial storage plus entering water)."))
            if not balance["cumulative_balance_passed"]:
                problems.append(("cumulative_mass_balance", name + " cumulative balance fails at one or more actual-routing endpoints; later cancellation does not establish conservation."))
            if abs(balance["prescribed_inflow_m3"] - balance["external_inflow_m3"]) > max(1e-6, 0.01 * balance["prescribed_inflow_m3"]):
                problems.append(("phase_forcing_integration", name + " engine-applied inflow differs materially from its prescribed integral."))
        entering = full["initial_storage_m3"] + full["external_inflow_m3"] + full["receiving_backflow_m3"]
        if abs(continuity) > 1 and entering > 1e-6:
            problems.append(("engine_continuity", "Whole-history SWMM routing continuity exceeds 1%."))
        tolerance = full["mass_balance_tolerance_m3"]
        if (abs(raw["exInflow"] - full["external_inflow_m3"] - full["receiving_backflow_m3"]) > tolerance or
                abs(raw["outflow"] - full["discharge_m3"]) > tolerance or abs(raw["flooding"] - full["spill_m3"]) > tolerance):
            problems.append(("routing_units_or_accounting", "Whole-history independently integrated SI flows do not reconcile with engine routing totals."))
        if raw["evapLoss"] != 0 or raw["seepLoss"] != 0:
            problems.append(("unexpected_loss", "Declared excluded-zero losses must be exactly zero in the engine totals."))
        if any(nonconverged.values()):
            problems.append(("nonconvergence", "At least one preparation/evaluation routing step did not converge."))
        if overtopped:
            problems.append(("unsupported_lateral_spill", "An open conduit reaches unrepresented lateral overtopping during preparation/evaluation."))
        if warnings:
            problems.append(("engine_warning", "SWMM reported a warning/error; inspect the retained report."))
        if equilibrium["required"] and not equilibrium["passed"]:
            problems.append(("equilibrium_unresolved", "The required constant-forcing stationarity window did not pass every actual-routing-state range check."))
        # Explicitly check independent phase sums so a boundary interval cannot
        # disappear or be counted twice even when each phase has small residual.
        for field in ("external_inflow_m3", "receiving_backflow_m3", "discharge_m3", "spill_m3"):
            if not math.isclose(phase_balances["preparation"][field] + phase_balances["evaluation"][field], full[field], rel_tol=1e-10, abs_tol=1e-12):
                problems.append(("phase_partition", "Preparation plus evaluation does not equal whole history: " + field))
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
