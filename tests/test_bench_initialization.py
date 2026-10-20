"""Bounded continuous-preparation software checks; no physical measurements."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from monsoon import bench_initialization as prepared
from monsoon import bench_model as dry
from monsoon._bench_initialization_worker import _Ledger, _Stationarity
from monsoon.site_data import content_sha256, validate_site_package

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "templates"


def example():
    return [json.loads((FIXTURES / name).read_text()) for name in (
        "synthetic_bench_prepared_site_v2.json", "synthetic_bench_prepared_model_v2.json", "synthetic_bench_prepared_run_v1.json")]


def bind(site, model, spec):
    model["site_package_sha256"] = content_sha256(site)
    spec["continuous_run"]["model_sha256"] = content_sha256(model)
    return site, model, spec


def codes(result):
    return {e["code"] for e in result["errors"]}


def test_contract_preserves_old_dry_run_and_source_binding():
    site, model, spec = example()
    assert validate_site_package(site)["valid"]
    assert prepared.validate_prepared_bench_run(site, model, spec)["valid"]
    assert dry.validate_bench_run(site, model, spec["continuous_run"])["valid"]
    assert not dry.validate_bench_run(site, model, spec)["valid"]
    for source in site["sources"]:
        payload = (FIXTURES / source["uri"].removeprefix("fixture://")).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == source["sha256"]
    assert spec["continuous_run"]["initial_conditions"]["kind"] == "dry_zero_flow"


@pytest.mark.parametrize("mutation,code", [
    (lambda s,m,p: p.update(event_start_s=0), "outside_bench_envelope"),
    (lambda s,m,p: p.update(event_start_s=160), "outside_bench_envelope"),
    (lambda s,m,p: p.update(event_start_s=100.5), "outside_bench_envelope"),
    (lambda s,m,p: p.update(event_start_s=True), "finite_number_required"),
    (lambda s,m,p: p.update(wet_depths={"A": .1}), "unknown_field"),
    (lambda s,m,p: p["preparation"].update(kind="reset_after_preparation"), "unsupported_value"),
    (lambda s,m,p: p["preparation"].update(geometry_at_event={}), "unknown_field"),
    (lambda s,m,p: p["preparation"].update(source_id=[]), "source_required"),
    (lambda s,m,p: p["preparation"]["equilibrium"].update(window_s=0), "outside_bench_envelope"),
    (lambda s,m,p: p["preparation"]["equilibrium"].update(window_s=101), "outside_bench_envelope"),
    (lambda s,m,p: p["preparation"]["equilibrium"].update(flow_range_tolerance_m3_s=1), "outside_bench_envelope"),
    (lambda s,m,p: p["preparation"]["equilibrium"].update(stage_range_tolerance_m=None), "finite_number_required"),
    (lambda s,m,p: p["preparation"]["equilibrium"].update(storage_range_tolerance_m3=float("nan")), "invalid_json"),
    (lambda s,m,p: p["continuous_run"]["initial_conditions"].update(kind="wet"), "unsupported_value"),
    (lambda s,m,p: p["continuous_run"]["initial_conditions"].update(node_depths={"A": .1}), "unknown_field"),
    (lambda s,m,p: p["continuous_run"]["inflows"][0]["points"][0].update(value_m3_s=.001), "wet_initial_boundary"),
    (lambda s,m,p: p["continuous_run"]["receiving_stages"][0]["points"][0].update(stage_m=.23), "wet_initial_boundary"),
    (lambda s,m,p: p["continuous_run"].update(duration_s=501), "routing_budget"),
    (lambda s,m,p: p.update(continuous_run=None), "continuous_run_required"),
])
def test_invalid_preparation_fails_before_execution(mutation, code, tmp_path, monkeypatch):
    site, model, spec = example()
    mutation(site, model, spec)
    def forbidden(*a, **kw):
        pytest.fail("Invalid preparation must not invoke an engine.")
    monkeypatch.setattr(prepared.subprocess, "run", forbidden)
    result = prepared.run_prepared_bench(site, model, spec, tmp_path)
    assert not result["valid"] and result["status"] == "invalid_contract"
    assert code in codes(result)
    assert not list(tmp_path.iterdir())


def test_reporting_and_stationarity_grids_are_exact():
    site, model, spec = example()
    model["numerics"]["report_step_s"] = 4
    spec["event_start_s"] = 102
    assert "event_report_grid" in codes(prepared.validate_prepared_bench_run(*bind(site, model, spec)))
    spec["event_start_s"] = 100
    spec["preparation"]["equilibrium"]["window_s"] = 22
    assert "equilibrium_report_grid" in codes(prepared.validate_prepared_bench_run(*bind(site, model, spec)))


def test_stationarity_requires_all_boundary_knots_constant_inside_window():
    site, model, spec = example()
    points = spec["continuous_run"]["inflows"][0]["points"]
    points.extend([{"elapsed_s": 80, "value_m3_s": 0}, {"elapsed_s": 90, "value_m3_s": 1e-5}])
    points.sort(key=lambda p: p["elapsed_s"])
    report = prepared.validate_prepared_bench_run(site, model, spec)
    assert "nonconstant_equilibrium_forcing" in codes(report)


def test_not_claimed_has_no_hidden_tolerance_fields_and_json_is_strict():
    site, model, spec = example()
    spec["preparation"]["equilibrium"] = {"kind": "not_claimed"}
    assert prepared.validate_prepared_bench_run(site, model, spec)["valid"]
    spec["preparation"]["equilibrium"]["window_s"] = 20
    assert "unknown_field" in codes(prepared.validate_prepared_bench_run(site, model, spec))
    assert not prepared.validate_prepared_bench_run(site, model, '{"event_start_s":0,"event_start_s":1}')["valid"]


def fake_state(t, water=2.0, outflow=0.0, flow=0.0):
    return {"elapsed_s": t, "storage_m3": water, "stage_m": {"A": 1}, "node_depth_m": {"A": 1},
            "link_depth_m": {"L": .1}, "node_storage_m3": {"A": water - .1}, "link_storage_m3": {"L": .1},
            "inflow_m3_s": {"A": 0}, "outflow_m3_s": {"O": outflow}, "spill_m3_s": {"A": 0},
            "link_flow_m3_s": {"L": flow}, "node_total_inflow_m3_s": {"A": flow},
            "node_total_outflow_m3_s": {"A": flow}, "node_lateral_inflow_m3_s": {"A": 0}}


def test_signed_zero_crossing_and_shared_phase_state_are_not_double_counted():
    spec = {"inflows": [{"node_id": "A", "points": [{"elapsed_s":0,"value_m3_s":0},{"elapsed_s":2,"value_m3_s":0}]}]}
    a, b, c = fake_state(0, 2, -.2), fake_state(1, 2.1, 0), fake_state(2, 2, .2)
    whole, pre, event = _Ledger(a), _Ledger(a), _Ledger(b)
    whole.add(a, b)
    whole.add(b, c)
    pre.add(a, b)
    event.add(b, c)
    rows = [x.finish(spec) for x in (whole, pre, event)]
    assert all(x["balance_passed"] and x["cumulative_balance_passed"] for x in rows)
    assert rows[0]["receiving_backflow_m3"] == pytest.approx(.1)
    assert rows[0]["discharge_m3"] == pytest.approx(.1)
    assert rows[1]["final_storage_m3"] == rows[2]["initial_storage_m3"] == 2.1
    assert rows[1]["receiving_backflow_m3"] == .1 and rows[2]["receiving_backflow_m3"] == 0
    assert rows[1]["discharge_m3"] == 0 and rows[2]["discharge_m3"] == .1


def test_endpoint_cancellation_cannot_hide_intermediate_nonconservation():
    spec = {"inflows": [{"node_id": "A", "points": [{"elapsed_s":0,"value_m3_s":0},{"elapsed_s":2,"value_m3_s":0}]}]}
    a, b, c = fake_state(0, 2), fake_state(1, 3), fake_state(2, 2)
    ledger = _Ledger(a)
    ledger.add(a, b)
    ledger.add(b, c)
    report = ledger.finish(spec)
    assert report["balance_passed"]
    assert not report["cumulative_balance_passed"]
    audit = report["cumulative_balance_audit"]
    assert audit["failed_endpoints"] == 1
    assert audit["worst_endpoint"]["mass_balance_residual_m3"] == -1
    assert audit["first_failed_simulation_elapsed_s"] == audit["last_failed_simulation_elapsed_s"] == 1


def test_subreport_transient_fails_stationarity_even_with_matching_endpoints():
    recipe = {"kind": "required_constant_forcing", "window_s": 10, "stage_range_tolerance_m": 1e-4,
              "storage_range_tolerance_m3": 1e-6, "flow_range_tolerance_m3_s": 1e-7}
    checker = _Stationarity(recipe, 10)
    for row in (fake_state(0), fake_state(5, flow=1e-4), fake_state(10)):
        checker.add(row)
    report = checker.finish(5)
    assert report["complete_window"] and not report["passed"]
    assert any(m["metric"] == "link_flow_m3_s:L" and not m["passed"] for m in report["metrics"])


@pytest.fixture(scope="module")
def analytical(tmp_path_factory):
    result = prepared.run_prepared_bench(*example(), tmp_path_factory.mktemp("prepared-analytical"))
    assert result["valid"], result["errors"]
    return result


@pytest.mark.hydraulic
def test_real_engine_known_volume_wet_preparation_then_distinct_event(analytical):
    result = analytical
    assert result["step_halving"]["passed"]
    assert result["step_halving"]["primary_routing_step_s"] == .01
    assert result["step_halving"]["refined_routing_step_s"] == .005
    assert [r["elapsed_s"] for r in result["full_timeseries"]] == list(range(161))
    assert [r["elapsed_s"] for r in result["timeseries"]] == list(range(61))
    assert [r["simulation_elapsed_s"] for r in result["timeseries"]] == list(range(100, 161))
    initial = result["initial_state"]
    assert initial == result["timeseries"][0]
    source = result["full_timeseries"][100]
    assert {k:v for k,v in initial.items() if k != "simulation_elapsed_s"} == {**source, "elapsed_s": 0.0}
    assert initial["node_storage_m3"]["A"] == pytest.approx(.007, abs=3e-6)
    assert initial["stage_m"]["A"] == pytest.approx(.11, abs=3e-5)
    assert result["timeseries"][-1]["node_storage_m3"]["A"] == pytest.approx(.009, abs=3e-6)
    assert result["timeseries"][-1]["stage_m"]["A"] == pytest.approx(.13, abs=3e-5)
    assert initial["link_storage_m3"]["L1"] > 0
    assert initial["link_flow_m3_s"] == {"L1": 0.0}
    assert initial["node_total_inflow_m3_s"] == {"A": 0.0, "O": 0.0}
    assert initial["node_total_outflow_m3_s"] == {"A": 0.0, "O": 0.0}
    for row in result["full_timeseries"]:
        assert row["storage_m3"] == pytest.approx(sum(row["node_storage_m3"].values()) + sum(row["link_storage_m3"].values()), abs=1e-12)
    assert result["initialization"]["state_reset_performed"] is False
    assert not result["physical_equilibration_established"] and not result["physical_validation_established"]
    assert not result["operational_activation_allowed"] and not result["engineering_approval_established"]


@pytest.mark.hydraulic
def test_phase_and_every_routing_endpoint_balances_pass(analytical):
    phases = analytical["phase_balances"]
    assert phases["preparation"]["prescribed_inflow_m3"] == pytest.approx(.007)
    assert phases["evaluation"]["prescribed_inflow_m3"] == pytest.approx(.002)
    assert phases["whole"]["prescribed_inflow_m3"] == pytest.approx(.009)
    assert phases["preparation"]["final_storage_m3"] == phases["evaluation"]["initial_storage_m3"]
    for name, steps in (("preparation", 10000), ("evaluation", 6000), ("whole", 16000)):
        ledger = phases[name]
        assert ledger["balance_passed"] and ledger["cumulative_balance_passed"]
        assert ledger["cumulative_balance_audit"]["checked_endpoints"] == steps + 1
        assert ledger["cumulative_balance_audit"]["failed_endpoints"] == 0
        assert ledger["discharge_m3"] == ledger["receiving_backflow_m3"] == ledger["spill_m3"] == 0
    for field in ("external_inflow_m3", "receiving_backflow_m3", "discharge_m3", "spill_m3"):
        assert phases["preparation"][field] + phases["evaluation"][field] == pytest.approx(phases["whole"][field], abs=1e-12)
    raw = analytical["full_diagnostics"]["raw_routing_totals"]
    assert raw["initStorage"] * .02832 == pytest.approx(phases["whole"]["initial_storage_m3"], rel=1e-12)
    assert raw["finalStorage"] * .02832 == pytest.approx(phases["whole"]["final_storage_m3"], rel=1e-12)


@pytest.mark.hydraulic
def test_requested_stationarity_covers_every_full_node_and_link_state(analytical):
    eq = analytical["equilibrium"]
    assert eq["passed"] and eq["complete_window"]
    assert eq["status"] == "numerically_stationary_window"
    assert eq["routing_state_samples"] == eq["expected_routing_state_samples"] == 2001
    names = {x["metric"] for x in eq["metrics"]}
    assert {"stage_m:A", "node_depth_m:A", "link_depth_m:L1", "node_storage_m3:A", "link_storage_m3:L1",
            "node_total_inflow_m3_s:A", "node_total_outflow_m3_s:A", "node_lateral_inflow_m3_s:A",
            "link_flow_m3_s:L1", "outflow_m3_s:O", "spill_m3_s:A", "storage_m3:SYSTEM"} <= names
    assert all(x["passed"] for x in eq["metrics"])
    comparison = {x["metric"] for x in analytical["step_halving"]["metrics"]}
    assert {"event_initial:node_storage_m3:A", "event_initial:link_storage_m3:L1", "event_initial:link_flow_m3_s:L1"} <= comparison


@pytest.mark.hydraulic
def test_passing_endpoint_does_not_relabel_early_native_failure(tmp_path):
    values = [json.loads((FIXTURES / f"synthetic_bench_prepared_oscillating_{kind}_v2.json").read_text()) for kind in ("site", "model", "run")]
    result = prepared.run_prepared_bench(*values, tmp_path)
    assert not result["valid"] and "cumulative_mass_balance" in codes(result)
    assert result["phase_balances"]["whole"]["balance_passed"]
    audit = result["phase_balances"]["preparation"]["cumulative_balance_audit"]
    assert audit["failed_endpoints"] > 0
    assert audit["first_failed_simulation_elapsed_s"] < audit["last_failed_simulation_elapsed_s"] < 100
    assert audit["maximum_residual_to_tolerance_ratio"] > 1


@pytest.mark.hydraulic
def test_unequilibrated_preparation_cannot_claim_equilibrium(tmp_path):
    site, model, spec = [json.loads((FIXTURES / f"synthetic_bench_prepared_oscillating_{kind}_v2.json").read_text()) for kind in ("site", "model", "run")]
    spec["preparation"]["equilibrium"] = example()[2]["preparation"]["equilibrium"]
    result = prepared.run_prepared_bench(site, model, spec, tmp_path)
    assert not result["valid"] and "equilibrium_unresolved" in codes(result)
    assert result["equilibrium"]["required"] and not result["equilibrium"]["passed"]
    assert any(x["metric"].startswith("link_flow_m3_s:") and not x["passed"] for x in result["equilibrium"]["metrics"])


@pytest.mark.hydraulic
def test_native_evidence_verification_and_tampering(analytical):
    assert prepared.verify_prepared_bench_result(analytical)["valid"]
    assert json.loads(Path(analytical["files"]["result.json"]).read_text()) == analytical
    assert len(analytical["files"]) == 18
    manifest = json.loads(Path(analytical["files"]["manifest.json"]).read_text())
    assert set(manifest["file_sha256"]) == set(analytical["files"]) - {"manifest.json"}
    for name, digest in manifest["file_sha256"].items():
        assert hashlib.sha256(Path(analytical["files"][name]).read_bytes()).hexdigest() == digest
    for prefix in ("base", "half"):
        request = json.loads(Path(analytical["files"][prefix + "/request.json"]).read_text())
        assert request["prepared_run"]["continuous_run"] == request["run"]
        assert request["run"]["initial_conditions"]["kind"] == "dry_zero_flow"
        assert request["prepared_run"]["event_start_s"] == 100
    changed = deepcopy(analytical)
    changed["initial_state"]["storage_m3"] += .001
    assert not prepared.verify_prepared_bench_result(changed)["valid"]
    changed = deepcopy(analytical)
    changed["files"]["../outside"] = analytical["files"]["result.json"]
    assert not prepared.verify_prepared_bench_result(changed)["valid"]
    path = Path(analytical["files"]["half/model.inp"])
    before = path.read_bytes()
    try:
        path.write_bytes(before + b"; changed\n")
        assert not prepared.verify_prepared_bench_result(analytical)["valid"]
    finally:
        path.write_bytes(before)


@pytest.mark.parametrize("mutation", ["missing", "renamed"])
def test_self_consistent_manifest_cannot_omit_required_native_output(analytical, mutation):
    root = Path(analytical["files"]["result.json"]).parent
    original = {name: Path(filename).read_bytes() for name, filename in analytical["files"].items()}
    renamed = root / "half" / "renamed-model.out"

    def reseal(folder, result):
        result["files"] = {p.relative_to(folder).as_posix(): str(p) for p in folder.rglob("*") if p.is_file()}
        (folder / "result.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["file_sha256"] = {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in folder.rglob("*") if p.is_file() and p != manifest_path}
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    try:
        output = root / "half" / "model.out"
        if mutation == "renamed":
            output.rename(renamed)
        else:
            output.unlink()
        child = json.loads((root / "half" / "result.json").read_text())
        reseal(root / "half", child)
        changed = deepcopy(analytical)
        reseal(root, changed)
        manifest = json.loads((root / "manifest.json").read_text())
        assert set(manifest["file_sha256"]) == set(changed["files"]) - {"manifest.json"}
        assert all(hashlib.sha256(Path(changed["files"][name]).read_bytes()).hexdigest() == digest
                   for name, digest in manifest["file_sha256"].items())
        report = prepared.verify_prepared_bench_result(changed)
        assert not report["valid"], "Consistent checksums do not replace a missing required native output."
        assert "expected native" in report["errors"][0]["message"]
    finally:
        if renamed.exists():
            renamed.unlink()
        for name, payload in original.items():
            (root / name).write_bytes(payload)


@pytest.mark.hydraulic
def test_long_native_output_path_preserves_complete_verified_export(tmp_path, analytical):
    import io
    import zipfile
    from monsoon.bench_next_ui import _bundle, _seal_files

    # The native output exceeds MAX_PATH while the child working directory
    # stays below CreateProcess's separate Windows cwd limit.
    directory = tmp_path / ("x" * max(1, 219 - len(str(tmp_path.resolve()))))
    result = prepared.run_prepared_bench(*example(), directory)
    assert result["valid"], result["errors"]
    expected = {"result.json", "manifest.json"} | {
        prefix + "/" + name
        for prefix in ("base", "half")
        for name in ("model.inp", "model.rpt", "model.out", "request.json", "worker.log",
                     "worker-result.json", "result.json", "manifest.json")
    }
    assert len(expected) == 18 and set(result["files"]) == expected
    for prefix in ("base", "half"):
        assert len(result["files"][prefix + "/model.out"]) > 260
        assert Path(result["files"][prefix + "/model.out"]).stat().st_size > 0
        assert Path(result["files"][prefix + "/model.inp"]).read_bytes() == Path(analytical["files"][prefix + "/model.inp"]).read_bytes()
    assert result["full_timeseries"] == analytical["full_timeseries"]
    assert result["phase_balances"] == analytical["phase_balances"]
    assert prepared.verify_prepared_bench_result(result)["valid"]
    seal = _seal_files(result, directory, prepared.verify_prepared_bench_result)
    exported = _bundle(result, seal, directory, prepared.verify_prepared_bench_result)
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == expected
        assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest
                   for name, digest in seal["file_sha256"].items())


def test_worker_rejects_directory_mismatch_before_native_open(tmp_path, monkeypatch):
    from monsoon import _bench_initialization_worker as worker

    directory = tmp_path / "artifact"
    directory.mkdir()
    monkeypatch.chdir(tmp_path)
    def forbidden(*args):
        pytest.fail("A worker outside its artifact directory must not open native input.")
    monkeypatch.setattr(worker.solver, "swmm_open", forbidden)
    worker.run(directory)
    result = json.loads((directory / "worker-result.json").read_text())
    assert not result["valid"] and result["status"] == "failed"
    assert "isolated artifact folder" in result["errors"][0]["message"]


def test_loaded_preparation_source_guard(monkeypatch):
    monkeypatch.setattr(prepared, "_LOADED_SOURCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="changed after import"):
        prepared.prepared_bench_engine_identity()
