"""Private exact-input SWMM cumulative-balance audit worker."""
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
if __package__:
    from ._bench_worker import _signed_integral
else:
    from _bench_worker import _signed_integral

_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_VOLUME_UCF = 0.02832  # Reviewed pinned runtime's rounded m3/ft3 conversion.


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _cumulative_checks(t, initial, storage, inflow, backflow, discharge, spill, native):
    """Use gross entering water for both budgets; net exchange cannot recover it."""
    entering = initial + inflow + backflow
    tolerance = max(1e-6, .01 * entering)
    native_residual = initial + native["exInflow"] - native["outflow"] - native["flooding"] - storage
    independent_residual = initial + inflow + backflow - discharge - spill - storage
    common = {"elapsed_s": t, "tolerance_m3": tolerance, "initial_plus_entered_m3": entering,
              "storage_m3": storage, "cumulative_external_inflow_m3": inflow,
              "cumulative_receiving_backflow_m3": backflow, "cumulative_discharge_m3": discharge}
    native_check = {**common, "residual_m3": native_residual,
                    "absolute_residual_over_tolerance": abs(native_residual) / tolerance,
                    "native_reported_error_percent": native["pctError"], "native_net_outflow_m3": native["outflow"]}
    independent_check = {**common, "residual_m3": independent_residual,
                         "absolute_residual_over_tolerance": abs(independent_residual) / tolerance}
    return native_check, independent_check


