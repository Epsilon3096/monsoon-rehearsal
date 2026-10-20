"""Focused solver integration tests; independent oracles live in other suites."""
from copy import deepcopy
import math
import unittest

import numpy as np

from monsoon.bench_fv import StorageCurve, manning_friction, simulate


def network(duration=1.):
    return {"nodes": {"A": {"invert_m": .02, "maximum_stage_m": .22,
                              "stage_area": [[.02, .01], [.22, .01]]}},
            "boundaries": {"O": [[0., 0.], [duration, 0.]]},
            "channels": [{"id": "C", "from_node": "A", "to_node": "O", "length_m": 1.,
                           "width_m": .08, "inlet_invert_m": .02, "outlet_invert_m": 0.,
                           "height_m": .2, "roughness_n": .012}],
            "inflows": {"A": [[0., 0.], [duration, 0.]]},
            "duration_s": duration, "report_step_s": duration / 4}


class ConservativeCoreTests(unittest.TestCase):
    def assert_closed(self, result, net, places=12):
        self.assertTrue(result["valid"], result["errors"])
        trace = result["routing_trace"]
        first = trace[0]["storage_m3"]
        incoming = outgoing = 0.
        for before, after in zip(trace, trace[1:]):
            incoming += after["interval_external_inflow_m3"] + after["interval_receiving_backflow_m3"]
            outgoing += after["interval_discharge_m3"] + after["interval_spill_m3"]
            self.assertAlmostEqual(first + incoming - outgoing, after["storage_m3"], places=places)
            for c in net["channels"]:
                delta = after["link_storage_m3"][c["id"]] - before["link_storage_m3"][c["id"]]
                transfer = after["interval_channel_upstream_m3"][c["id"]] - after["interval_channel_downstream_m3"][c["id"]]
                self.assertAlmostEqual(delta, transfer, places=places)
            for nid in net["nodes"]:
                transfer = after["interval_external_inflow_by_node_m3"][nid] - after["interval_spill_by_node_m3"][nid]
                for c in net["channels"]:
                    if c["from_node"] == nid:
                        transfer -= after["interval_channel_upstream_m3"][c["id"]]
                    if c["to_node"] == nid:
                        transfer += after["interval_channel_downstream_m3"][c["id"]]
                self.assertAlmostEqual(after["node_storage_m3"][nid] - before["node_storage_m3"][nid], transfer, places=places)
            self.assertGreaterEqual(after["minimum_depth_m"], 0.)

    def test_connected_sloping_lake_preserves_water_and_rest(self):
        net = network()
        net["boundaries"]["O"] = [[0., .06], [1., .06]]
        n = 48
        bed = .02 - .02 * (np.arange(n) + .5) / n
        initial = {"nodes": {"A": {"stage_m": .06}},
                   "channels": {"C": {"depth_m": .06 - bed, "unit_discharge_m2_s": 0.}}}
        result = simulate(net, cells_per_channel=n, initial_state=initial)
        self.assert_closed(result, net)
        self.assertLess(np.max(np.abs(np.asarray(result["final_state"]["channels"]["C"]["unit_discharge_m2_s"]))), 1e-12)
        self.assertAlmostEqual(result["final_state"]["nodes"]["A"]["stage_m"], .06, places=12)

    def test_backwater_and_recession_keep_local_control_volumes(self):
        net = network(3.)
        net["boundaries"]["O"] = [[0., 0.], [.8, .035], [1.4, .035], [2.3, 0.], [3., 0.]]
        net["inflows"]["A"] = [[0., 0.], [.4, .0001], [.6, .0001], [1., 0.], [3., 0.]]
        result = simulate(net, cells_per_channel=32, split_times=(.8, 1.4, 2.3))
        self.assert_closed(result, net)
        self.assertGreater(result["diagnostics"]["receiving_backflow_m3"], 0.)
        self.assertGreater(result["diagnostics"]["discharge_m3"], 0.)
        self.assertEqual(result["routing_trace"][-1]["elapsed_s"], 3.)
        self.assertEqual(len(result["phase_balances"]), 5)

    def test_isolated_storage_uses_exact_input_and_accounted_spill(self):
        net = network()
        net["channels"] = []
        net["boundaries"] = {}
        net["nodes"]["A"]["stage_area"] = [[.02, .001], [.22, .003]]
        net["inflows"]["A"] = [[0., 0.], [.1, .002], [.37, .002], [.79, .001], [1., .001]]
        result = simulate(net, max_step_s=.07, split_times=(.37, .79))
        self.assert_closed(result, net)
        expected_input = .0001 + .27 * .002 + .42 * .0015 + .21 * .001
        self.assertAlmostEqual(result["diagnostics"]["external_inflow_m3"], expected_input, places=14)
        self.assertAlmostEqual(result["diagnostics"]["final_storage_m3"], .0004, places=14)
        self.assertAlmostEqual(result["diagnostics"]["spill_m3"], expected_input - .0004, places=14)

    def test_dry_state_has_no_seed_water(self):
        result = simulate(network(), cells_per_channel=12)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(all(r["storage_m3"] == 0. for r in result["routing_trace"]))
        self.assertTrue(all(x == 0. for x in result["final_state"]["channels"]["C"]["depth_m"]))

    def test_budget_and_scope_fail_explicitly(self):
        result = simulate(network(), maximum_steps=2)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "step_limit")
        self.assertLess(result["final_state"]["elapsed_s"], 1.)
        net = network()
        net["boundaries"]["O"] = [[0., .3], [1., .3]]
        result = simulate(net)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "scope_exceeded")
        net = network()
        net["channels"][0]["inlet_invert_m"] += .001
        result = simulate(net)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["code"], "unsupported_offset")

    def test_storage_domains_and_friction_are_explicit(self):
        curve = StorageCurve([[.02, .01], [.12, .02], [.22, .01]])
        for stage in np.linspace(.02, .22, 101):
            self.assertAlmostEqual(curve.stage(curve.volume(stage)), stage, places=13)
        for bad in (-1., curve.capacity_m3 + .001):
            with self.assertRaises(ValueError):
                curve.stage(bad)
        for h in (0., .001, .05):
            q = np.array([-.1, 0., .1])
            damped = manning_friction(h, q, .08, .012, .1)
            self.assertTrue(np.isfinite(damped).all())
            self.assertTrue(np.all(np.abs(damped) <= np.abs(q)))
            self.assertTrue(np.all(damped * q >= 0))


if __name__ == "__main__":
    unittest.main()
