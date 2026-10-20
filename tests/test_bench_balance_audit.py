"""Independent cumulative accounting and evidence barriers; synthetic inputs only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from monsoon import bench_balance_audit as audit
from monsoon import bench_model as bench
from monsoon._bench_balance_worker import _cumulative_checks, _signed_integral

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "templates"


def read(name):
    return json.loads((FIXTURES / name).read_bytes())


def fixture_inputs(kind):
    if kind == "compartment":
        return (read("synthetic_bench_prepared_site_v2.json"), read("synthetic_bench_prepared_model_v2.json"),
                read("synthetic_bench_prepared_run_v1.json")["continuous_run"])
    values = [read(f"synthetic_bench_{name}_v1.json") for name in ("site", "model", "run")]
    if kind == "tailwater":
        values[2]["inflows"][0]["points"] = [{"elapsed_s": 0, "value_m3_s": 0}, {"elapsed_s": 120, "value_m3_s": 0}]
        values[2]["receiving_stages"][0]["points"] = [
            {"elapsed_s": t, "stage_m": h} for t, h in ((0, 0), (20, .06), (50, .06), (90, 0), (120, 0))]
    return values


def hashes(result):
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in result["files"].items()}


@pytest.fixture(scope="module")
def positive(tmp_path_factory):
    directory = tmp_path_factory.mktemp("positive-cumulative-audit")
    parent = bench.run_bench_model(*fixture_inputs("compartment"), directory)
    assert parent["valid"], parent["errors"]
    original = hashes(parent)
    result = audit.audit_bench_balance(parent, directory)
    assert result["valid"], result["errors"]
    return parent, result, original


def test_exact_input_pair_checks_every_routing_endpoint_and_preserves_parent(positive):
    parent, result, original = positive
    assert len(result["files"]) == 18
    assert hashes(parent) == original
    assert bench.verify_bench_result(parent)["valid"]
    assert audit.verify_bench_balance_audit(result, parent)["valid"]
    for label, endpoints in (("base", 16001), ("half", 32001)):
        detail = result["attempts"][label]["diagnostics"]
        assert detail["cumulative_endpoints_checked"] == endpoints
        assert detail["violating_endpoint_count"] == 0
        assert detail["maximum_clock_difference_s"] < 1e-10
        assert detail["maximum_native_live_storage_difference_m3"] < 1e-12
        assert Path(result["files"][label + "/model.inp"]).read_bytes() == Path(parent["files"][label + "/model.inp"]).read_bytes()
        request = json.loads(Path(result["files"][label + "/request.json"]).read_bytes())
        assert request["parent_request_json"].encode("utf-8") == Path(parent["files"][label + "/request.json"]).read_bytes()
        worker = json.loads(Path(result["files"][label + "/worker-result.json"]).read_bytes())
        assert [r["elapsed_s"] for r in worker["report_samples"]] == list(range(161))
        for row in worker["report_samples"]:
            assert row["native_tolerance_m3"] == row["independent_tolerance_m3"]
            assert abs(row["native_cumulative_residual_m3"]) <= row["native_tolerance_m3"]
    assert result["audit_identity"] == audit.bench_balance_audit_identity()
    for key in audit._CLAIMS:
        assert result[key] is False


def test_native_audit_keeps_complete_exact_input_artifacts_beyond_260_character_paths(positive, tmp_path):
    parent, short_result, original = positive
    directory = tmp_path / "packaged evidence with spaces"
    # Reproduce the package failure: a 256-character worker cwd is launchable,
    # while its expected model.out path exceeds the native filename buffer.
    # A cwd over 260 characters has a separate Windows CreateProcess limit.
    padding = 223 - len(str(directory.resolve())) - 1
    assert padding > 0, "The test base directory must leave room for a launchable native worker cwd."
    directory /= "x" * padding
    result = audit.audit_bench_balance(parent, directory)
    assert result["valid"], result["errors"]
    child_names = {"model.inp", "model.rpt", "model.out", "request.json", "worker.log",
                   "worker-result.json", "result.json", "manifest.json"}
    expected = {"result.json", "manifest.json"} | {
        f"{label}/{name}" for label in ("base", "half") for name in child_names}
    assert set(result["files"]) == expected
    assert audit.verify_bench_balance_audit(result, parent)["valid"]
    assert hashes(parent) == original and bench.verify_bench_result(parent)["valid"]
    for label in ("base", "half"):
        native_output = Path(result["files"][label + "/model.out"])
        assert len(str(native_output.resolve())) > 260
        assert len(str(native_output.parent.resolve())) < 260
        assert native_output.stat().st_size > 0
        assert {p.name for p in native_output.parent.iterdir()} == child_names
        assert Path(result["files"][label + "/model.inp"]).read_bytes() == Path(parent["files"][label + "/model.inp"]).read_bytes()
        request = json.loads(Path(result["files"][label + "/request.json"]).read_bytes())
        assert request["parent_request_json"].encode("utf-8") == Path(parent["files"][label + "/request.json"]).read_bytes()
        worker = json.loads(Path(result["files"][label + "/worker-result.json"]).read_bytes())
        short_worker = json.loads(Path(short_result["files"][label + "/worker-result.json"]).read_bytes())
        assert worker["diagnostics"] == short_worker["diagnostics"]
        assert worker["report_samples"] == short_worker["report_samples"]


@pytest.mark.parametrize("kind", ["original_pulse", "tailwater"])
def test_final_balance_and_time_convergence_cannot_hide_intermediate_failure(kind, tmp_path):
    parent = bench.run_bench_model(*fixture_inputs(kind), tmp_path)
    assert parent["valid"] and parent["step_halving"]["passed"]
    result = audit.audit_bench_balance(parent, tmp_path)
    assert not result["valid"] and result["status"] == "numerically_unresolved"
    assert audit.verify_bench_balance_audit(result, parent)["valid"]
    for label in ("base", "half"):
        assert result["attempts"][label]["diagnostics"]["violating_endpoint_count"] > 0
        worker = json.loads(Path(result["files"][label + "/worker-result.json"]).read_bytes())
        last = worker["report_samples"][-1]
        assert abs(last["native_cumulative_residual_m3"]) <= last["native_tolerance_m3"]
        if kind == "tailwater":
            split = next(row for row in worker["report_samples"] if row["elapsed_s"] == 50)
            assert split["native_cumulative_residual_m3"] == pytest.approx(-.001915, abs=2e-6)
            assert split["native_cumulative_residual_m3"] == pytest.approx(split["independent_cumulative_residual_m3"], abs=1e-12)
    assert result["physical_validation_established"] is False


def test_mixed_signed_exchange_uses_gross_entering_water_for_both_budgets():
    # Discharge first, then backflow: cumulative net exchange loses the history.
    outgoing, incoming = 0.0, 0.0
    for before, after in ((.004, .004), (.004, -.006)):
        plus, minus = _signed_integral(before, after, 1.0)
        outgoing += plus
        incoming += minus
    initial, external, storage = .003, .002, .001
    native = {"exInflow": external, "outflow": outgoing - incoming, "flooding": 0, "pctError": 1e-6}
    a, b = _cumulative_checks(2, initial, storage, external, incoming, outgoing, 0, native)
    expected = initial + external + incoming
    assert incoming > 0 and outgoing > incoming
    assert expected > initial + external + max(-native["outflow"], 0)
    assert a["initial_plus_entered_m3"] == pytest.approx(expected)
    assert a["tolerance_m3"] == b["tolerance_m3"] == pytest.approx(.01 * expected)
    assert a["residual_m3"] == pytest.approx(b["residual_m3"])
    assert a["native_net_outflow_m3"] == outgoing - incoming


@pytest.mark.parametrize("nested", ["", "audit-child"])
def test_audit_cannot_write_inside_immutable_parent_pair(positive, monkeypatch, nested):
    parent, _, original = positive
    root = Path(parent["files"]["result.json"]).parent
    def forbidden(*args, **kwargs):
        pytest.fail("Unsafe output placement must fail before invoking a worker.")
    monkeypatch.setattr(audit.subprocess, "run", forbidden)
    result = audit.audit_bench_balance(parent, root / nested)
    assert not result["valid"] and result["status"] == "invalid_parent"
    assert "outside the immutable" in result["errors"][0]["message"]
    assert hashes(parent) == original and bench.verify_bench_result(parent)["valid"]
    if nested:
        assert not (root / nested).exists()


def test_unqualified_parent_fails_before_worker_and_creates_no_artifacts(positive, tmp_path, monkeypatch):
    parent = deepcopy(positive[0])
    parent["valid"] = False
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **kw: pytest.fail("Unqualified parent cannot execute."))
    result = audit.audit_bench_balance(parent, tmp_path)
    assert not result["valid"] and result["status"] == "invalid_parent"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("artifact", ["base/model.inp", "half/worker-result.json", "base/manifest.json"])
def test_any_changed_audit_artifact_blocks_verification(positive, artifact):
    parent, result, _ = positive
    path = Path(result["files"][artifact])
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        assert not audit.verify_bench_balance_audit(result, parent)["valid"]
    finally:
        path.write_bytes(original)
    assert audit.verify_bench_balance_audit(result, parent)["valid"]


def test_wrong_parent_or_in_memory_acceptance_claim_cannot_verify(positive):
    parent, result, _ = positive
    wrong = deepcopy(parent)
    wrong["simulation_sha256"] = "0" * 64
    assert not audit.verify_bench_balance_audit(result, wrong)["valid"]
    changed = deepcopy(result)
    changed["physical_validation_established"] = True
    assert not audit.verify_bench_balance_audit(changed, parent)["valid"]


def test_changed_loaded_audit_source_refuses_execution_and_verification(positive, tmp_path, monkeypatch):
    parent, result, _ = positive
    monkeypatch.setattr(audit, "_LOADED_SHA256", "0" * 64)
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **kw: pytest.fail("Changed source cannot execute."))
    assert not audit.audit_bench_balance(parent, tmp_path)["valid"]
    assert not audit.verify_bench_balance_audit(result, parent)["valid"]
    assert not list(tmp_path.iterdir())


def test_failed_second_attempt_remains_a_failed_inspectable_pair(positive, tmp_path, monkeypatch):
    parent, _, original = positive
    native_run = audit.subprocess.run
    calls = 0
    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
        return native_run(*args, **kwargs)
    monkeypatch.setattr(audit.subprocess, "run", fail_second)
    result = audit.audit_bench_balance(parent, tmp_path)
    assert calls == 2 and not result["valid"]
    assert result["attempts"]["base"]["valid"] is True
    assert result["attempts"]["half"]["valid"] is False
    assert "TimeoutExpired" in result["attempts"]["half"]["errors"][0]["message"]
    assert "half/request.json" in result["files"] and "half/worker.log" in result["files"]
    assert audit.verify_bench_balance_audit(result, parent)["valid"]
    assert hashes(parent) == original