def run(folder):
    result = {"valid": False, "status": "failed", "errors": [], "diagnostics": {}, "report_samples": []}
    opened = started = False
    try:
        request = json.loads((folder / "request.json").read_bytes())
        fp, source_text = request["fingerprint"], request["parent_request_json"]
        identity = fp["audit_identity"]
        engine = identity["engine_identity"]
        if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != fp["source_request_sha256"]:
            raise ValueError("Original request bytes differ from the audit binding.")
        original = json.loads(source_text)
        site, model, spec = (original[k] for k in ("site", "model", "run"))
        if original["fingerprint"]["engine"] != engine:
            raise ValueError("Original input was produced with a different engine/source identity.")
        for name, digest in {**engine["source_sha256"], **identity["source_sha256"]}.items():
            if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != digest:
                raise ValueError("Source changed before audit execution: " + name)
        if identity["source_sha256"]["_bench_balance_worker.py"] != _LOADED_SHA256:
            raise ValueError("Loaded audit worker differs from the bound source.")
        dist = importlib.metadata.distribution("swmm-toolkit")
        if solver.swmm_get_version() != 52004 or dist.version != "0.17.0":
            raise ValueError("Unsupported native engine/runtime.")
        for name, digest in engine["runtime_file_sha256"].items():
            if hashlib.sha256(Path(dist.locate_file(name)).read_bytes()).hexdigest() != digest:
                raise ValueError("Native runtime bytes changed before audit.")
        if hashlib.sha256((folder / "model.inp").read_bytes()).hexdigest() != fp["input_sha256"] or fp["input_sha256"] != original["fingerprint"]["input_sha256"]:
            raise ValueError("Audit must execute the exact retained parent input bytes.")
        for key in ("site", "model", "run"):
            if _digest(original[key]) != original["fingerprint"][key + "_sha256"]:
                raise ValueError("Original request snapshot identity mismatch: " + key)
        solver.swmm_open(str(folder / "model.inp"), str(folder / "model.rpt"), str(folder / "model.out"))
        opened = True
        solver.swmm_start(True)
        started = True
        ni = {n["id"]: solver.project_get_index(solver.swmm_NODE, n["id"]) for n in site["nodes"]}
        li = {l["id"]: solver.project_get_index(solver.swmm_LINK, l["id"]) for l in site["links"]}
        outfalls = site["boundaries"]["outfall_node_ids"]
        inflows = site["boundaries"]["inflow_node_ids"]
        internal = [n for n in ni if n not in outfalls]

        def sample(t):
            node_volume = sum(solver.node_get_result(i, NodeResult.VOLUME.value) for i in ni.values())
            link_volume = sum(solver.link_get_result(i, LinkResult.VOLUME.value) for i in li.values())
            exchange = {}
            for name in outfalls:
                outgoing = solver.node_get_result(ni[name], NodeResult.TOTAL_OUTFLOW.value)
                exchange[name] = -outgoing if outgoing > 0 else solver.node_get_result(ni[name], NodeResult.TOTAL_INFLOW.value)
            return {"elapsed_s": t, "storage_m3": node_volume + link_volume,
                    "inflow_m3_s": sum(solver.node_get_result(ni[n], NodeResult.LATERAL_INFLOW.value) for n in inflows),
                    "spill_m3_s": sum(solver.node_get_result(ni[n], NodeResult.FLOOD.value) for n in internal), "exchange": exchange}

        first = previous = sample(0.0)
        step, duration, report_step = model["numerics"]["routing_step_s"], spec["duration_s"], model["numerics"]["report_step_s"]
        cumulative_inflow = cumulative_backflow = cumulative_outflow = cumulative_spill = 0.0
        steps, next_report = 0, 0
        maximum_clock_difference = maximum_storage_difference = 0.0
        worst_native = worst_independent = None
        violation_count, first_violation, last_violation = 0, None, None

        def inspect(row):
            nonlocal worst_native, worst_independent, maximum_storage_difference, violation_count, first_violation, last_violation, next_report
            native = solver.system_get_routing_totals()
            raw = {k: getattr(native, k) for k in ("dwInflow", "wwInflow", "gwInflow", "iiInflow", "exInflow", "flooding", "outflow", "evapLoss", "seepLoss", "initStorage", "finalStorage", "pctError")}
            if not all(math.isfinite(v) for v in list(raw.values()) + [row["storage_m3"], row["inflow_m3_s"], row["spill_m3_s"]] + list(row["exchange"].values())):
                raise ValueError("Nonfinite cumulative balance state.")
            native_initial = raw["initStorage"] * _VOLUME_UCF
            native_storage = raw["finalStorage"] * _VOLUME_UCF
            difference = max(abs(native_initial - first["storage_m3"]), abs(native_storage - row["storage_m3"]))
            maximum_storage_difference = max(maximum_storage_difference, difference)
            if difference > max(1e-12, 1e-10 * max(abs(native_storage), abs(native_initial))):
                raise ValueError("Native raw-storage/live-storage SI mapping changed.")
            if raw["evapLoss"] != 0 or raw["seepLoss"] != 0 or any(raw[k] != 0 for k in ("dwInflow", "wwInflow", "gwInflow", "iiInflow")):
                raise ValueError("Unexpected external inputs/losses outside the bounded parent contract.")
            native_check, independent_check = _cumulative_checks(row["elapsed_s"], first["storage_m3"], row["storage_m3"],
                cumulative_inflow, cumulative_backflow, cumulative_outflow, cumulative_spill, raw)
            native_residual, tolerance = native_check["residual_m3"], native_check["tolerance_m3"]
            independent_residual, independent_tolerance = independent_check["residual_m3"], independent_check["tolerance_m3"]
            if worst_native is None or native_check["absolute_residual_over_tolerance"] > worst_native["absolute_residual_over_tolerance"]:
                worst_native = native_check
            if worst_independent is None or independent_check["absolute_residual_over_tolerance"] > worst_independent["absolute_residual_over_tolerance"]:
                worst_independent = independent_check
            if abs(native_residual) > tolerance or abs(independent_residual) > independent_tolerance:
                violation_count += 1
                first_violation = row["elapsed_s"] if first_violation is None else first_violation
                last_violation = row["elapsed_s"]
            if row["elapsed_s"] >= next_report - 1e-6:
                if abs(row["elapsed_s"] - next_report) > 1e-6:
                    raise ValueError("Audit did not reach the exact original reporting grid.")
                result["report_samples"].append({"elapsed_s": float(next_report), "storage_m3": row["storage_m3"],
                    "native_cumulative_residual_m3": native_residual, "native_tolerance_m3": tolerance,
                    "independent_cumulative_residual_m3": independent_residual, "independent_tolerance_m3": independent_tolerance,
                    "initial_plus_entered_m3": native_check["initial_plus_entered_m3"],
                    "cumulative_external_inflow_m3": cumulative_inflow, "cumulative_receiving_backflow_m3": cumulative_backflow,
                    "cumulative_discharge_m3": cumulative_outflow,
                    "native_exInflow_m3": raw["exInflow"], "native_outflow_m3": raw["outflow"], "native_flooding_m3": raw["flooding"]})
                next_report += report_step

        inspect(first)
        while True:
            days = solver.swmm_step()
            steps += 1
            t = days * 86400 if days > 0 else float(duration)
            maximum_clock_difference = max(maximum_clock_difference, abs(t - steps * step))
            dt = t - previous["elapsed_s"]
            if steps > 100001 or abs(t - steps * step) > 1e-6 or abs(dt - step) > 1e-6 or dt <= 0 or t > duration + 1e-6:
                raise ValueError("Audit routing clock differs from the exact parent fixed-step history.")
            row = sample(t)
            cumulative_inflow += dt * (previous["inflow_m3_s"] + row["inflow_m3_s"]) / 2
            cumulative_spill += dt * (previous["spill_m3_s"] + row["spill_m3_s"]) / 2
            for name in outfalls:
                outward, inward = _signed_integral(previous["exchange"][name], row["exchange"][name], dt)
                cumulative_outflow += outward
                cumulative_backflow += inward
            inspect(row)
            previous = row
            if days <= 0:
                break
        nonconverged = {name: solver.node_get_stats(ni[name]).nonConvergedCount for name in internal}
        solver.swmm_end()
        started = False
        solver.swmm_report()
        solver.swmm_close()
        opened = False
        warnings = [line.strip() for line in (folder / "model.rpt").read_text(encoding="utf-8", errors="replace").splitlines() if "WARNING" in line or "ERROR" in line]
        diagnostics = {"routing_steps": steps, "cumulative_endpoints_checked": steps + 1, "final_elapsed_s": previous["elapsed_s"],
                       "maximum_clock_difference_s": maximum_clock_difference, "maximum_native_live_storage_difference_m3": maximum_storage_difference,
                       "worst_native_balance": worst_native, "worst_independent_balance": worst_independent,
                       "violating_endpoint_count": violation_count, "first_violation_elapsed_s": first_violation,
                       "last_violation_elapsed_s": last_violation, "nonconverged_steps": nonconverged, "warnings": warnings,
                       "native_storage_conversion_m3_per_ft3": _VOLUME_UCF,
                       "tolerance_budget": "Initial live storage plus independently integrated gross external inflow and gross receiving backflow; shared by both residual checks. Native net outflow is retained separately.",
                       "native_error_limit_note": "The pinned engine can report tiny percent error for a finite bench-scale residual; explicit native totals and live storage are checked instead.",
                       "method": "Every actual routing endpoint: native cumulative volume balance and independently integrated live signed boundary flows against all node+link storage. Exact parent input bytes; same engine, no physical validation."}
        problems = []
        if violation_count:
            problems.append({"code": "cumulative_mass_balance", "message": "At least one intermediate routing endpoint exceeds max(1 mL, 1% of initial plus entered water); final cancellation cannot qualify the run."})
        if len(result["report_samples"]) != duration // report_step + 1:
            problems.append({"code": "incomplete_audit_grid", "message": "Audit report endpoints are incomplete."})
        if warnings or any(nonconverged.values()):
            problems.append({"code": "audit_engine_diagnostics", "message": "Native audit reported warnings/errors or nonconverged internal-node steps."})
        result.update(valid=not problems, status="succeeded" if not problems else "numerically_unresolved", diagnostics=diagnostics, errors=problems)
    except Exception as exc:
        result["errors"].append({"code": "audit_engine_failure", "message": f"{type(exc).__name__}: {exc}"})
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
