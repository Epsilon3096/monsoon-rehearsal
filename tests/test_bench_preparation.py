"""Preparation contracts only: no apparatus, observation or permission is created."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from monsoon import bench_preparation as bench
from monsoon.measurements import load_protocol, PROTOCOL_SHA256
from monsoon.site_data import content_sha256


def test_blank_draft_requires_no_people_or_evidence_and_has_no_physical_claim():
    result = bench.prepare_bench_pack()
    assert result["valid"] and result["status"] == "draft_missing_evidence"
    assert not result["documentary_requirements_complete"]
    assert not result["physical_validation_established"]
    assert not result["engineering_approval_established"]
    assert not result["operational_activation_allowed"]
    assert len(result["pack"]["run_sheets"]) == 24
    assert result["pack_sha256"] == bench.prepare_bench_pack()["pack_sha256"]


def test_frozen_ids_pairs_and_counterbalanced_order_preserved():
    protocol = load_protocol()
    sheets = bench.prepare_bench_pack()["pack"]["run_sheets"]
    assert {s["event_id"] for s in sheets} == set(protocol["event_plan"]["validation_ids"])
    for block in range(6):
        rows = sheets[block*4:block*4+4]
        assert [r["event_id"][-2:] for r in rows] == ["01", "02", "04", "03"]
        assert [r["state"] for r in rows] == ["current", "restored", "restored", "current"]
        assert all(r["mechanism"] == protocol["mechanisms"][block] for r in rows)
        assert rows[0]["paired_event_id"] == rows[1]["event_id"]
        assert rows[2]["paired_event_id"] == rows[3]["event_id"]
    assert [r["run_order"] for r in sheets] == list(range(1, 25))
    assert all(s["independent_reset_required"] for s in sheets)


def test_generated_sheets_have_no_dimensions_observations_or_timestamps():
    sheets = bench.prepare_bench_pack()["pack"]["run_sheets"]
    for sheet in sheets:
        assert sheet["readings"] == []
        assert sheet["predictions"] == []
        assert all(value is None for value in sheet["record_after_event"].values())
        assert sheet["plan_before_collection"]["forcing_sha256"] is None
        assert sheet["plan_before_collection"]["intended_window_seconds"] is None
        assert not sheet["physical_validation_established"]


@pytest.mark.parametrize("key,value", [("observations", []), ("measured_results", {"pass": True}), ("dimensions", {"width_m": .1}), ("run_order", ["BENCH-VAL-H2-02"]), ("future_outcome", "pass")])
def test_measured_or_unrecognised_payload_fields_do_not_generate_pack(key, value):
    payload = bench.blank_bench_readiness()
    payload[key] = value
    result = bench.prepare_bench_pack(payload)
    assert not result["valid"] and "pack" not in result
    assert any(e["code"] == "unknown_field" for e in result["errors"])


def test_documented_claim_requires_evidence_reference():
    payload = bench.blank_bench_readiness()
    payload["checklist"]["facility_setup_authority"]["status"] = "documented"
    report = bench.validate_bench_readiness(payload)
    assert not report["valid"]
    assert any(e["code"] == "document_reference_required" for e in report["errors"])


def test_complete_documentary_claim_never_establishes_approval_or_validation():
    payload = bench.blank_bench_readiness()
    payload.update(prepared_at="2026-10-14T18:00:00+08:00", site_package_sha256="1"*64, model_freeze_sha256="2"*64)
    payload["roles"] = {r: "IN-MEMORY TEST DECLARATION" for r in bench.ROLES}
    for item in payload["checklist"].values():
        item.update(status="documented", evidence_reference={"uri":"test://declaration", "sha256":"3"*64, "description":"No actual evidence is asserted by this test."})
    result = bench.prepare_bench_pack(payload)
    assert result["valid"] and result["documentary_requirements_complete"]
    assert result["status"] == "documented_claims_pending_review"
    assert not result["facility_permission_established"]
    assert not result["engineering_approval_established"]
    assert not result["physical_validation_established"]
    assert all(s["readings"] == [] for s in result["pack"]["run_sheets"])


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(protocol_sha256="0"*64),
    lambda p: p.update(mode="observed"),
    lambda p: p.update(prepared_at="2026-10-14T18:00:00"),
    lambda p: p["roles"].update(build_lead=[]),
    lambda p: p["checklist"].update(unrecognised={}),
    lambda p: p["checklist"]["control_volume_inventory"].update(status=True),
    lambda p: p["checklist"]["control_volume_inventory"].update(observed_storage_m3=1),
])
def test_malformed_or_wrong_contract_inputs_fail_closed(mutation):
    payload = bench.blank_bench_readiness()
    mutation(payload)
    assert not bench.prepare_bench_pack(payload)["valid"]


def test_pack_binds_payload_protocol_and_version_without_mutating_input():
    payload = bench.blank_bench_readiness()
    original = deepcopy(payload)
    result = bench.prepare_bench_pack(payload)
    assert payload == original
    assert result["payload_sha256"] == content_sha256(payload)
    assert result["pack"]["protocol_sha256"] == PROTOCOL_SHA256
    assert result["pack"]["schema_version"] == bench.VERSION
    assert content_sha256({k:v for k,v in result["pack"].items() if k != "pack_sha256"}) == result["pack_sha256"]
    payload["notes"] = "Additional proposed build note."
    assert bench.prepare_bench_pack(payload)["pack_sha256"] != result["pack_sha256"]


def test_filesystem_pack_never_overwrites_and_manifest_matches_raw_bytes(tmp_path):
    result = bench.prepare_bench_pack(output_dir=tmp_path)
    destination = Path(result["saved_directory"])
    manifest = json.loads((destination / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError):
        bench.prepare_bench_pack(output_dir=tmp_path)
    assert json.loads((destination / "bench-pack.json").read_text())["pack_sha256"] == result["pack_sha256"]


def test_invalid_plan_writes_nothing(tmp_path):
    payload = bench.blank_bench_readiness()
    payload["observations"] = []
    assert not bench.prepare_bench_pack(payload, tmp_path)["valid"]
    assert not list(tmp_path.iterdir())


def test_parse_duplicate_keys_and_nonfinite_does_not_generate_pack():
    for value in ('{"a":1,"a":2}', '{"observed":NaN}', None, []):
        if value is None:
            continue  # None intentionally requests the useful blank default.
        assert not bench.prepare_bench_pack(value)["valid"]


def test_in_memory_pack_has_individual_printable_sheets_and_byte_manifest():
    result = bench.prepare_bench_pack()
    files = result["files"]
    sheets = [name for name in files if name.startswith("run-sheets/")]
    assert len(sheets) == 24
    assert all(name.endswith(".md") for name in sheets)
    manifest = json.loads(files["manifest.json"])
    assert set(manifest["files"]) == set(files) - {"manifest.json"}
    assert all(hashlib.sha256(files[name].encode("utf-8")).hexdigest() == sha for name, sha in manifest["files"].items())
    assert all("Observed value" in files[name] and "Locked-model predicted value" in files[name] for name in sheets)


def test_cli_blank_default_generates_useful_draft_without_input_file(tmp_path):
    process = subprocess.run([sys.executable, "-m", "monsoon.bench_preparation", "--output", str(tmp_path)],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True)
    result = json.loads(process.stdout)
    assert result["valid"] and result["status"] == "draft_missing_evidence"
    assert len(result["pack"]["run_sheets"]) == 24
    assert (Path(result["saved_directory"]) / "manifest.json").is_file()
