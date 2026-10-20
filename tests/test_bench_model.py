"""Synthetic software verification only; none of these tests is physical proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from monsoon import bench_model as bench
from monsoon.site_data import content_sha256, validate_site_package

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "templates"


def example():
    return [json.loads((FIXTURES / f"synthetic_bench_{name}_v1.json").read_text()) for name in ("site", "model", "run")]


def bind(site, model, run):
    model["site_package_sha256"] = content_sha256(site)
    run["model_sha256"] = content_sha256(model)
    return site, model, run


def codes(report):
    return {e["code"] for e in report["errors"]}


def test_strict_fixture_and_inert_contract():
    site, model, run = example()
    assert validate_site_package(site)["valid"]
    report = bench.validate_bench_run(site, model, run)
    assert report["valid"] and report["evidence_kind"] == "synthetic_fixture"
    assert not report["physical_validation_established"]
    assert not report["operational_activation_allowed"]
    assert bench.validate_bench_model(site, model)["valid"]
    assert "[JUNCTIONS]" not in bench.build_bench_input(site, model, run)
    assert "TABULAR" in bench.build_bench_input(site, model, run)


@pytest.mark.parametrize("value", [True, None, "0.01", float("nan"), float("inf"), -1, 0, 1e100, 10**500])
def test_bad_numerics_fail_closed_before_subprocess(value, tmp_path, monkeypatch):
    site, model, run = example()
    model["numerics"]["routing_step_s"] = value
    def forbidden(*a, **kw):
        pytest.fail("Invalid contract must not invoke the engine")
    monkeypatch.setattr(bench.subprocess, "run", forbidden)
    result = bench.run_bench_model(site, model, run, tmp_path)
    assert not result["valid"] and result["status"] == "invalid_contract"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mutation,code", [
    (lambda s,m,r: m.update(extra="unknown"), "unknown_field"),
    (lambda s,m,r: m["junction_storage"].clear(), "incomplete_inventory"),
    (lambda s,m,r: m["overflow"].pop(), "incomplete_inventory"),
    (lambda s,m,r: s["boundaries"]["spill_node_ids"].remove("A"), "incomplete_spill_inventory"),
    (lambda s,m,r: m["link_parameters"][0].update(link_id=[]), "unknown_asset"),
    (lambda s,m,r: m["junction_storage"][0]["stage_area"].append({"stage_m":0.3,"area_m2":0.015}), "outside_bench_envelope"),
    (lambda s,m,r: m["numerics"].update(minimum_surface_area_m2=0.5), "oversized_numerical_area"),
    (lambda s,m,r: m["numerics"].update(routing_step_s=0.03), "unaligned_steps"),
    (lambda s,m,r: m["numerics"].update(routing_step_s=0.005), "outside_bench_envelope"),
    (lambda s,m,r: r["initial_conditions"].update(kind="equilibrated"), "unsupported_value"),
    (lambda s,m,r: r["initial_conditions"].update(node_depths={"A":0.1}), "unknown_field"),
    (lambda s,m,r: r["receiving_stages"][0]["points"][0].update(stage_m=0.05), "wet_initial_boundary"),
    (lambda s,m,r: r["inflows"][0]["points"][0].update(value_m3_s=0.001), "wet_initial_boundary"),
    (lambda s,m,r: r["inflows"][0]["points"].pop(), "boundary_coverage"),
    (lambda s,m,r: r["inflows"][0]["points"][1].update(elapsed_s=0), "time_order"),
    (lambda s,m,r: r["inflows"][0]["points"][1].update(value_m3_s=-0.01), "outside_bench_envelope"),
    (lambda s,m,r: r.update(duration_s=3601), "outside_bench_envelope"),
    (lambda s,m,r: r.update(duration_s=1000), "routing_budget"),
    (lambda s,m,r: m.update(evidence_kind="supplied_bench_model"), "unsupported_value"),
    (lambda s,m,r: m["losses"].update(leakage="unknown"), "unsupported_value"),
])
def test_unsupported_or_missing_state(mutation, code):
    site, model, run = example()
    mutation(site, model, run)
    report = bench.validate_bench_run(*bind(site, model, run))
    assert not report["valid"] and code in codes(report)


def test_duplicate_and_nonfinite_json_rejected():
    site, model, run = example()
    assert not bench.validate_bench_run(site, '{"schema_version":1,"schema_version":2}', run)["valid"]
    assert not bench.validate_bench_run(site, model, '{"value":NaN}')["valid"]
    nested = {}
    for _ in range(70):
        nested = {"x": nested}
    assert not bench.validate_bench_run(site, nested, run)["valid"]


def test_geometry_is_explicit_and_all_supported_shapes_translate():
    for shape, expected in [({"shape":"circular", "diameter_m":0.08}, "CIRCULAR 0.08"),
                            ({"shape":"trapezoid", "bottom_width_m":0.04,"height_m":0.25,"left_slope_h_per_v":1,"right_slope_h_per_v":2}, "TRAPEZOIDAL 0.25 0.04 1 2")]:
        site, model, run = example()
        site["links"][0]["cross_section"] = shape
        assert expected in bench.build_bench_input(*bind(site, model, run))


def test_initial_parameter_and_current_source_identity_explicit(monkeypatch):
    site, model, run = example()
    model["numerics"].pop("initial_numerical_storage_tolerance_m3")
    assert not bench.validate_bench_model(site, model)["valid"]
    monkeypatch.setattr(bench, "_LOADED_SOURCE_SHA256", "0"*64)
    with pytest.raises(ValueError, match="changed after import"):
        bench.bench_engine_identity()


@pytest.fixture(scope="module")
def pulse(tmp_path_factory):
    result = bench.run_bench_model(*example(), tmp_path_factory.mktemp("synthetic-bench-pulse"))
    assert result["valid"], result["errors"]
    return result


@pytest.mark.hydraulic
def test_real_engine_pulse_units_grid_conservation_and_step_halving(pulse):
    assert pulse["step_halving"]["passed"]
    assert pulse["step_halving"]["primary_routing_step_s"] == 0.01
    assert pulse["step_halving"]["refined_routing_step_s"] == 0.005
    rows, d = pulse["timeseries"], pulse["diagnostics"]
    assert [r["elapsed_s"] for r in rows] == list(range(121))
    assert d["routing_steps"] == 12000
    assert d["minimum_actual_step_s"] == pytest.approx(0.01, abs=1e-8)
    assert d["maximum_actual_step_s"] == pytest.approx(0.01, abs=1e-8)
    assert d["prescribed_inflow_m3"] == pytest.approx(0.007)
    assert abs(d["mass_balance_residual_m3"]) < 1e-5
    assert d["final_storage_m3"] + d["discharge_m3"] == pytest.approx(d["initial_storage_m3"] + 0.007, abs=1e-5)
    assert all(r["storage_m3"] == pytest.approx(sum(r["node_storage_m3"].values()) + sum(r["link_storage_m3"].values()), abs=1e-12) for r in rows)
    for row in rows:
        assert row["node_storage_m3"]["A"] == pytest.approx(0.015 * (row["stage_m"]["A"] - 0.04), abs=1e-10)
        assert row["node_storage_m3"]["S"] == pytest.approx(0.04 * (row["stage_m"]["S"] - 0.02), abs=1e-10)
    assert rows[0]["storage_m3"] > 0  # Pinned engine's real numerical dry-link floor is retained.
    assert rows[0]["storage_m3"] < 1e-5
    # The pinned engine uses rounded UCF(VOLUME)=0.02832, not the exact SI foot cube.
    assert d["raw_routing_totals"]["initStorage"] * 0.02832 == pytest.approx(d["initial_storage_m3"], rel=1e-12)
    assert d["raw_routing_totals"]["finalStorage"] * 0.02832 == pytest.approx(d["final_storage_m3"], rel=1e-12)
    assert set(rows[0]["node_storage_m3"].values()) == {0}
    assert max(sum(r["link_storage_m3"].values()) for r in rows) > 0.0005
    assert not pulse["physical_validation_established"] and not pulse["operational_activation_allowed"]


@pytest.mark.hydraulic
def test_narrower_explicit_geometry_changes_upstream_stage(pulse, tmp_path):
    site, model, run = example()
    site["links"][0]["cross_section"]["width_m"] = 0.04
    narrow = bench.run_bench_model(*bind(site, model, run), tmp_path)
    assert narrow["valid"], narrow["errors"]
    assert narrow["diagnostics"]["maximum_stage_m"]["A"] > pulse["diagnostics"]["maximum_stage_m"]["A"] + 0.005
    assert narrow["site_package_sha256"] != pulse["site_package_sha256"]


@pytest.mark.hydraulic
def test_signed_receiving_backflow_and_later_discharge(tmp_path):
    site, model, run = example()
    run["inflows"][0]["points"] = [{"elapsed_s":0,"value_m3_s":0},{"elapsed_s":120,"value_m3_s":0}]
    run["receiving_stages"][0]["points"] = [{"elapsed_s":t,"stage_m":q} for t,q in [(0,0),(20,0.06),(50,0.06),(90,0),(120,0)]]
    result = bench.run_bench_model(site, model, run, tmp_path)
    assert result["valid"], result["errors"]
    d = result["diagnostics"]
    flows = [r["outflow_m3_s"]["O"] for r in result["timeseries"]]
    assert min(flows) < -0.0001 and max(flows) > 0.0001
    assert d["receiving_backflow_m3"] > 0.01 and d["discharge_m3"] > 0.01
    assert d["external_inflow_m3"] == 0
    assert abs(d["mass_balance_residual_m3"]) < 1e-5
    assert result["timeseries"][20]["receiving_stage_m"]["O"] == 0.06


@pytest.mark.hydraulic
def test_closed_mass_known_inflow_retained_below_raised_outlet(tmp_path):
    site, model, run = example()
    site["nodes"][2].update(invert_m=0.22, ground_m=0.5)
    site["links"][1].update(inlet_invert_m=0.23, outlet_invert_m=0.22)
    run["receiving_stages"][0]["points"] = [{"elapsed_s":0,"stage_m":0.22},{"elapsed_s":120,"stage_m":0.22}]
    result = bench.run_bench_model(*bind(site, model, run), tmp_path)
    assert result["valid"], result["errors"]
    d = result["diagnostics"]
    assert d["discharge_m3"] == 0 and d["spill_m3"] == 0 and d["receiving_backflow_m3"] == 0
    assert d["final_storage_m3"] == pytest.approx(d["initial_storage_m3"] + 0.007, abs=1e-5)


@pytest.mark.hydraulic
def test_zero_forcing_closed_mass_and_no_fabricated_zero_initial_volume(tmp_path):
    site, model, run = example()
    run["inflows"][0]["points"] = [{"elapsed_s":0,"value_m3_s":0},{"elapsed_s":120,"value_m3_s":0}]
    result = bench.run_bench_model(site, model, run, tmp_path)
    assert result["valid"], result["errors"]
    d = result["diagnostics"]
    assert d["final_storage_m3"] == d["initial_storage_m3"] > 0
    assert d["mass_balance_residual_m3"] == 0
    assert d["discharge_m3"] == 0 and d["external_inflow_m3"] == 0


@pytest.mark.hydraulic
def test_missing_lateral_overtopping_path_cannot_pass(tmp_path):
    site, model, run = example()
    for link in site["links"]:
        link["cross_section"]["height_m"] = 0.005
    result = bench.run_bench_model(*bind(site, model, run), tmp_path)
    assert not result["valid"] and "unsupported_lateral_spill" in codes(result)
    assert result["diagnostics"]["unsupported_open_link_overtopping"]
    assert Path(result["files"]["base/model.rpt"]).is_file()
    assert Path(result["files"]["half/model.rpt"]).is_file()
    assert not result["step_halving"]["passed"]


@pytest.mark.hydraulic
def test_manifest_verification_and_no_relabelling_or_tampering(pulse):
    assert bench.verify_bench_result(pulse)["valid"]
    assert json.loads(Path(pulse["files"]["result.json"]).read_text()) == pulse
    assert len(pulse["files"]) == 18
    manifest = json.loads(Path(pulse["files"]["manifest.json"]).read_text())
    assert set(manifest["file_sha256"]) == set(pulse["files"]) - {"manifest.json"}
    for name, digest in manifest["file_sha256"].items():
        assert hashlib.sha256(Path(pulse["files"][name]).read_bytes()).hexdigest() == digest
    changed = deepcopy(pulse)
    changed["timeseries"][1]["storage_m3"] += 0.1
    assert not bench.verify_bench_result(changed)["valid"]
    changed = deepcopy(pulse)
    changed["files"]["../outside"] = pulse["files"]["result.json"]
    assert not bench.verify_bench_result(changed)["valid"]
    target = Path(pulse["files"]["half/model.inp"])
    original = target.read_bytes()
    try:
        target.write_bytes(original + b"; tamper\n")
        assert not bench.verify_bench_result(pulse)["valid"]
    finally:
        target.write_bytes(original)


def test_finer_failure_is_retained_and_cannot_be_accepted(monkeypatch, tmp_path):
    calls = []
    def fake(*args, **kwargs):
        calls.append(kwargs.get("_refinement", False))
        return {"valid":False,"status":"failed","errors":[{"code":"synthetic_failure"}],"timeseries":[],"diagnostics":{},"files":{}}
    monkeypatch.setattr(bench, "_run_attempt", fake)
    result = bench.run_bench_model(*example(), tmp_path)
    assert calls == [False, True]
    assert not result["valid"] and not result["step_halving"]["passed"]


def test_original_fixture_requires_missing_compartment_inventory():
    original = json.loads((FIXTURES / "synthetic_site_v1.json").read_text())
    _, model, run = example()
    model["site_package_sha256"] = content_sha256(original)
    report = bench.validate_bench_model(original, model)
    assert not report["valid"] and "incomplete_spill_inventory" in codes(report)
