"""Contract, independent ledger and immutable-evidence checks for FV adapter."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from monsoon import bench_conservative as fv
from monsoon.site_data import canonical_json, content_sha256

FIXTURES = Path(__file__).resolve().parents[1] / "data/templates"


def example():
    return [json.loads((FIXTURES / f"synthetic_bench_{k}_v1.json").read_text()) for k in ("site","model","run")]


def bind(s,m,r):
    m["site_package_sha256"] = content_sha256(s)
    r["model_sha256"] = content_sha256(m)
    return s,m,r


def test_fixture_explicitly_separate_and_nominal_dry():
    s,m,r = example()
    report = fv.validate_conservative_run(s,m,r)
    assert report["valid"] and not report["native_swmm_correction"]
    assert not report["physical_validation_established"] and not report["operational_activation_allowed"]
    network = fv.build_conservative_network(s,m,r)
    assert set(network["nodes"]) == {"A","S"}
    assert set(network["boundaries"]) == {"O"}
    assert "initial_state" not in network
    settings = fv.qualification_settings(m)
    assert [(x["cells_per_channel"],x["cfl"],x["max_step_s"]) for x in settings.values()] == [(128,.4,.01),(128,.2,.005),(256,.4,.01)]


@pytest.mark.parametrize("mutation,code",[
    (lambda s,m,r:s["links"][0].update(cross_section={"shape":"circular","diameter_m":.08}),"unsupported_shape"),
    (lambda s,m,r:s["links"][0].update(inlet_invert_m=.041),"unsupported_offset"),
    (lambda s,m,r:m["link_parameters"][0].update(exit_loss_coefficient=.1),"unsupported_minor_losses"),
    (lambda s,m,r:r["initial_conditions"].update(kind="wet"),"unsupported_value"),
])
def test_unsupported_scope_never_runs_or_creates_artifacts(mutation,code,tmp_path,monkeypatch):
    s,m,r = example()
    mutation(s,m,r)
    monkeypatch.setattr(fv,"run_bounded_worker",lambda *a,**kw:pytest.fail("Invalid contract invoked worker"))
    result = fv.run_conservative_bench(*bind(s,m,r),tmp_path)
    assert not result["valid"] and code in {e["code"] for e in result["errors"]}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("splits",[None,[True],[0],[120],[50,50],[60,50],[float("nan")],[.5]])
def test_phase_split_contract(splits):
    assert not fv.validate_conservative_run(*example(),split_times=splits)["valid"]


def ledger():
    network={"nodes":{"N":{}},"channels":[{"id":"L","from_node":"N","to_node":"O"}],
             "inflows":{"N":[[0,0],[1,.004]]},"boundaries":{"O":[]},"duration_s":1}
    settings={"max_step_s":1,"cfl":.4,"maximum_steps":10}
    rows=[{"elapsed_s":0,"dt_s":0,"storage_m3":0,"node_storage_m3":{"N":0},"link_storage_m3":{"L":0}},
          {"elapsed_s":1,"dt_s":1,"storage_m3":.0015,"node_storage_m3":{"N":.001},"link_storage_m3":{"L":.0005},
           "maximum_cfl":.3,"interval_external_by_node_m3":{"N":.002},"interval_receiving_by_boundary_m3":{"O":0},
           "interval_discharge_by_boundary_m3":{"O":.0005},"interval_spill_by_node_m3":{"N":0},
           "interval_external_inflow_m3":.002,"interval_receiving_backflow_m3":0,"interval_discharge_m3":.0005,"interval_spill_m3":0,
           "boundary_exchange_stage_1_m3":{"O":.00025},"boundary_exchange_stage_2_m3":{"O":.00025},
           "interval_channel_upstream_m3":{"L":.001},"interval_channel_downstream_m3":{"L":.0005}}]
    return network,settings,(),rows


def test_independent_applied_transfer_and_forcing_audit():
    result=fv.audit_conservative_trace(*ledger())
    assert result["valid"] and result["endpoint_count"] == 1
    assert result["maximum_absolute_residual_m3"] < 1e-16
    assert result["totals_m3"]["external"] == .002
    assert result["phases"][0]["final_storage_m3"] == .0015


@pytest.mark.parametrize("mutation",[
    lambda rows:rows[1].update(storage_m3=.002),
    lambda rows:rows[1]["interval_channel_upstream_m3"].update(L=.0009),
    lambda rows:rows[1]["interval_discharge_by_boundary_m3"].update(O=-.0005),
    lambda rows:rows[1]["interval_receiving_by_boundary_m3"].update(O=.0001),
    lambda rows:rows[1]["interval_external_by_node_m3"].update(N=.0019),
    lambda rows:rows[1].update(maximum_cfl=.401),
    lambda rows:rows[1].update(dt_s=.9),
    lambda rows:rows[0].update(storage_m3=1e-12),
    lambda rows:rows[1]["link_storage_m3"].clear(),
    lambda rows:rows.pop(),
])
def test_audit_rejects_internal_cancellation_missing_and_corrupt_values(mutation):
    n,s,c,rows=ledger()
    mutation(rows)
    assert not fv.audit_conservative_trace(n,s,c,rows)["valid"]


@pytest.fixture(scope="module")
def dry_result(tmp_path_factory):
    s,m,r=example()
    r["duration_s"]=2
    r["inflows"][0]["points"]=[{"elapsed_s":t,"value_m3_s":0} for t in (0,2)]
    r["receiving_stages"][0]["points"]=[{"elapsed_s":t,"stage_m":0} for t in (0,2)]
    result=fv.run_conservative_bench(s,m,r,tmp_path_factory.mktemp("conservative-dry"),split_times=(1,))
    assert result["valid"],result["errors"]
    return result


def test_complete_dry_triple_and_independent_verification(dry_result):
    result=dry_result
    assert set(result["attempts"]) == {"primary","temporal","spatial"}
    assert all(a["transfer_audit"]["valid"] for a in result["attempts"].values())
    assert fv.verify_conservative_result(result)["valid"]
    assert len(result["files"]) == 16
    assert all(not row["storage_m3"] for row in result["timeseries"])


@pytest.mark.parametrize("change",["missing","extra","changed","cached","forged_decision","forged_settings"])
def test_evidence_tamper_and_recomputed_decisions(dry_result,tmp_path,change):
    folder=tmp_path/"moved"
    shutil.copytree(dry_result["artifact_directory"],folder)
    result={**deepcopy(dry_result),"artifact_directory":str(folder)}
    assert fv.verify_conservative_result(result)["valid"]
    if change == "missing":
        (folder/"primary/routing.jsonl.gz").unlink()
    elif change == "extra":
        (folder/"unexpected.txt").write_text("extra")
    elif change == "changed":
        (folder/"primary/worker.log").write_text("changed")
    elif change == "cached":
        result["valid"]=False
    else:
        if change == "forged_decision":
            result["convergence"]["spatial"]["relative_tolerance"] = .5
        else:
            request=json.loads((folder/"request.json").read_text())
            request["settings"]["primary"]["cfl"] = .8
            fv._write(folder/"request.json",request)
            result["request_sha256"]=content_sha256(request)
        result["files"]={p.relative_to(folder).as_posix():fv._hash(p) for p in folder.rglob("*") if p.is_file() and p.name not in ("result.json","manifest.json")}
        fv._write(folder/"result.json",{k:v for k,v in result.items() if k != "artifact_directory"})
        fv._write(folder/"manifest.json",{"schema_version":"monsoon.conservative-evidence/1","request_sha256":result["request_sha256"],
            "file_sha256":{p.relative_to(folder).as_posix():fv._hash(p) for p in folder.rglob("*") if p.is_file() and p.name != "manifest.json"}})
    assert not fv.verify_conservative_result(result)["valid"]


def test_stale_loaded_source_fails_closed(monkeypatch):
    monkeypatch.setitem(fv._LOADED_SOURCES,"bench_fv.py","0"*64)
    with pytest.raises(ValueError,match="changed after import"):
        fv.conservative_identity()


def test_three_timed_out_workers_remain_complete_verifiable_failures(tmp_path, monkeypatch):
    """Canonical JSON must not reorder error evidence on a failed triple."""
    calls = []
    def injected_timeout(command, *, cwd, timeout, log_path):
        calls.append((Path(cwd).name, timeout))
        Path(log_path).write_text("Explicitly injected timeout control; no solver started.\n", encoding="utf-8")
        raise subprocess.TimeoutExpired("independent failure control", timeout)
    monkeypatch.setattr(fv, "run_bounded_worker", injected_timeout)
    result = fv.run_conservative_bench(*example(), tmp_path)
    assert calls == [("primary", 600), ("temporal", 600), ("spatial", 600)]
    assert result["valid"] is False and result["status"] == "numerically_unresolved"
    assert all(a["valid"] is False and a["status"] == "worker_failed" for a in result["attempts"].values())
    folder = Path(result["artifact_directory"])
    required = {"request.json", "result.json", "manifest.json"}
    required.update(f"{label}/{name}" for label in ("primary", "temporal", "spatial")
                    for name in ("request.json", "worker.log", "audit.json"))
    assert {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()} == required
    assert set(result["files"]) == required - {"result.json", "manifest.json"}
    stored = json.loads((folder / "result.json").read_bytes())
    retained = {**stored, "artifact_directory": str(folder)}
    integrity = fv.verify_conservative_result(retained)
    assert integrity["valid"] is True, integrity
    assert integrity["numerical_qualification"] is False


@pytest.mark.parametrize("change",["final_clock","final_stage","final_grid","final_discharge","peak","phase_tolerance","diagnostic_steps","report_storage"])
def test_worker_summary_cannot_disagree_with_trace(dry_result,tmp_path,change):
    folder=tmp_path/"attempt"
    shutil.copytree(Path(dry_result["artifact_directory"])/"primary",folder)
    worker=json.loads((folder/"worker-result.json").read_text())
    if change == "final_clock":
        worker["final_state"]["elapsed_s"] = 1
    elif change == "final_stage":
        worker["final_state"]["nodes"]["A"]["stage_m"] += .01
    elif change == "final_grid":
        worker["final_state"]["channels"]["L1"]["bed_m"][0] += .01
    elif change == "final_discharge":
        worker["final_state"]["channels"]["L1"]["unit_discharge_m2_s"].pop()
    elif change == "peak":
        worker["diagnostics"]["maximum_stage_m"]["A"] += .1
    elif change == "phase_tolerance":
        worker["phase_balances"]["whole"]["tolerance_m3"] = .1
    elif change == "diagnostic_steps":
        worker["diagnostics"]["step_count"] = 1
    elif change == "report_storage":
        worker["timeseries"][-1]["storage_m3"] = .001
    fv._write(folder/"worker-result.json",worker)
    request=json.loads((folder/"request.json").read_text())
    assert not fv._qualify_attempt(folder,request)["valid"]
