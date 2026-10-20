"""Independent native-engine phase audit; synthetic inputs only, no production edits."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2] / "outputs/monsoon-rehearsal"
sys.path.insert(0, str(PROJECT))
from monsoon.bench_model import build_bench_input, bench_engine_identity
from monsoon.site_data import content_sha256
from swmm.toolkit import solver
from swmm.toolkit.shared_enum import LinkResult, NodeResult


def run_probe(step):
    site, model, run = [json.loads((PROJECT / "data/templates" / f"synthetic_bench_{k}_v1.json").read_text())
                        for k in ("site", "model", "run")]
    model["numerics"]["routing_step_s"] = step
    run["model_sha256"] = content_sha256(model)
    run["inflows"][0]["points"] = [{"elapsed_s": 0, "value_m3_s": 0}, {"elapsed_s": 120, "value_m3_s": 0}]
    run["receiving_stages"][0]["points"] = [{"elapsed_s": t, "stage_m": h}
        for t, h in [(0, 0), (20, .06), (50, .06), (90, 0), (120, 0)]]
    # Build with the supported public minimum, then change only ROUTING_STEP for
    # the explicitly labelled diagnostic half-step. Native input is retained.
    if step < .01:
        from monsoon.bench_model import _input, _validate
        check, snapshot = _validate(site, model, run, _refinement=True)
        assert check["valid"], check["errors"]
        inp = _input(snapshot)
    else:
        inp = build_bench_input(site, model, run)
    folder = Path(tempfile.mkdtemp(prefix=f"native-phase-{step}-", dir=Path(__file__).parent))
    (folder / "model.inp").write_text(inp, encoding="utf-8")
    solver.swmm_open(str(folder / "model.inp"), str(folder / "model.rpt"), str(folder / "model.out"))
    solver.swmm_start(True)
    ni = {n["id"]: solver.project_get_index(solver.swmm_NODE, n["id"]) for n in site["nodes"]}
    li = {l["id"]: solver.project_get_index(solver.swmm_LINK, l["id"]) for l in site["links"]}

    def current(t):
        node_volumes = {k: solver.node_get_result(v, NodeResult.VOLUME.value) for k, v in ni.items()}
        link_volumes = {k: solver.link_get_result(v, LinkResult.VOLUME.value) for k, v in li.items()}
        outgoing = solver.node_get_result(ni["O"], NodeResult.TOTAL_OUTFLOW.value)
        incoming = solver.node_get_result(ni["O"], NodeResult.TOTAL_INFLOW.value)
        return {"elapsed_s": t, "storage_m3": sum(node_volumes.values()) + sum(link_volumes.values()),
                "node_storage_m3": node_volumes, "link_storage_m3": link_volumes,
                "outfall_exchange_m3_s": -outgoing if outgoing > 0 else incoming,
                "outfall_total_inflow_m3_s": incoming, "outfall_total_outflow_m3_s": outgoing,
                "outfall_link_flow_m3_s": solver.link_get_result(li["L2"], LinkResult.FLOW.value),
                "stage_m": {k: solver.node_get_result(v, NodeResult.HEAD.value) for k, v in ni.items()}}

    initial = previous = current(0)
    cumulative_signed = 0.0
    records = []
    steps = 0
    maximum_clock_difference_s = 0.0
    while True:
        native_days = solver.swmm_step()
        steps += 1
        t = native_days * 86400 if native_days > 0 else 120.0
        maximum_clock_difference_s = max(maximum_clock_difference_s, abs(t - steps * step))
        row = current(t)
        cumulative_signed += (row["outfall_exchange_m3_s"] + previous["outfall_exchange_m3_s"]) * (t - previous["elapsed_s"]) / 2
        if any(abs(t - stamp) < 1e-7 for stamp in (20, 49.99, 50, 50.01, 90, 120)):
            totals = solver.system_get_routing_totals()
            raw = {k: getattr(totals, k) for k in ("exInflow", "outflow", "flooding", "initStorage", "finalStorage", "pctError")}
            row.update(raw_routing_totals=raw,
                       raw_storage_as_m3=raw["finalStorage"] * .02832,
                       independent_cumulative_signed_outflow_m3=cumulative_signed,
                       independent_residual_m3=initial["storage_m3"] - cumulative_signed - row["storage_m3"],
                       native_cumulative_residual_m3=raw["initStorage"] * .02832 + raw["exInflow"] - raw["outflow"] - raw["flooding"] - raw["finalStorage"] * .02832)
            records.append(row)
        previous = row
        if native_days <= 0:
            break
    solver.swmm_end()
    solver.swmm_report()
    solver.swmm_close()
    result = {"evidence_kind": "synthetic_fixture", "purpose": "Independent native cumulative balance/clock/storage probe; not physical validation",
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "engine_identity": bench_engine_identity(),
              "step_s": step, "routing_steps": steps, "maximum_clock_difference_s": maximum_clock_difference_s,
              "initial_state": initial, "records": records,
              "physical_validation_established": False, "operational_activation_allowed": False}
    (folder / "probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"folder": str(folder), "step_s": step, "clock_difference_s": maximum_clock_difference_s,
                      "records": [{k: r[k] for k in ("elapsed_s", "storage_m3", "raw_storage_as_m3", "independent_residual_m3", "native_cumulative_residual_m3", "outfall_exchange_m3_s", "outfall_link_flow_m3_s", "raw_routing_totals")} for r in records]}))


if __name__ == "__main__":
    run_probe(float(sys.argv[1]))
