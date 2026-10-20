"""Independent analytical oracles for the separately scoped finite-volume engine.

Criteria were frozen on 2026-10-15 before candidate results in
work/v07-theory/fv-analytic-protocol.json (SHA256 below). These tests derive
physical expectations without calling the candidate's flux, geometry, source,
or balance routines. They are numerical verification, not physical validation.

Set MONSOON_FV_ANALYTIC_EVIDENCE_DIR to a NEW empty directory to retain every
result, actual-step ledger, input, metric and failure for an explicit attempt.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import traceback

import numpy as np
import pytest

from monsoon import bench_fv


PROTOCOL_SHA256 = "e0fdd213d77fec190805d57a6580249fadd21211f78bd286812afb42e8662754"
GRAVITY = 9.81
CRITERIA = {
    "emergent-lake-wall": {
        "max_depth_change_m": 1e-10,
        "max_unit_discharge_m2_s": 1e-10,
        "absolute_storage_change_m3": 1e-12,
    },
    "ritter-dry-dam-break": {
        "normalized_L1_h_coarse": 0.15,
        "normalized_L1_h_fine": 0.10,
        "normalized_L1_q_coarse": 0.25,
        "normalized_L1_q_fine": 0.20,
        "fine_over_coarse_error_max": 0.8,
        "fine_wet_front_error_m": 0.20,
        "wet_front_depth_threshold_m": 1e-5,
        "normalized_L1_time_halving_h_change": 0.01,
        "normalized_L1_time_halving_q_change": 0.01,
    },
    "tabular-storage-inverse": {
        "volume_absolute_m3": 1e-14,
        "stage_roundtrip_m": 1e-12,
        "area_absolute_m2": 1e-14,
    },
    "manning-friction-only": {
        "relative_q_error": 1e-13,
        "absolute_q_error_m2_s": 1e-15,
    },
    "uniform-manning-preservation": {
        "maximum_relative_depth_error": 0.02,
        "maximum_relative_unit_discharge_error": 0.02,
        "mean_relative_unit_discharge_error": 0.005,
    },
}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def _write_json(path, value):
    # Failed nonfinite output must be retained too; checks below reject it.
    path.write_text(json.dumps(value, indent=2, sort_keys=True,
                               default=_json_default, allow_nan=True) + "\n",
                    encoding="utf-8")


@pytest.fixture(scope="session")
def analytic_evidence(tmp_path_factory):
    configured = os.environ.get("MONSOON_FV_ANALYTIC_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path_factory.mktemp("fv-analytic")
    root.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite results of an earlier attempt.
    with (root / "analytic-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({
            "schema": "monsoon.fv-independent-analytic-attempt/1",
            "protocol_sha256": PROTOCOL_SHA256,
            "test_sha256": _sha256(__file__),
            "core_sha256": _sha256(bench_fv.__file__),
            "python": sys.version,
            "platform": platform.platform(),
            "numpy_version": np.__version__,
            "criteria": CRITERIA,
            "claim": "Independent analytical numerical verification only.",
        }, stream, indent=2, sort_keys=True)
    return root


def _single_channel(*, length, width, bed_start, bed_end, roughness, duration,
                    stage_up, stage_down):
    return {
        "nodes": {},
        "channels": [{
            "id": "C", "from_node": "UP", "to_node": "DOWN",
            "length_m": length, "width_m": width,
            "inlet_invert_m": bed_start, "outlet_invert_m": bed_end,
            "height_m": 0.25, "roughness_n": roughness,
        }],
        "inflows": {},
        "boundaries": {
            "UP": [[0.0, stage_up], [duration, stage_up]],
            "DOWN": [[0.0, stage_down], [duration, stage_down]],
        },
        "duration_s": duration,
        "report_step_s": min(0.1, duration),
    }


def _run(root, name, network, *, count, step, cfl, h, q, modes):
    directory = root / name
    directory.mkdir(exist_ok=False)
    options = {
        "cells_per_channel": count, "max_step_s": step, "cfl": cfl,
        "split_times": [network["duration_s"] / 2],
        "initial_state": {"channels": {"C": {
            "depth_m": list(h), "unit_discharge_m2_s": list(q),
        }}},
        "boundary_modes": modes, "spatial_order": 2,
        "maximum_steps": 300000,
    }
    _write_json(directory / "inputs.json", {"network": network, "options": options})
    try:
        result = bench_fv.simulate(network, **options)
    except Exception:
        (directory / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    summary = dict(result)
    trace = summary.pop("routing_trace", [])
    _write_json(directory / "result.json", summary)
    with gzip.open(directory / "routing-trace.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in trace:
            stream.write(json.dumps(row, sort_keys=True, default=_json_default,
                                    allow_nan=True) + "\n")
    return result, directory


def _mass_and_state_metrics(result, *, initial_storage, duration, expected_count,
                            width, length):
    """Reconstruct cumulative AND within-phase budgets from applied volumes.

    No use is made of the candidate's residual, tolerance, diagnostic or phase
    verdict. Negative signed transfers cannot inflate the gross-water budget.
    """
    failures = []
    if result.get("valid") is not True:
        failures.append(f"solver invalid: {result.get('status')}: {result.get('errors')}")
    trace = result.get("routing_trace", [])
    if not trace:
        return {"failures": failures + ["missing actual-step routing trace"],
                "independent_final_storage_m3": math.nan}
    initial = trace[0]
    if not math.isclose(float(initial["time_s"]), 0.0, abs_tol=1e-14):
        failures.append("routing trace does not start at zero")
    if abs(float(initial["storage_m3"]) - initial_storage) > 1e-12:
        failures.append("initial stored water disagrees with independent geometry")
    if abs(float(trace[-1]["time_s"]) - duration) > 1e-12:
        failures.append("solver did not finish the declared duration")

    incoming = outgoing = phase_incoming = phase_outgoing = 0.0
    phase_initial = initial_storage
    max_residual = max_ratio = max_phase_residual = max_phase_ratio = 0.0
    minimum_interval = 0.0
    minimum_depth = math.inf
    previous_time = 0.0
    split_seen = False
    split = duration / 2
    for index, row in enumerate(trace):
        time = float(row["time_s"])
        dt = float(row["dt_s"])
        storage = float(row["storage_m3"])
        depth_minimum = float(row["minimum_depth_m"])
        volumes = [float(row[key]) for key in (
            "interval_external_inflow_m3", "interval_receiving_backflow_m3",
            "interval_discharge_m3", "interval_spill_m3")]
        if not all(math.isfinite(v) for v in [time, dt, storage, depth_minimum, *volumes]):
            failures.append(f"nonfinite ledger endpoint {index}")
            continue
        minimum_interval = min(minimum_interval, *volumes)
        minimum_depth = min(minimum_depth, depth_minimum)
        if depth_minimum < 0.0:
            failures.append(f"negative minimum depth at endpoint {index}")
        if any(v < 0.0 for v in volumes):
            failures.append(f"negative gross interval volume at endpoint {index}")
        if storage < 0.0:
            failures.append(f"negative total storage at endpoint {index}")
        if index:
            if time <= previous_time or abs(dt - (time - previous_time)) > 1e-12:
                failures.append(f"invalid actual time interval at endpoint {index}")
        elif dt != 0.0 or any(v != 0.0 for v in volumes):
            failures.append("initial row has a nonzero interval")
        inc = math.fsum(volumes[:2])
        out = math.fsum(volumes[2:])
        incoming = math.fsum((incoming, inc))
        outgoing = math.fsum((outgoing, out))
        phase_incoming = math.fsum((phase_incoming, inc))
        phase_outgoing = math.fsum((phase_outgoing, out))
        residual = math.fsum((storage, -initial_storage, -incoming, outgoing))
        budget = max(1e-6, 0.01 * (initial_storage + incoming))
        phase_residual = math.fsum((storage, -phase_initial,
                                   -phase_incoming, phase_outgoing))
        phase_budget = max(1e-6, 0.01 * (phase_initial + phase_incoming))
        max_residual = max(max_residual, abs(residual))
        max_ratio = max(max_ratio, abs(residual) / budget)
        max_phase_residual = max(max_phase_residual, abs(phase_residual))
        max_phase_ratio = max(max_phase_ratio, abs(phase_residual) / phase_budget)
        if abs(residual) > budget:
            failures.append(f"cumulative mass budget failed at t={time}: {residual}")
        if abs(phase_residual) > phase_budget:
            failures.append(f"within-phase mass budget failed at t={time}: {phase_residual}")
        if abs(time - split) <= 1e-12:
            split_seen = True
            phase_initial, phase_incoming, phase_outgoing = storage, 0.0, 0.0
        previous_time = time
    if not split_seen:
        failures.append("actual routing endpoint missing at the fixed phase split")

    state = result.get("final_state", {}).get("channels", {}).get("C", {})
    h = list(state.get("depth_m", []))
    q = list(state.get("unit_discharge_m2_s", []))
    if len(h) != expected_count or len(q) != expected_count:
        failures.append("final cell arrays have the wrong length")
    if not all(math.isfinite(float(v)) for v in [*h, *q]):
        failures.append("nonfinite final depth or unit discharge")
    if any(float(v) < 0.0 for v in h):
        failures.append("negative final cell depth")
    independent_final_storage = math.fsum(h) * width * length / expected_count
    if abs(independent_final_storage - float(trace[-1]["storage_m3"])) > 1e-12:
        failures.append("final all-water storage disagrees with cell geometry")
    return {
        "failures": failures, "trace_endpoints": len(trace),
        "max_cumulative_mass_residual_m3": max_residual,
        "max_cumulative_mass_budget_fraction": max_ratio,
        "max_within_phase_mass_residual_m3": max_phase_residual,
        "max_within_phase_mass_budget_fraction": max_phase_ratio,
        "gross_entering_water_m3": incoming, "gross_leaving_water_m3": outgoing,
        "minimum_gross_interval_volume_m3": minimum_interval,
        "minimum_depth_over_actual_endpoints_m": minimum_depth,
        "independent_final_storage_m3": independent_final_storage,
    }


def _finish(directory, metrics, checks):
    failures = list(metrics.get("failures", []))
    failures.extend(name for name, passed in checks.items() if not passed)
    metrics["checks"] = checks
    metrics["failures"] = failures
    _write_json(directory / "metrics.json", metrics)
    assert not failures, "\n".join(failures)


def test_emergent_lake_at_rest(analytic_evidence):
    """A sloping bed crossing the free surface must stay completely at rest."""
    count, length, width, duration = 80, 2.0, 0.08, 10.0
    x = [(i + 0.5) * length / count for i in range(count)]
    bed = [0.02 + (0.06 - 0.02) * value / length for value in x]
    h0 = [max(0.04 - value, 0.0) for value in bed]
    network = _single_channel(length=length, width=width, bed_start=0.02,
                              bed_end=0.06, roughness=0.012, duration=duration,
                              stage_up=0.04, stage_down=0.04)
    result, directory = _run(analytic_evidence, "emergent-lake-wall", network,
                             count=count, step=0.01, cfl=0.4, h=h0, q=[0.0] * count,
                             modes={"UP": {"mode": "wall"}, "DOWN": {"mode": "wall"}})
    initial_volume = 0.5 * 1.0 * 0.02 * width
    metrics = _mass_and_state_metrics(result, initial_storage=initial_volume,
                                     duration=duration, expected_count=count,
                                     width=width, length=length)
    final = result.get("final_state", {}).get("channels", {}).get("C", {})
    final_h, final_q = final.get("depth_m", []), final.get("unit_discharge_m2_s", [])
    metrics.update(
        max_depth_change_m=max((abs(a - b) for a, b in zip(final_h, h0)), default=math.inf),
        max_unit_discharge_m2_s=max((abs(q) for q in final_q), default=math.inf),
        absolute_storage_change_m3=abs(metrics["independent_final_storage_m3"] - initial_volume),
    )
    _finish(directory, metrics, {
        name: metrics[name] <= limit for name, limit in CRITERIA["emergent-lake-wall"].items()
    })


def _ritter_cell_averages(count, *, length=10.0, dam=5.0, depth=0.1, time=1.0):
    """Integrate Ritter's polynomials exactly over each cell.

    In the fan, xi=(x-dam)/t, h=(2*c-xi)^2/(9*g),
    q=2*(4*c^3-3*c*xi^2+xi^3)/(27*g). Integrating these independent
    polynomials avoids substituting point samples for numerical cell averages.
    """
    c = math.sqrt(GRAVITY * depth)
    fan_left, fan_right = dam - c * time, dam + 2 * c * time
    dx = length / count
    h, q = [], []
    for i in range(count):
        left, right = i * dx, (i + 1) * dx
        depth_integral = depth * max(0.0, min(right, fan_left) - left)
        discharge_integral = 0.0
        a, b = max(left, fan_left), min(right, fan_right)
        if b > a:
            lo, hi = (a - dam) / time, (b - dam) / time
            depth_integral += time / (9 * GRAVITY) * (
                (hi**3 - lo**3) / 3 - 2 * c * (hi**2 - lo**2)
                + 4 * c**2 * (hi - lo))
            discharge_integral = 2 * time / (27 * GRAVITY) * (
                4 * c**3 * (hi - lo) - c * (hi**3 - lo**3)
                + (hi**4 - lo**4) / 4)
        h.append(depth_integral / dx)
        q.append(discharge_integral / dx)
    return h, q


def _normalized_l1(actual, expected, dx, normalization):
    return math.fsum(abs(a - b) for a, b in zip(actual, expected)) * dx / normalization


def test_ritter_dry_dam_break(analytic_evidence):
    """Wet/dry wave shape, advancing front, mesh and time convergence."""
    length, width, depth, duration, dam = 10.0, 0.08, 0.1, 1.0, 5.0
    c = math.sqrt(GRAVITY * depth)
    norm_h, norm_q = depth * c * duration, depth * c**2 * duration
    criteria = CRITERIA["ritter-dry-dam-break"]
    network = _single_channel(length=length, width=width, bed_start=0.0,
                              bed_end=0.0, roughness=0.0, duration=duration,
                              stage_up=depth, stage_down=0.0)
    runs = []
    for label, count, step, cfl in [
        ("coarse", 400, 0.0025, 0.4),
        ("fine", 800, 0.00125, 0.4),
        ("fine-half-time", 800, 0.000625, 0.2),
    ]:
        dx = length / count
        h0 = [depth if (i + 0.5) * dx < dam else 0.0 for i in range(count)]
        exact_h, exact_q = _ritter_cell_averages(count)
        # Separate integral identities verify the oracle's cell integration.
        assert abs(math.fsum(exact_h) * dx - depth * dam) < 1e-12
        assert abs(math.fsum(exact_q) * dx - 0.5 * GRAVITY * depth**2 * duration) < 1e-12
        result, directory = _run(analytic_evidence, "ritter-" + label, network,
                                 count=count, step=step, cfl=cfl, h=h0,
                                 q=[0.0] * count,
                                 modes={"UP": {"mode": "transmissive"},
                                        "DOWN": {"mode": "transmissive"}})
        metrics = _mass_and_state_metrics(result, initial_storage=width * depth * dam,
                                         duration=duration, expected_count=count,
                                         width=width, length=length)
        state = result.get("final_state", {}).get("channels", {}).get("C", {})
        h, q = state.get("depth_m", []), state.get("unit_discharge_m2_s", [])
        wet = [i for i, value in enumerate(h)
               if value > criteria["wet_front_depth_threshold_m"]]
        front = (wet[-1] + 1) * dx if wet else 0.0
        metrics.update(
            normalized_L1_h=_normalized_l1(h, exact_h, dx, norm_h) if len(h) == count else math.inf,
            normalized_L1_q=_normalized_l1(q, exact_q, dx, norm_q) if len(q) == count else math.inf,
            wet_front_m=front,
            wet_front_error_m=abs(front - (dam + 2 * c * duration)),
            exact_wet_front_m=dam + 2 * c * duration,
        )
        _write_json(directory / "oracle.json", {
            "depth_cell_mean_m": exact_h, "unit_discharge_cell_mean_m2_s": exact_q,
            "normalization_h_m2": norm_h, "normalization_q_m3_s": norm_q,
        })
        # Keep all three requested results even if the first misses a bound.
        _write_json(directory / "metrics.json", metrics)
        runs.append({"label": label, "directory": directory,
                     "h": h, "q": q, "metrics": metrics})

    coarse, fine, half_time = runs
    checks = {}
    all_failures = []
    for run in runs:
        label, metrics = run["label"], run["metrics"]
        category = "coarse" if label == "coarse" else "fine"
        all_failures.extend(f"{label}: {failure}" for failure in metrics["failures"])
        for variable in ("h", "q"):
            checks[f"{label} normalized L1 {variable}"] = (
                metrics[f"normalized_L1_{variable}"] <=
                criteria[f"normalized_L1_{variable}_{category}"])
        if category == "fine":
            checks[f"{label} wet front error"] = (
                metrics["wet_front_error_m"] <= criteria["fine_wet_front_error_m"])
    combined = {"failures": all_failures, "runs": {
        run["label"]: run["metrics"] for run in runs}}
    for variable in ("h", "q"):
        coarse_error = coarse["metrics"][f"normalized_L1_{variable}"]
        fine_error = fine["metrics"][f"normalized_L1_{variable}"]
        ratio = fine_error / coarse_error if coarse_error else (0.0 if fine_error == 0 else math.inf)
        combined[f"fine_over_coarse_{variable}_error"] = ratio
        checks[f"mesh convergence {variable}"] = ratio <= criteria["fine_over_coarse_error_max"]
        change = _normalized_l1(fine[variable], half_time[variable], length / 800,
                                norm_h if variable == "h" else norm_q)
        combined[f"normalized_L1_time_halving_{variable}_change"] = change
        checks[f"time convergence {variable}"] = (
            change <= criteria[f"normalized_L1_time_halving_{variable}_change"])
    comparison_directory = analytic_evidence / "ritter-dry-dam-break"
    comparison_directory.mkdir(exist_ok=False)
    _finish(comparison_directory, combined, checks)


def test_tabular_storage_volume_area_and_inverse(analytic_evidence):
    directory = analytic_evidence / "tabular-storage-inverse"
    directory.mkdir(exist_ok=False)
    curve_points = [[0.04, 0.01], [0.09, 0.03], [0.19, 0.02]]
    curve = bench_fv.StorageCurve(curve_points)
    stages = [0.04, 0.040000001, 0.045, 0.065, 0.089999999,
              0.09, 0.090000001, 0.13, 0.189999999, 0.19]
    records = []
    for stage in stages:
        if stage <= 0.09:
            d = stage - 0.04
            expected_volume = 0.01 * d + 0.2 * d**2
            expected_area = 0.01 + 0.4 * d
        else:
            e = stage - 0.09
            expected_volume = 0.001 + 0.03 * e - 0.05 * e**2
            expected_area = 0.03 - 0.1 * e
        volume, area = float(curve.volume(stage)), float(curve.area(stage))
        inverted = float(curve.stage(expected_volume))
        roundtrip = float(curve.stage(volume))
        records.append({
            "stage_m": stage, "expected_volume_m3": expected_volume,
            "expected_area_m2": expected_area, "actual_volume_m3": volume,
            "actual_area_m2": area, "inverted_exact_volume_stage_m": inverted,
            "roundtrip_stage_m": roundtrip,
        })
    _write_json(directory / "inputs-and-results.json", {"curve": curve_points, "records": records})
    metrics = {
        "volume_absolute_m3": max(abs(r["actual_volume_m3"] - r["expected_volume_m3"]) for r in records),
        "area_absolute_m2": max(abs(r["actual_area_m2"] - r["expected_area_m2"]) for r in records),
        "stage_roundtrip_m": max(max(abs(r["inverted_exact_volume_stage_m"] - r["stage_m"]),
                                     abs(r["roundtrip_stage_m"] - r["stage_m"])) for r in records),
    }
    _finish(directory, metrics, {
        name: metrics[name] <= limit for name, limit in CRITERIA["tabular-storage-inverse"].items()
    })


def test_manning_friction_matches_exact_fixed_depth_solution(analytic_evidence):
    directory = analytic_evidence / "manning-friction-only"
    directory.mkdir(exist_ok=False)
    h, width, n = 0.05, 0.08, 0.012
    radius = width * h / (width + 2 * h)
    k = GRAVITY * n**2 / (h * radius ** (4 / 3))
    records, checks = [], {}
    for q0 in [-0.02, -0.002, 0.0, 0.002, 0.02]:
        for duration in [0.01, 0.2, 1.0]:
            expected = math.copysign(1 / (1 / abs(q0) + k * duration), q0) if q0 else 0.0
            actual = float(bench_fv.manning_friction(h, q0, width, n, duration))
            error = abs(actual - expected)
            records.append({"h_m": h, "width_m": width, "n": n, "q0_m2_s": q0,
                            "dt_s": duration, "expected_q_m2_s": expected,
                            "actual_q_m2_s": actual, "absolute_q_error_m2_s": error})
            label = f"q0={q0}, dt={duration}"
            criteria = CRITERIA["manning-friction-only"]
            checks[label + " exact friction"] = error <= max(
                criteria["absolute_q_error_m2_s"], criteria["relative_q_error"] * abs(expected))
            checks[label + " sign"] = actual == 0.0 if q0 == 0.0 else actual * q0 > 0.0
            checks[label + " damping"] = abs(actual) <= abs(q0)
            identity = float(bench_fv.manning_friction(h, q0, width, 0.0, duration))
            checks[label + " no-friction identity"] = identity == q0
    dry = [float(bench_fv.manning_friction(0.0, q, width, n, 1.0))
           for q in [-0.02, 0.0, 0.02]]
    checks["dry-depth finite outputs"] = all(math.isfinite(value) for value in dry)
    checks["dry zero stays zero"] = dry[1] == 0.0
    _write_json(directory / "inputs-and-results.json", {"records": records, "dry_outputs": dry})
    _finish(directory, {"maximum_absolute_q_error_m2_s": max(
        r["absolute_q_error_m2_s"] for r in records)}, checks)


def test_uniform_manning_moving_equilibrium(analytic_evidence):
    """Normal flow on a constant slope tests source/flux/friction together."""
    count, length, width, h0, n, duration = 500, 100.0, 0.08, 0.05, 0.012, 5.0
    slope = (0.2 - 0.1) / length
    radius = width * h0 / (width + 2 * h0)
    velocity = radius ** (2 / 3) * math.sqrt(slope) / n
    q0 = h0 * velocity
    network = _single_channel(length=length, width=width, bed_start=0.2,
                              bed_end=0.1, roughness=n, duration=duration,
                              stage_up=0.2 + h0, stage_down=0.1 + h0)
    result, directory = _run(analytic_evidence, "uniform-manning-preservation", network,
                             count=count, step=0.01, cfl=0.4, h=[h0] * count,
                             q=[q0] * count, modes={
                                 "UP": {"mode": "fixed_velocity", "velocity_m_s": velocity},
                                 "DOWN": {"mode": "fixed_velocity", "velocity_m_s": velocity},
                             })
    metrics = _mass_and_state_metrics(result, initial_storage=width * h0 * length,
                                     duration=duration, expected_count=count,
                                     width=width, length=length)
    state = result.get("final_state", {}).get("channels", {}).get("C", {})
    depth_errors = [abs(h - h0) / h0 for h in state.get("depth_m", [])]
    q_errors = [abs(q - q0) / q0 for q in state.get("unit_discharge_m2_s", [])]
    metrics.update(maximum_relative_depth_error=max(depth_errors, default=math.inf),
                   maximum_relative_unit_discharge_error=max(q_errors, default=math.inf),
                   mean_relative_unit_discharge_error=math.fsum(q_errors) / count if len(q_errors) == count else math.inf,
                   analytical_normal_velocity_m_s=velocity,
                   analytical_unit_discharge_m2_s=q0)
    _finish(directory, metrics, {
        name: metrics[name] <= limit for name, limit in CRITERIA["uniform-manning-preservation"].items()
    })
