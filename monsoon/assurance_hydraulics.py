"""Numerical evidence for each state used by the development stress audit."""
from __future__ import annotations

from copy import deepcopy
import math

from monsoon.case import load_case
from monsoon.hydraulics import run_state


def checked_state(completed, scenario, cache):
    """Keep raw base output and attach convergence/recession evidence.

    Unlike the deliberately timed D1 boundary diagnostic, every state used for
    the approval audit must have adequately captured event spill by 180 minutes.
    The audit independently checks that location-level eligibility is unchanged
    under step halving against its matching no-additional-work reference.
    """
    base = run_state(completed, scenario, cache, routing_step=.5, horizon_minutes=180)
    half = run_state(completed, scenario, cache, routing_step=.25, horizon_minutes=180)
    extended = run_state(completed, scenario, cache, routing_step=.5, horizon_minutes=360)
    errors = []
    runs = [("default", base), ("half step", half), ("extended horizon", extended)]
    for label, run in runs:
        if run.get("valid") is not True or run.get("status") != "succeeded" or not run.get("run_id"):
            errors.append(f'{label}: hydraulic evidence is invalid: {"; ".join(run.get("errors", []))}')
    if len({run.get("engine_version") for _, run in runs}) != 1:
        errors.append("Numerical comparison used different engine versions.")
    deltas, extra = {}, {}
    if not errors:
        nodes = [node["id"] for node in load_case()["nodes"]]
        for node_id in nodes:
            try:
                a, b, c = [float(run["nodes"][node_id]["spill_m3"]) for _, run in runs]
                if not all(math.isfinite(v) and v >= 0 for v in (a,b,c)):
                    raise ValueError("nonfinite/negative spill")
                tolerance = max(.05, .02 * max(abs(a), abs(b)))
                delta = abs(a-b)
                deltas[node_id] = {"absolute_m3": delta, "tolerance_m3": tolerance}
                extra[node_id] = c-a
                if delta > tolerance:
                    errors.append(f"{node_id}: spill does not converge under step halving.")
                if abs(c-a) > .05:
                    errors.append(f"{node_id}: event spill changes by {c-a:.6f} m³ at 360 minutes.")
            except (KeyError, ValueError, TypeError) as exc:
                errors.append(f"{node_id}: missing or invalid numerical evidence ({exc}).")
        try:
            a,b,c = [float(run["total_spill_m3"]) for _, run in runs]
            if not all(math.isfinite(v) and v >= 0 for v in (a,b,c)):
                raise ValueError("nonfinite/negative total spill")
            if abs(a-b) > max(.05,.02*max(abs(a),abs(b))):
                errors.append("Total spill does not converge under step halving.")
            if abs(c-a) > .05:
                errors.append("Total event spill changes materially at 360 minutes.")
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f"Missing or invalid total spill: {exc}")
    result = deepcopy(base)
    result["assurance_numerics"] = {
        "valid": not errors, "status": "passed" if not errors else "unresolved", "errors": errors,
        "all_engine_runs_valid": all(r.get("valid") is True for _,r in runs),
        "default_run_id": base.get("run_id"), "half_step_run_id": half.get("run_id"),
        "extended_run_id": extended.get("run_id"),
        "routing_step_s": .5, "half_step_s": .25, "horizon_minutes": 180,
        "extended_horizon_minutes": 360,
        "half_step_nodes": half.get("nodes", {}), "half_step_total_spill_m3": half.get("total_spill_m3"),
        "per_node_deltas": deltas, "horizon_extra_spill_m3": extra,
        "files": {label: run.get("files", {}) for label,run in runs},
        "runs": [{"configuration": label, **{key: run.get(key) for key in
                  ["run_id", "status", "valid", "engine_version", "nodes", "total_spill_m3", "diagnostics", "files"]}}
                 for label,run in runs],
        "contract": "Every represented node and total: max(0.05 m³,2%) step-halving; 0.05 m³ horizon tolerance; no independent-replicate or physical-validation claim."
    }
    return result
