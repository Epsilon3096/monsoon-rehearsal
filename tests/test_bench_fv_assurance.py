"""Independent, non-circular accounting and adversarial FV checks.

These tests were specified before candidate holdout execution.  The trace
auditor is also used by the independent frozen-holdout runner.  It rebuilds
balances from actual shared face transfers; reported point flows are never
integrated to create a replacement water ledger.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import chain
import math

import pytest

from monsoon import bench_fv


VOLUME_FLOOR = 1e-6
RELATIVE_BUDGET = 0.01


def _close(a, b, *, absolute=1e-12, relative=1e-10):
    assert math.isfinite(a) and math.isfinite(b), (a, b)
    assert abs(a - b) <= max(absolute, relative * max(abs(a), abs(b))), (a, b)


def _sum(mapping):
    assert isinstance(mapping, dict)
    assert all(math.isfinite(value) for value in mapping.values())
    return math.fsum(mapping.values())


def piecewise_integral(points, end):
    """Independent exact integral of a prescribed piecewise-linear forcing."""
    total = 0.0
    for (left, a), (right, b) in zip(points, points[1:]):
        if left >= end:
            break
        stop = min(right, end)
        at_stop = a + (b - a) * (stop - left) / (right - left)
        total += (stop - left) * (a + at_stop) / 2
    return total


def storage_from_stage(points, stage):
    """Independent geometric integral, without calling the candidate curve."""
    assert points[0][0] <= stage <= points[-1][0]
    total = 0.0
    for (bottom, area0), (top, area1) in zip(points, points[1:]):
        if stage <= bottom:
            break
        rise = min(stage, top) - bottom
        total += area0 * rise + .5 * (area1 - area0) * rise * rise / (top - bottom)
    return total


def audit_trace(network, result, *, split_times=(), settings=None):
    """Independently check every system, channel, and compartment interval.

    This is deliberately fail-closed.  Missing transfer or stage-contribution
    fields cannot qualify a result merely because its own diagnostics pass.
    """
    trace = iter(result["routing_trace"])
    first = next(trace)
    assert first["elapsed_s"] == 0.0
    assert first["dt_s"] == 0.0
    channels = {channel["id"]: channel for channel in network["channels"]}
    nodes = set(network["nodes"])
    boundaries = set(network["boundaries"])
    splits = sorted(t for t in split_times if 0 < t < network["duration_s"])
    endpoints = [0.0, *splits, float(network["duration_s"])]
    report_times = [row["elapsed_s"] for row in result["timeseries"]]
    count = round(network["duration_s"] / network["report_step_s"])
    expected = [i * network["report_step_s"] for i in range(count + 1)]
    assert len(report_times) == len(expected)
    assert all(abs(a - b) <= 1e-11 for a, b in zip(report_times, expected))
    max_residual = max_interval_residual = max_local_residual = 0.0
    cumulative = dict(inflow=0.0, backflow=0.0, discharge=0.0, spill=0.0)
    initial = first["storage_m3"]
    phase_initial = initial
    phase_cumulative = {key: 0.0 for key in cumulative}
    phases = []
    phase_index = 0
    report_lookup = {row["elapsed_s"]: row for row in result["timeseries"]}
    back_by_boundary = {nid: 0.0 for nid in boundaries}
    discharge_by_boundary = {nid: 0.0 for nid in boundaries}
    spill_by_node = {nid: 0.0 for nid in nodes}
    report_endpoints_seen = set()
    previous = None

    for row_index, row in enumerate(chain((first,), trace)):
        assert set(row["node_storage_m3"]) == nodes
        assert set(row["link_storage_m3"]) == set(channels)
        assert all(v >= 0.0 and math.isfinite(v) for v in
                   [row["storage_m3"], *row["node_storage_m3"].values(), *row["link_storage_m3"].values()])
        _close(row["storage_m3"], _sum(row["node_storage_m3"]) + _sum(row["link_storage_m3"]))
        if row["elapsed_s"] in report_lookup:
            report_endpoints_seen.add(row["elapsed_s"])
            report = report_lookup[row["elapsed_s"]]
            _close(report["storage_m3"], row["storage_m3"])
            for nid in nodes:
                _close(report["node_storage_m3"][nid], row["node_storage_m3"][nid])
                _close(storage_from_stage(network["nodes"][nid]["stage_area"], report["stage_m"][nid]), row["node_storage_m3"][nid])
            for cid in channels:
                _close(report["link_storage_m3"][cid], row["link_storage_m3"][cid])
        if row_index == 0:
            previous = row
            continue
        assert previous["elapsed_s"] < row["elapsed_s"] <= endpoints[phase_index + 1]
        _close(row["dt_s"], row["elapsed_s"] - previous["elapsed_s"], absolute=2e-11)
        assert row["dt_s"] > 0
        if settings is not None:
            assert row["dt_s"] <= settings["max_step_s"] * (1 + 1e-9)
            assert 0 <= row["maximum_cfl"] <= settings["cfl"] * (1 + 1e-8)
            assert row_index <= settings["maximum_steps"]
        incoming = row["interval_external_inflow_by_node_m3"]
        spill = row["interval_spill_by_node_m3"]
        up = row["interval_channel_upstream_m3"]
        down = row["interval_channel_downstream_m3"]
        entering = row["interval_receiving_by_boundary_m3"]
        exiting = row["interval_discharge_by_boundary_m3"]
        stage1 = row["boundary_exchange_stage_1_m3"]
        stage2 = row["boundary_exchange_stage_2_m3"]
        assert set(up) == set(down) == set(channels)
        assert set(entering) == set(exiting) == set(stage1) == set(stage2) == boundaries
        assert set(incoming) <= nodes and set(spill) <= nodes
        assert all(v >= 0 for mapping in (incoming, spill, entering, exiting) for v in mapping.values())
        interval = {"inflow": row["interval_external_inflow_m3"],
                    "backflow": row["interval_receiving_backflow_m3"],
                    "discharge": row["interval_discharge_m3"], "spill": row["interval_spill_m3"]}
        for key, mapping in (("inflow", incoming), ("backflow", entering), ("discharge", exiting), ("spill", spill)):
            _close(interval[key], _sum(mapping))
            assert interval[key] >= 0
        for boundary in boundaries:
            # Each RK stage is a separately applied signed transfer, positive
            # outward. Split its sign before combining the two contributions.
            _close(entering[boundary], max(-stage1[boundary], 0) + max(-stage2[boundary], 0))
            _close(exiting[boundary], max(stage1[boundary], 0) + max(stage2[boundary], 0))
            outward = math.fsum(down[cid] for cid, channel in channels.items() if channel["to_node"] == boundary)
            outward -= math.fsum(up[cid] for cid, channel in channels.items() if channel["from_node"] == boundary)
            _close(exiting[boundary] - entering[boundary], outward)
            back_by_boundary[boundary] += entering[boundary]
            discharge_by_boundary[boundary] += exiting[boundary]
        for cid in channels:
            change = row["link_storage_m3"][cid] - previous["link_storage_m3"][cid]
            expected_change = up[cid] - down[cid]
            max_local_residual = max(max_local_residual, abs(change - expected_change))
            _close(change, expected_change)
        for nid in nodes:
            spill_by_node[nid] += spill.get(nid, 0)
            change = row["node_storage_m3"][nid] - previous["node_storage_m3"][nid]
            expected_change = incoming.get(nid, 0) - spill.get(nid, 0)
            expected_change += math.fsum(down[cid] for cid, channel in channels.items() if channel["to_node"] == nid)
            expected_change -= math.fsum(up[cid] for cid, channel in channels.items() if channel["from_node"] == nid)
            max_local_residual = max(max_local_residual, abs(change - expected_change))
            _close(change, expected_change)
        change = row["storage_m3"] - previous["storage_m3"]
        expected_change = interval["inflow"] + interval["backflow"] - interval["discharge"] - interval["spill"]
        max_interval_residual = max(max_interval_residual, abs(change - expected_change))
        _close(change, expected_change)
        for key in cumulative:
            cumulative[key] += interval[key]
            phase_cumulative[key] += interval[key]
        residual = initial + cumulative["inflow"] + cumulative["backflow"] - cumulative["discharge"] - cumulative["spill"] - row["storage_m3"]
        tolerance = max(VOLUME_FLOOR, RELATIVE_BUDGET * (initial + cumulative["inflow"] + cumulative["backflow"]))
        assert abs(residual) <= tolerance
        max_residual = max(max_residual, abs(residual))
        phase_residual = phase_initial + phase_cumulative["inflow"] + phase_cumulative["backflow"] - phase_cumulative["discharge"] - phase_cumulative["spill"] - row["storage_m3"]
        phase_tolerance = max(VOLUME_FLOOR, RELATIVE_BUDGET * (phase_initial + phase_cumulative["inflow"] + phase_cumulative["backflow"]))
        assert abs(phase_residual) <= phase_tolerance
        # This independent forcing integral detects missing/fabricated first or
        # final intervals even if the internal mass ledger balances itself.
        oracle_inflow = math.fsum(piecewise_integral(points, row["elapsed_s"]) for points in network["inflows"].values())
        _close(cumulative["inflow"], oracle_inflow, absolute=1e-11)
        if row["elapsed_s"] == endpoints[phase_index + 1]:
            phases.append({"start_s": endpoints[phase_index], "end_s": row["elapsed_s"],
                           "initial_storage_m3": phase_initial, "final_storage_m3": row["storage_m3"],
                           **phase_cumulative, "residual_m3": phase_residual, "tolerance_m3": phase_tolerance})
            phase_initial = row["storage_m3"]
            phase_cumulative = {key: 0.0 for key in cumulative}
            phase_index += 1
        previous = row
    last = previous
    endpoint_count = row_index + 1
    assert last["elapsed_s"] == network["duration_s"]
    assert report_endpoints_seen == set(report_lookup)
    assert phase_index == len(endpoints) - 1
    for key in cumulative:
        _close(math.fsum(phase[key] for phase in phases), cumulative[key])
    final = result["final_state"]
    assert final["elapsed_s"] == network["duration_s"]
    assert set(final["nodes"]) == nodes
    for nid in nodes:
        _close(final["nodes"][nid]["volume_m3"], last["node_storage_m3"][nid])
        _close(storage_from_stage(network["nodes"][nid]["stage_area"], final["nodes"][nid]["stage_m"]),
               last["node_storage_m3"][nid])
    for cid, channel in channels.items():
        state = final["channels"][cid]
        depth = state["depth_m"]
        assert depth and all(math.isfinite(h) and h >= 0 for h in depth)
        storage = math.fsum(depth) * state["dx_m"] * channel["width_m"]
        _close(storage, last["link_storage_m3"][cid])
    published_phases = result["phase_balances"]
    assert set(published_phases) == {"whole", *("phase_" + str(i + 1) for i in range(len(phases)))}
    quantities = {"inflow": "external_inflow_m3", "backflow": "receiving_backflow_m3",
                  "discharge": "discharge_m3", "spill": "spill_m3"}
    for index, phase in enumerate(phases):
        published = published_phases["phase_" + str(index + 1)]
        assert published["passed"] is True
        for field in ("start_s", "end_s", "initial_storage_m3", "final_storage_m3", "residual_m3", "tolerance_m3"):
            _close(phase[field], published[field])
        for key, field in quantities.items():
            _close(phase[key], published[field])
    whole = published_phases["whole"]
    assert whole["passed"] is True and whole["start_s"] == 0.0 and whole["end_s"] == network["duration_s"]
    _close(whole["initial_storage_m3"], initial)
    _close(whole["final_storage_m3"], last["storage_m3"])
    diagnostics = result["diagnostics"]
    for key, field in quantities.items():
        _close(whole[field], cumulative[key])
        _close(diagnostics[field], cumulative[key])
    for label, values in (("backflow_by_outfall_m3", back_by_boundary),
                          ("discharge_by_outfall_m3", discharge_by_boundary), ("spill_by_node_m3", spill_by_node)):
        assert set(diagnostics[label]) == set(values)
        for nid in values:
            _close(diagnostics[label][nid], values[nid])
    _close(diagnostics["initial_storage_m3"], initial)
    _close(diagnostics["final_storage_m3"], last["storage_m3"])
    assert diagnostics["step_count"] == endpoint_count - 1
    assert diagnostics["completed_duration_s"] == network["duration_s"]
    if settings is not None:
        for name, diagnostic in (("cells_per_channel", "cells_per_channel"), ("cfl", "requested_cfl"),
                                 ("max_step_s", "max_step_s"), ("spatial_order", "spatial_order"),
                                 ("maximum_steps", "maximum_steps")):
            assert settings[name] == diagnostics[diagnostic]
    return {"passed": True, "endpoints_checked": endpoint_count, "intervals_checked": endpoint_count - 1,
            "maximum_cumulative_residual_m3": max_residual,
            "maximum_interval_residual_m3": max_interval_residual,
            "maximum_local_control_volume_residual_m3": max_local_residual,
            "initial_storage_m3": initial, "final_storage_m3": last["storage_m3"],
            "gross_volumes_m3": cumulative, "phases": phases}


def _network():
    return {"nodes": {"A": {"invert_m": 0.0, "maximum_stage_m": .20, "stage_area": [[0, .02], [.2, .02]]},
                      "B": {"invert_m": 0.0, "maximum_stage_m": .20, "stage_area": [[0, .03], [.2, .03]]}},
            "channels": [{"id": "AB", "from_node": "A", "to_node": "B", "length_m": .8,
                          "width_m": .08, "inlet_invert_m": 0., "outlet_invert_m": 0., "height_m": .2, "roughness_n": .012},
                         {"id": "BO", "from_node": "B", "to_node": "O", "length_m": .5,
                          "width_m": .06, "inlet_invert_m": 0., "outlet_invert_m": 0., "height_m": .2, "roughness_n": .012}],
            "inflows": {"A": [[0, 0], [.13, .0003], [.27, .0001], [.57, .0002], [.8, .00017]]},
            "boundaries": {"O": [[0, 0], [.2, .025], [.5, .005], [.8, .03]]},
            "duration_s": .8, "report_step_s": .1}


def _run(network, **kwargs):
    return bench_fv.simulate(network, cells_per_channel=16, max_step_s=.004, cfl=.4,
                             split_times=(.31, .51), **kwargs)


def test_every_shared_transfer_and_cumulative_phase_is_accounted():
    network = _network()
    result = _run(network)
    assert result["valid"], result.get("errors")
    audit = audit_trace(network, result, split_times=(.31, .51))
    assert audit["initial_storage_m3"] == 0.0
    assert audit["gross_volumes_m3"]["backflow"] > 0.0


def test_dry_zero_contains_no_numerical_film_or_invented_flux():
    network = _network()
    network["inflows"] = {"A": [[0, 0], [.8, 0]]}
    network["boundaries"] = {"O": [[0, 0], [.8, 0]]}
    result = _run(network)
    assert result["valid"], result.get("errors")
    audit = audit_trace(network, result, split_times=(.31, .51))
    assert audit["gross_volumes_m3"] == dict(inflow=0., backflow=0., discharge=0., spill=0.)
    assert all(row["storage_m3"] == 0. for row in result["routing_trace"])
    assert all(q == 0. for row in result["timeseries"] for q in row["link_flow_m3_s"].values())


def test_vertical_datum_does_not_change_flow_volume_or_relative_stage():
    network = _network()
    shifted = deepcopy(network)
    offset = 30.125
    for node in shifted["nodes"].values():
        node["invert_m"] += offset
        node["maximum_stage_m"] += offset
        for pair in node["stage_area"]:
            pair[0] += offset
    for channel in shifted["channels"]:
        channel["inlet_invert_m"] += offset
        channel["outlet_invert_m"] += offset
    for points in shifted["boundaries"].values():
        for pair in points:
            pair[1] += offset
    a, b = _run(network), _run(shifted)
    assert a["valid"] and b["valid"], (a.get("errors"), b.get("errors"))
    for left, right in zip(a["timeseries"], b["timeseries"]):
        _close(left["storage_m3"], right["storage_m3"], absolute=1e-10)
        for nid in left["stage_m"]:
            _close(left["stage_m"][nid], right["stage_m"][nid] - offset, absolute=1e-10)
        for cid in left["link_flow_m3_s"]:
            _close(left["link_flow_m3_s"][cid], right["link_flow_m3_s"][cid], absolute=1e-10)


def test_unconnected_water_cannot_be_allocated_to_other_boundary():
    network = _network()
    augmented = deepcopy(network)
    augmented["nodes"]["ISOLATED"] = {"invert_m": 0., "maximum_stage_m": 1., "stage_area": [[0., .3], [1., .3]]}
    base = _run(network)
    other = _run(augmented, initial_state={"nodes": {"ISOLATED": {"volume_m3": .036}}})
    assert base["valid"] and other["valid"], (base.get("errors"), other.get("errors"))
    for left, right in zip(base["timeseries"], other["timeseries"]):
        for nid in left["outflow_m3_s"]:
            _close(left["outflow_m3_s"][nid], right["outflow_m3_s"][nid])
        for cid in left["link_flow_m3_s"]:
            _close(left["link_flow_m3_s"][cid], right["link_flow_m3_s"][cid])
        _close(right["storage_m3"] - left["storage_m3"], .036)


def test_compartment_overflow_is_explicit_collector_water():
    network = {"nodes": {"P": {"invert_m": 0., "maximum_stage_m": .02, "stage_area": [[0., .01], [.02, .01]]}},
               "channels": [], "inflows": {"P": [[0., .001], [1., .001]]}, "boundaries": {},
               "duration_s": 1., "report_step_s": .1}
    result = bench_fv.simulate(network, max_step_s=.007, split_times=(.2, .61))
    assert result["valid"], result.get("errors")
    audit = audit_trace(network, result, split_times=(.2, .61))
    _close(audit["final_storage_m3"], .0002)
    _close(audit["gross_volumes_m3"]["spill"], .0008)


def test_single_interval_capacity_crossing_matches_exact_collector_solution():
    network = {"nodes": {"P": {"invert_m": 0., "maximum_stage_m": .02, "stage_area": [[0., .01], [.02, .01]]}},
               "channels": [], "inflows": {"P": [[0., 0.], [.25, .002]]}, "boundaries": {},
               "duration_s": .25, "report_step_s": .25}
    result = bench_fv.simulate(network, max_step_s=.25, split_times=())
    assert result["valid"], result.get("errors")
    audit = audit_trace(network, result)
    # Exact inflow is 0.25 L, capacity 0.20 L. Conservation alone would also
    # admit an underfilled compartment paired with too much collector water.
    _close(audit["final_storage_m3"], .0002)
    _close(audit["gross_volumes_m3"]["spill"], .00005)


def test_variable_area_compartment_filling_matches_independent_geometry():
    network = {"nodes": {"P": {"invert_m": .4, "maximum_stage_m": .5,
                              "stage_area": [[.4, .01], [.43, .025], [.5, .018]]}},
               "channels": [], "inflows": {"P": [[0., 0.], [.4, .001], [1.2, .001], [2., .0005]]},
               "boundaries": {}, "duration_s": 2., "report_step_s": .1}
    result = bench_fv.simulate(network, max_step_s=.013, split_times=(.73, 1.36))
    assert result["valid"], result.get("errors")
    audit = audit_trace(network, result, split_times=(.73, 1.36))
    _close(audit["final_storage_m3"], .0016)
    assert audit["gross_volumes_m3"]["spill"] == 0.0
    for row in result["timeseries"]:
        expected_volume = piecewise_integral(network["inflows"]["P"], row["elapsed_s"])
        _close(storage_from_stage(network["nodes"]["P"]["stage_area"], row["stage_m"]["P"]), expected_volume)


@pytest.mark.parametrize("mutation", [
    lambda n: n["nodes"]["A"]["stage_area"][0].__setitem__(1, 0.),
    lambda n: n["nodes"]["A"]["stage_area"][0].__setitem__(1, -0.01),
    lambda n: n["channels"][0].__setitem__("length_m", 0.),
    lambda n: n["channels"][0].__setitem__("width_m", float("nan")),
    lambda n: n["channels"][0].__setitem__("roughness_n", -0.01),
    lambda n: n["channels"][0].__setitem__("inlet_invert_m", .01),
    lambda n: n["channels"][0].__setitem__("to_node", "MISSING"),
    lambda n: n["inflows"]["A"][1].__setitem__(1, -0.0001),
    lambda n: n["boundaries"]["O"][1].__setitem__(0, -.1),
])
def test_invalid_or_unrepresented_network_never_succeeds(mutation):
    network = _network()
    mutation(network)
    result = _run(network)
    assert result["valid"] is False
    assert result["errors"]


def test_negative_initial_water_is_rejected_without_clipping():
    network = _network()
    result = _run(network, initial_state={"nodes": {"A": {"volume_m3": -1e-14}}})
    assert result["valid"] is False
    assert result["errors"]


def test_step_limit_retains_failure_instead_of_reporting_completed_run():
    result = _run(_network(), maximum_steps=1)
    assert result["valid"] is False
    assert result["errors"]
    assert result["status"] != "succeeded"
    if result.get("routing_trace"):
        assert result["routing_trace"][-1]["elapsed_s"] < .8


def test_unrepresented_channel_overtopping_is_rejected():
    result = _run(_network(), initial_state={"channels": {"AB": {"depth_m": .201}}})
    assert result["valid"] is False
    assert any("overtopping" in error["code"] for error in result["errors"])


def test_dry_initial_momentum_is_rejected():
    result = _run(_network(), initial_state={"channels": {"AB": {"depth_m": 0., "unit_discharge_m2_s": .001}}})
    assert result["valid"] is False
    assert result["errors"]


def test_independent_auditor_rejects_gross_reversal_hidden_by_zero_net():
    network = _network()
    network["inflows"] = {"A": [[0, 0], [.8, 0]]}
    network["boundaries"] = {"O": [[0, 0], [.8, 0]]}
    result = _run(network)
    assert result["valid"], result.get("errors")
    # Equal-and-opposite stage transfers retain a zero net volume. A checker
    # that uses only the net boundary ledger would miss this inconsistency.
    result["routing_trace"][1]["boundary_exchange_stage_1_m3"]["O"] = .00001
    result["routing_trace"][1]["boundary_exchange_stage_2_m3"]["O"] = -.00001
    with pytest.raises(AssertionError):
        audit_trace(network, result, split_times=(.31, .51))


def test_independent_auditor_rejects_self_balanced_wrong_forcing():
    network = {"nodes": {"P": {"invert_m": 0., "maximum_stage_m": 1., "stage_area": [[0., .1], [1., .1]]}},
               "channels": [], "inflows": {"P": [[0., .001], [1., .001]]}, "boundaries": {},
               "duration_s": 1., "report_step_s": .1}
    result = bench_fv.simulate(network, max_step_s=.01, split_times=())
    assert result["valid"], result.get("errors")
    audit_trace(network, result)
    network["inflows"]["P"] = [[0., .002], [1., .002]]
    with pytest.raises(AssertionError):
        audit_trace(network, result)


def test_analytical_observer_receives_copies_at_every_actual_endpoint():
    network = _network()
    reference = _run(network)
    observed_times = []

    def destructive_observer(snapshot):
        observed_times.append(snapshot["time_s"])
        for channel in snapshot["channels"].values():
            channel["depth_m"][:] = -100.
            channel["unit_discharge_m2_s"][:] = float("nan")

    observed = _run(network, state_observer=destructive_observer)
    assert observed["valid"] and reference["valid"], (observed.get("errors"), reference.get("errors"))
    assert observed == reference
    assert observed_times == [row["elapsed_s"] for row in reference["routing_trace"]]

