"""Additional all-cell Ritter quality gate, separate from the original five.

This gate was devised after thin-tail overshoot was observed. Its provenance
explicitly includes the already-observed monotone-velocity workcopy. It is
frozen for subsequent corrections; it is NOT represented as a blind test of
that workcopy. Original analytical acceptance criteria remain unchanged.
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


PROTOCOL_ID = "monsoon.fv-thin-front-protocol/1"
CRITERIA = {
    "gravity_m_s2": 9.81,
    "depth_m": 0.1,
    "width_m": 0.08,
    "length_m": 10.0,
    "dam_x_m": 5.0,
    "duration_s": 1.0,
    "spatial_allowance_cells": 1.0,
    "temporal_allowance_steps": 1.0,
    "roundoff_ulps_factor": 64.0,
    "support_strip_m": 0.20,
    "grids": [[400, 0.0025, 0.4], [800, 0.00125, 0.4], [800, 0.000625, 0.2]],
}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=True) + "\n",
                    encoding="utf-8")


@pytest.fixture(scope="session")
def thin_front_evidence(tmp_path_factory):
    configured = os.environ.get("MONSOON_FV_THIN_FRONT_EVIDENCE_DIR")
    root = Path(configured) if configured else tmp_path_factory.mktemp("fv-thin-front")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"schema": PROTOCOL_ID, "criteria": CRITERIA,
                   "test_sha256": _sha(__file__), "core_sha256": _sha(bench_fv.__file__),
                   "numpy_version": np.__version__,
                   "claim": "Supplemental numerical verification; no physical-validation claim."},
                  stream, indent=2, sort_keys=True)
    return root


def _exact_front_strip_water(time):
    """Exact Ritter water in the pre-existing 0.20 m front-uncertainty strip."""
    g, h0, width = CRITERIA["gravity_m_s2"], CRITERIA["depth_m"], CRITERIA["width_m"]
    c0 = math.sqrt(g * h0)
    front = CRITERIA["dam_x_m"] + 2 * c0 * time
    left = max(0.0, front - CRITERIA["support_strip_m"])
    right = min(CRITERIA["length_m"], front)
    if time == 0:
        return width * h0 * max(0.0, min(right, CRITERIA["dam_x_m"]) - left)
    fan_left = CRITERIA["dam_x_m"] - c0 * time
    integral = h0 * max(0.0, min(right, fan_left) - left)
    a, b = max(left, fan_left), min(right, front)
    if b > a:
        integral += ((front - a) ** 3 - (front - b) ** 3) / (27 * g * time**2)
    return width * integral


def measure_state(h, q, *, time, count, step):
    """Independent check of every cell, including positive subnormal depths.

    Momentum-form comparisons avoid division by tiny h. There is no selected
    wet-depth threshold. q/h is calculated only for diagnostic reporting.
    """
    h, q = np.asarray(h, dtype=float), np.asarray(q, dtype=float)
    if h.shape != (count,) or q.shape != (count,):
        return {"time_s": float(time), "failures": ["wrong cell-array shape"]}
    if not np.isfinite(h).all() or not np.isfinite(q).all() or np.any(h < 0):
        return {"time_s": float(time), "failures": ["nonfinite state or negative depth"]}
    g, h0 = CRITERIA["gravity_m_s2"], CRITERIA["depth_m"]
    dx, duration = CRITERIA["length_m"] / count, CRITERIA["duration_s"]
    exact_speed = 2 * math.sqrt(g * h0)
    speed_allowance = (CRITERIA["spatial_allowance_cells"] * dx
                       + CRITERIA["temporal_allowance_steps"] * exact_speed * step) / duration
    speed_limit = exact_speed + speed_allowance
    momentum_bound = speed_limit * h
    pressure_term = 2 * math.sqrt(g) * h * np.sqrt(h)
    tiny = float(np.nextafter(0.0, 1.0))
    factor = CRITERIA["roundoff_ulps_factor"]
    momentum_roundoff = factor * np.finfo(float).eps * (np.abs(q) + momentum_bound) + factor * tiny
    invariant_roundoff = factor * np.finfo(float).eps * (
        np.abs(q) + momentum_bound + pressure_term) + factor * tiny
    velocity_excess = np.abs(q) - momentum_bound - momentum_roundoff
    invariant_excess = np.abs(q) + pressure_term - momentum_bound - invariant_roundoff
    negative_flow_excess = -q - momentum_roundoff
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        velocity = np.divide(q, h, out=np.zeros_like(q), where=h > 0)
    invariants = np.abs(velocity) + 2 * np.sqrt(g * h)
    face_left = np.arange(count, dtype=float) * dx
    front = CRITERIA["dam_x_m"] + exact_speed * time
    overlap = np.maximum(0.0, face_left + dx - np.maximum(face_left, front))
    unsupported_water = float(np.sum(h * overlap) * CRITERIA["width_m"])
    support_bound = _exact_front_strip_water(time)
    initial_water = CRITERIA["width_m"] * h0 * CRITERIA["dam_x_m"]
    support_roundoff = factor * np.finfo(float).eps * initial_water + factor * tiny
    checks = {
        "velocity_bound": not bool(np.any(velocity_excess > 0)),
        "invariant_region": not bool(np.any(invariant_excess > 0)),
        "nonnegative_flow": not bool(np.any(negative_flow_excess > 0)),
        "tail_support_water": unsupported_water <= support_bound + support_roundoff,
    }
    iv, ir, iq = int(np.argmax(velocity_excess)), int(np.argmax(invariant_excess)), int(np.argmin(q))
    witnesses = {}
    for label, index in [("velocity", iv), ("invariant", ir), ("minimum_flow", iq)]:
        witnesses[label] = {"cell_index": index, "x_m": (index + 0.5) * dx,
                            "depth_m": float(h[index]), "unit_discharge_m2_s": float(q[index]),
                            "velocity_m_s": float(velocity[index]),
                            "absolute_velocity_plus_2c_m_s": float(invariants[index])}
    return {
        "time_s": float(time), "speed_limit_m_s": speed_limit,
        "exact_global_speed_bound_m_s": exact_speed,
        "resolution_allowance_m_s": speed_allowance,
        "maximum_absolute_velocity_m_s": float(np.max(np.abs(velocity))),
        "maximum_absolute_velocity_plus_2c_m_s": float(np.max(invariants)),
        "maximum_velocity_momentum_excess_m2_s": float(np.max(velocity_excess)),
        "maximum_invariant_momentum_excess_m2_s": float(np.max(invariant_excess)),
        "maximum_negative_flow_excess_m2_s": float(np.max(negative_flow_excess)),
        "velocity_violating_cell_count": int(np.count_nonzero(velocity_excess > 0)),
        "invariant_violating_cell_count": int(np.count_nonzero(invariant_excess > 0)),
        "minimum_unit_discharge_m2_s": float(np.min(q)),
        "water_beyond_exact_front_m3": unsupported_water,
        "support_water_bound_m3": support_bound,
        "witnesses": witnesses,
        "failures": [name for name, passed in checks.items() if not passed],
    }


@pytest.mark.parametrize("count,step,cfl", CRITERIA["grids"],
                         ids=["coarse", "fine", "fine-half-time"])
def test_ritter_velocity_invariant_and_support_at_every_endpoint(
        thin_front_evidence, count, step, cfl):
    directory = thin_front_evidence / f"N{count}-dt{step}-cfl{cfl}"
    directory.mkdir(exist_ok=False)
    duration, length = CRITERIA["duration_s"], CRITERIA["length_m"]
    h0, width, dam = CRITERIA["depth_m"], CRITERIA["width_m"], CRITERIA["dam_x_m"]
    network = {
        "nodes": {},
        "channels": [{"id": "C", "from_node": "UP", "to_node": "DOWN",
                      "length_m": length, "width_m": width,
                      "inlet_invert_m": 0.0, "outlet_invert_m": 0.0,
                      "height_m": 0.25, "roughness_n": 0.0}],
        "inflows": {},
        "boundaries": {"UP": [[0.0, h0], [duration, h0]],
                       "DOWN": [[0.0, 0.0], [duration, 0.0]]},
        "duration_s": duration, "report_step_s": 0.1,
    }
    options = {
        "cells_per_channel": count, "max_step_s": step, "cfl": cfl,
        "split_times": [duration / 2], "spatial_order": 2, "maximum_steps": 300000,
        "initial_state": {"channels": {"C": {
            "depth_m": [h0 if (i + 0.5) * length / count < dam else 0.0 for i in range(count)],
            "unit_discharge_m2_s": [0.0] * count,
        }}},
        "boundary_modes": {"UP": {"mode": "transmissive"}, "DOWN": {"mode": "transmissive"}},
    }
    _write_json(directory / "inputs.json", {"network": network, "options": options,
                                           "observer": "independent all-cell measure_state callback"})
    records = []
    last_state = {}

    def observer(snapshot):
        state = snapshot["channels"]["C"]
        h, q = np.array(state["depth_m"], copy=True), np.array(state["unit_discharge_m2_s"], copy=True)
        records.append(measure_state(h, q, time=snapshot["time_s"], count=count, step=step))
        last_state.update(h=h, q=q)

    try:
        result = bench_fv.simulate(network, **options, state_observer=observer)
    except Exception:
        (directory / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        with gzip.open(directory / "independent-endpoint-metrics.jsonl.gz", "wt", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True, allow_nan=True) + "\n")
    summary = dict(result)
    trace = summary.pop("routing_trace", [])
    _write_json(directory / "result.json", summary)
    with gzip.open(directory / "routing-trace.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in trace:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=True) + "\n")
    failures = []
    if result.get("valid") is not True:
        failures.append(f"solver invalid: {result.get('status')}: {result.get('errors')}")
    if not records or len(records) != len(trace):
        failures.append("independent observer did not cover every actual routing endpoint")
    if any(abs(record["time_s"] - row["time_s"]) > 1e-12 for record, row in zip(records, trace)):
        failures.append("observer times differ from actual routing trace")
    if not records or abs(records[-1]["time_s"] - duration) > 1e-12:
        failures.append("did not observe exact completed horizon")
    final = result.get("final_state", {}).get("channels", {}).get("C", {})
    if not np.array_equal(last_state.get("h"), final.get("depth_m")) or not np.array_equal(
            last_state.get("q"), final.get("unit_discharge_m2_s")):
        failures.append("final observer arrays differ from actual final state")
    failed_endpoints = [{"time_s": r["time_s"], "failures": r["failures"]}
                        for r in records if r["failures"]]
    if failed_endpoints:
        failures.append(f"physical quality criteria failed at {len(failed_endpoints)} endpoints")
    metrics = {"failures": failures, "observed_endpoints": len(records),
               "failed_endpoints": failed_endpoints,
               "maximum_absolute_velocity_m_s": max((r.get("maximum_absolute_velocity_m_s", math.inf) for r in records), default=math.inf),
               "maximum_absolute_velocity_plus_2c_m_s": max((r.get("maximum_absolute_velocity_plus_2c_m_s", math.inf) for r in records), default=math.inf),
               "maximum_water_beyond_exact_front_m3": max((r.get("water_beyond_exact_front_m3", math.inf) for r in records), default=math.inf),
               "speed_limit_m_s": records[0].get("speed_limit_m_s") if records else None,
               "final_metrics": records[-1] if records else None}
    _write_json(directory / "metrics.json", metrics)
    assert not failures, "\n".join(failures)
