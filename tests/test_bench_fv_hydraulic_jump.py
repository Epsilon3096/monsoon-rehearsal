"""Prospective exact jump controls following the observed original-pulse failure.

This is a diagnostic-driven development gate, not blind evidence. Its separate
protocol freezes all bounds before corrected jump outputs. The earlier eight
analytical controls and every original mass/convergence limit remain unchanged.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import traceback

import numpy as np
import pytest

from monsoon import bench_fv


PROTOCOL_ID = "monsoon.fv-hydraulic-jump-protocol/1"
CRITERIA = {
    "gravity_m_s2": 9.81, "length_m": 4.0, "width_m": .08,
    "left_depth_m": .01, "right_depth_m": .02, "duration_s": 2.0,
    "grids": [[256, .005, .4], [512, .0025, .4], [512, .00125, .2]],
    "moving_speeds_m_s": [-.03, .03], "aligned_x_m": 2.0,
    "subcell_coarse_cell_fraction": 1 / 3,
    "aligned_max_depth_error_m": 1e-10,
    "aligned_max_q_error_m2_s": 1e-10,
    "depth_error_equivalent_cells": 2.0,
    "q_error_equivalent_cells": 2.0,
    "frame_discharge_error_equivalent_cells": .5,
    "fine_over_coarse_error_max": .8,
    "refinement_roundoff_equivalent_width_m": 1e-10,
    "shock_location_error_cells": 2.0,
    "depth_range_fraction_of_jump": .02,
    "pulse_exclusion_halfwidth_cells": 4.0,
    "outside_transition_frame_discharge_relative": .02,
    "time_halving_normalized_h_change": .01,
    "time_halving_normalized_q_change": .01,
    "invariant_allowance_cells": 1.0,
    "invariant_allowance_steps": 1.0,
    "roundoff_ulps": 64.0,
    "absolute_mass_budget_m3": 1e-6,
    "relative_mass_budget": .01,
    "exact_total_water_error_m3": 1e-10,
}
CASES = {
    "stationary-aligned": {"speed_m_s": 0., "x0_m": 2., "aligned_identity": True},
    "stationary-subcell": {"speed_m_s": 0., "x0_m": 2. + (4. / 256) / 3, "aligned_identity": False},
    "slow-left": {"speed_m_s": -.03, "x0_m": 2., "aligned_identity": False},
    "slow-right": {"speed_m_s": .03, "x0_m": 2., "aligned_identity": False},
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=True,
                  default=lambda value: value.tolist() if hasattr(value, "tolist") else value.item())
        stream.write("\n")


def parameters(case):
    g, hl, hr = (CRITERIA[key] for key in ("gravity_m_s2", "left_depth_m", "right_depth_m"))
    q0 = math.sqrt(.5 * g * hl * hr * (hl + hr))
    speed = case["speed_m_s"]
    ql, qr = q0 + speed * hl, q0 + speed * hr
    return hl, hr, q0, ql, qr


def exact_problem_checks(case):
    """Independent RH, entropy, Lax and boundary-domain construction checks."""
    hl, hr, q0, ql, qr = parameters(case)
    g, speed = CRITERIA["gravity_m_s2"], case["speed_m_s"]
    mass = (qr - ql) - speed * (hr - hl)
    momentum = (qr * qr / hr + .5 * g * hr * hr) - (ql * ql / hl + .5 * g * hl * hl) - speed * (qr - ql)
    el, er = .5 * ql * ql / hl + .5 * g * hl * hl, .5 * qr * qr / hr + .5 * g * hr * hr
    entropy = qr / hr * (er + .5 * g * hr * hr) - ql / hl * (el + .5 * g * hl * hl) - speed * (er - el)
    left_char, right_char = ql / hl - math.sqrt(g * hl), qr / hr - math.sqrt(g * hr)
    reach = max(abs(ql / hl) + math.sqrt(g * hl), abs(qr / hr) + math.sqrt(g * hr)) * CRITERIA["duration_s"]
    boundary_distance = min(case["x0_m"], CRITERIA["length_m"] - case["x0_m"])
    return {"mass_RH_residual_m2_s": mass, "momentum_RH_residual_m3_s2": momentum,
            "entropy_production": entropy, "shock_speed_m_s": speed,
            "left_minus_characteristic_m_s": left_char, "right_minus_characteristic_m_s": right_char,
            "largest_signal_reach_m": reach, "nearest_boundary_distance_m": boundary_distance,
            "passed": abs(mass) <= 1e-17 and abs(momentum) <= 1e-17 and entropy < 0
                      and left_char > speed > right_char and reach < boundary_distance}


def exact_cell_means(case, count, time):
    """Integrate the two constant exact states over every physical cell."""
    hl, hr, q0, ql, qr = parameters(case)
    dx = CRITERIA["length_m"] / count
    left = np.arange(count, dtype=float) * dx
    shock = case["x0_m"] + case["speed_m_s"] * time
    fraction = np.minimum(dx, np.maximum(0., shock - left)) / dx
    return fraction * hl + (1 - fraction) * hr, fraction * ql + (1 - fraction) * qr


def measure(case, h, q, time, count, step):
    h, q = np.asarray(h), np.asarray(q)
    failures = []
    if h.shape != (count,) or q.shape != (count,) or not np.isfinite(h).all() or not np.isfinite(q).all() or np.any(h <= 0):
        return {"time_s": float(time), "failures": ["nonfinite, nonpositive or incorrectly shaped exact-wet state"]}
    hl, hr, q0, ql, qr = parameters(case)
    g, length, duration = (CRITERIA[key] for key in ("gravity_m_s2", "length_m", "duration_s"))
    dx, jump, cref = length / count, hr - hl, math.sqrt(g * hr)
    x = (np.arange(count, dtype=float) + .5) * dx
    exact_h, exact_q = exact_cell_means(case, count, time)
    shock = case["x0_m"] + case["speed_m_s"] * time
    jerror = q - case["speed_m_s"] * h - q0
    outside = np.abs(x - shock) >= CRITERIA["pulse_exclusion_halfwidth_cells"] * dx
    roundoff = CRITERIA["roundoff_ulps"] * np.finfo(float).eps
    u = q / h
    low = min(ql / hl - 2 * math.sqrt(g * hl), qr / hr - 2 * math.sqrt(g * hr))
    high = max(ql / hl + 2 * math.sqrt(g * hl), qr / hr + 2 * math.sqrt(g * hr))
    amax = max(abs(ql / hl) + math.sqrt(g * hl), abs(qr / hr) + math.sqrt(g * hr))
    allowance = (CRITERIA["invariant_allowance_cells"] * dx
                 + CRITERIA["invariant_allowance_steps"] * amax * step) / duration
    momentum_allowance = roundoff * (np.abs(q) + (abs(low) + abs(high) + allowance) * h)
    upper_excess = q + 2 * h * np.sqrt(g * h) - (high + allowance) * h - momentum_allowance
    lower_excess = (low - allowance) * h - (q - 2 * h * np.sqrt(g * h)) - momentum_allowance
    range_allowance = CRITERIA["depth_range_fraction_of_jump"] * jump + roundoff * hr
    pulse = float(np.max(np.abs(jerror[outside]))) if np.any(outside) else 0.
    exact_volume = CRITERIA["width_m"] * (hl * shock + hr * (length - shock))
    volume = CRITERIA["width_m"] * dx * math.fsum(float(value) for value in h)
    checks = {
        "depth_range": float(np.min(h)) >= hl - range_allowance and float(np.max(h)) <= hr + range_allowance,
        "invariant_region": bool(np.all(upper_excess <= 0) and np.all(lower_excess <= 0)),
        "outside_transition_discharge_pulse": pulse <= CRITERIA["outside_transition_frame_discharge_relative"] * q0 + roundoff * q0,
        "exact_total_water": abs(volume - exact_volume) <= CRITERIA["exact_total_water_error_m3"],
    }
    if case["aligned_identity"]:
        checks["aligned_depth_identity"] = float(np.max(np.abs(h - exact_h))) <= CRITERIA["aligned_max_depth_error_m"]
        checks["aligned_q_identity"] = float(np.max(np.abs(q - exact_q))) <= CRITERIA["aligned_max_q_error_m2_s"]
    crossings = np.flatnonzero((h[:-1] < .5 * (hl + hr)) & (h[1:] >= .5 * (hl + hr)))
    location = math.nan
    if len(crossings) == 1:
        i = int(crossings[0])
        location = float(x[i] + (.5 * (hl + hr) - h[i]) * dx / (h[i + 1] - h[i]))
    checks["single_shock_location"] = len(crossings) == 1 and abs(location - shock) <= CRITERIA["shock_location_error_cells"] * dx
    failures.extend(key for key, passed in checks.items() if not passed)
    return {
        "time_s": float(time), "checks": checks, "failures": failures,
        "h_error_equivalent_width_m": float(np.sum(np.abs(h - exact_h)) * dx / jump),
        "q_error_equivalent_width_m": float(np.sum(np.abs(q - exact_q)) * dx / (jump * cref)),
        "frame_discharge_error_equivalent_width_m": float(np.sum(np.abs(jerror)) * dx / q0),
        "maximum_depth_error_m": float(np.max(np.abs(h - exact_h))),
        "maximum_q_error_m2_s": float(np.max(np.abs(q - exact_q))),
        "outside_transition_maximum_frame_discharge_error_m2_s": pulse,
        "minimum_depth_m": float(np.min(h)), "maximum_depth_m": float(np.max(h)),
        "maximum_velocity_m_s": float(np.max(u)), "minimum_velocity_m_s": float(np.min(u)),
        "invariant_lower_m_s": low, "invariant_upper_m_s": high, "invariant_allowance_m_s": allowance,
        "maximum_invariant_upper_momentum_excess": float(np.max(upper_excess)),
        "maximum_invariant_lower_momentum_excess": float(np.max(lower_excess)),
        "shock_crossing_count": len(crossings), "shock_x_m": location, "exact_shock_x_m": shock,
        "independent_storage_m3": volume, "exact_storage_m3": exact_volume,
    }


@pytest.fixture(scope="session")
def jump_evidence(tmp_path_factory):
    configured = os.environ.get("MONSOON_FV_JUMP_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path_factory.mktemp("fv-jump")
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "manifest.json", {"schema": PROTOCOL_ID, "criteria": CRITERIA, "cases": CASES,
                                    "test_sha256": _sha(__file__), "core_sha256": _sha(bench_fv.__file__),
                                    "blind_holdout": False, "physical_validation_established": False})
    return root


def _run(root, case, count, step, cfl):
    folder = root / f"N{count}-dt{step}-cfl{cfl}"
    folder.mkdir(exist_ok=False)
    duration, length, width = (CRITERIA[key] for key in ("duration_s", "length_m", "width_m"))
    hl, hr, q0, ql, qr = parameters(case)
    initial_h, initial_q = exact_cell_means(case, count, 0.)
    network = {"nodes": {}, "channels": [{"id": "C", "from_node": "LEFT", "to_node": "RIGHT",
               "length_m": length, "width_m": width, "inlet_invert_m": 0., "outlet_invert_m": 0.,
               "height_m": .25, "roughness_n": 0.}], "inflows": {},
               "boundaries": {"LEFT": [[0., hl], [duration, hl]], "RIGHT": [[0., hr], [duration, hr]]},
               "duration_s": duration, "report_step_s": .1}
    options = {"cells_per_channel": count, "max_step_s": step, "cfl": cfl, "spatial_order": 2,
               "maximum_steps": 300000, "split_times": [duration / 2],
               "boundary_modes": {"LEFT": {"mode": "transmissive"}, "RIGHT": {"mode": "transmissive"}},
               "initial_state": {"channels": {"C": {"depth_m": initial_h.tolist(), "unit_discharge_m2_s": initial_q.tolist()}}}}
    _write(folder / "inputs.json", {"network": network, "options": options, "case": case})
    endpoints, last = [], {}
    def observer(snapshot):
        state = snapshot["channels"]["C"]
        h, q = np.array(state["depth_m"], copy=True), np.array(state["unit_discharge_m2_s"], copy=True)
        endpoints.append(measure(case, h, q, snapshot["time_s"], count, step))
        last.update(h=h, q=q)
    try:
        result = bench_fv.simulate(network, **options, state_observer=observer)
    except Exception:
        (folder / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        with gzip.open(folder / "independent-endpoint-metrics.jsonl.gz", "wt", encoding="utf-8") as stream:
            for row in endpoints:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=True,
                                        default=lambda value: value.tolist() if hasattr(value, "tolist") else value.item()) + "\n")
    compact = dict(result)
    trace = compact.pop("routing_trace", [])
    _write(folder / "result.json", compact)
    with gzip.open(folder / "routing-trace.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in trace:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=True) + "\n")
    errors = []
    if result.get("valid") is not True:
        errors.append("solver did not report a complete valid run")
    if len(trace) != len(endpoints) or not endpoints or endpoints[-1]["time_s"] != duration:
        errors.append("missing or incomplete actual endpoint observations")
    initial = width * (hl * case["x0_m"] + hr * (length - case["x0_m"]))
    incoming = outgoing = phase_in = phase_out = 0.
    phase_start, max_residual, max_phase_residual, split_seen = initial, 0., 0., False
    for row, observed in zip(trace, endpoints):
        if row["time_s"] != observed["time_s"]:
            errors.append("routing and independently observed endpoints differ")
        values = [row[key] for key in ("interval_external_inflow_m3", "interval_receiving_backflow_m3", "interval_discharge_m3", "interval_spill_m3")]
        if not all(math.isfinite(value) and value >= 0 for value in values):
            errors.append("nonfinite or negative actual gross water transfer")
            continue
        enter, leave = values[0] + values[1], values[2] + values[3]
        incoming += enter; outgoing += leave; phase_in += enter; phase_out += leave
        storage = observed.get("independent_storage_m3", math.nan)
        residual, phase_residual = storage - initial - incoming + outgoing, storage - phase_start - phase_in + phase_out
        if not math.isfinite(storage) or abs(storage - row["storage_m3"]) > 1e-12:
            errors.append("reported stored water differs from independent actual cell volume")
        if abs(residual) > max(CRITERIA["absolute_mass_budget_m3"], CRITERIA["relative_mass_budget"] * (initial + incoming)):
            errors.append("cumulative 1mL/1percent water budget")
        if abs(phase_residual) > max(CRITERIA["absolute_mass_budget_m3"], CRITERIA["relative_mass_budget"] * (phase_start + phase_in)):
            errors.append("within-phase 1mL/1percent water budget")
        max_residual, max_phase_residual = max(max_residual, abs(residual)), max(max_phase_residual, abs(phase_residual))
        if row["time_s"] == duration / 2:
            phase_start, phase_in, phase_out, split_seen = storage, 0., 0., True
    if not split_seen:
        errors.append("missing actual half-duration phase endpoint")
    endpoint_failures = [{"time_s": row["time_s"], "failures": row["failures"]} for row in endpoints if row["failures"]]
    errors.extend("endpoint " + str(row["time_s"]) + ": " + ", ".join(row["failures"]) for row in endpoint_failures)
    final = endpoints[-1] if endpoints else {}
    dx = length / count
    for metric, bound in (("h_error_equivalent_width_m", "depth_error_equivalent_cells"),
                          ("q_error_equivalent_width_m", "q_error_equivalent_cells"),
                          ("frame_discharge_error_equivalent_width_m", "frame_discharge_error_equivalent_cells")):
        if not final.get(metric, math.inf) <= CRITERIA[bound] * dx:
            errors.append("final " + metric)
    _write(folder / "metrics.json", {"passed": not errors, "failures": errors, "final": final,
                                    "maximum_cumulative_mass_residual_m3": max_residual,
                                    "maximum_phase_mass_residual_m3": max_phase_residual,
                                    "observed_endpoints": len(endpoints), "failed_endpoints": endpoint_failures})
    return {"errors": errors, "final": final, "h": last.get("h"), "q": last.get("q")}


@pytest.mark.parametrize("case_id", list(CASES))
def test_exact_stationary_and_slow_hydraulic_jump(jump_evidence, case_id):
    case = CASES[case_id]
    folder = jump_evidence / case_id
    folder.mkdir(exist_ok=False)
    exact_problem = exact_problem_checks(case)
    _write(folder / "exact-problem-checks.json", exact_problem)
    assert exact_problem["passed"], "Independent exact RH problem construction failed before any solver call"
    runs, errors = [], []
    grids = CRITERIA["grids"][:1] if case["aligned_identity"] else CRITERIA["grids"]
    for count, step, cfl in grids:
        try:
            run = _run(folder, case, count, step, cfl)
            runs.append(run)
            errors.extend(f"N{count}/dt{step}: " + error for error in run["errors"])
        except Exception as exc:
            errors.append(f"N{count}/dt{step}: {type(exc).__name__}: {exc}")
            runs.append(None)
    comparisons = {}
    if len(runs) == 3 and all(run is not None for run in runs):
        coarse, fine, half = runs
        for field in ("h_error_equivalent_width_m", "q_error_equivalent_width_m", "frame_discharge_error_equivalent_width_m"):
            c, f = coarse["final"].get(field), fine["final"].get(field)
            if c is None or f is None or not math.isfinite(c) or not math.isfinite(f):
                comparisons[field] = {"passed": False, "unresolved": "missing or nonfinite final error metric"}
                errors.append("unresolved mesh refinement " + field)
                continue
            limit = CRITERIA["fine_over_coarse_error_max"] * c + CRITERIA["refinement_roundoff_equivalent_width_m"]
            comparisons[field] = {"coarse": c, "fine": f, "fine_limit": limit, "passed": f <= limit}
            if f > limit:
                errors.append("mesh refinement " + field)
        dx = CRITERIA["length_m"] / CRITERIA["grids"][1][0]
        jump, cref = CRITERIA["right_depth_m"] - CRITERIA["left_depth_m"], math.sqrt(CRITERIA["gravity_m_s2"] * CRITERIA["right_depth_m"])
        for field, scale, key in (("h", jump * cref * CRITERIA["duration_s"], "time_halving_normalized_h_change"),
                                  ("q", jump * cref**2 * CRITERIA["duration_s"], "time_halving_normalized_q_change")):
            if (fine[field] is None or half[field] is None
                    or fine[field].shape != (CRITERIA["grids"][1][0],)
                    or half[field].shape != (CRITERIA["grids"][2][0],)
                    or not np.isfinite(fine[field]).all() or not np.isfinite(half[field]).all()):
                comparisons[key] = {"passed": False, "unresolved": "missing, invalid or nonfinite final state"}
                errors.append("unresolved time refinement " + field)
                continue
            change = float(np.sum(np.abs(fine[field] - half[field])) * dx / scale)
            comparisons[key] = {"value": change, "limit": CRITERIA[key], "passed": change <= CRITERIA[key]}
            if change > CRITERIA[key]:
                errors.append("time refinement " + field)
    elif len(runs) == 3:
        comparisons["unresolved"] = {"passed": False, "reason": "one or more fixed-grid runs failed before final measurement"}
    _write(folder / "case-metrics.json", {"passed": not errors, "failures": errors, "comparisons": comparisons})
    assert not errors, "\n".join(errors)
