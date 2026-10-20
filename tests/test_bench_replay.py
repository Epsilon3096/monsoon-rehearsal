"""New replay tests use invented software fixtures, never physical observations."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import threading
import zipfile

import pytest

from monsoon import bench_model, bench_replay, bench_balance_audit
from monsoon.bench_replay import BenchReplayError, BenchReplayStore
from monsoon.site_data import canonical_json, content_sha256

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    folder = ROOT / "data/templates"
    names = {"site": "synthetic_bench_replay_site_v1.json", "model": "synthetic_bench_replay_model_v1.json",
             "recipe": "synthetic_bench_replay_recipe_v1.json",
             "calibration_event": "synthetic_bench_replay_calibration_event_v1.json",
             "calibration_boundaries": "synthetic_bench_replay_calibration_boundaries_v1.json",
             "validation_event": "synthetic_bench_replay_validation_event_v1.json",
             "validation_boundaries": "synthetic_bench_replay_validation_boundaries_v1.json"}
    return {key: json.loads((folder / name).read_text(encoding="utf-8")) for key, name in names.items()}


def response(record, boundary, multiplier=1):
    recipe = record["recipe"]
    rows = record["prediction"].get("timeseries") if record["prediction"] else None
    if not rows:
        rows = [{"elapsed_s": t, "stage_m": {"A": t / 1000, "S": t / 1000}, "outflow_m3_s": {"O": 0},
                 "spill_m3_s": {"A": 0, "S": 0}, "storage_m3": 0} for t in range(121)]
    samples = []
    for row in rows:
        observed = {}
        for series in recipe["response_series"]:
            q, n = series["quantity"], series["location_id"]
            offset = {"m": 0.001, "m3/s": 1e-7, "m3": 1e-6}[series["unit"]] * multiplier
            observed[series["id"]] = (row[q] if q == "storage_m3" else row[q][n]) + offset
        samples.append({"elapsed_s": row["elapsed_s"], "observed": observed})
    window = record["event"]["window"] or {"start_at": None, "end_at": None}
    return {"schema_version": bench_replay.RESPONSE_SCHEMA, "event_id": record["event"]["event_id"],
            "evidence_kind": record["evidence_kind"], **window, "clock": deepcopy(boundary["clock"]),
            "vertical_datum": recipe["vertical_datum"], "source_id": "SYN-BENCH-SOURCE",
            "notes": "Explicit circular software-only generated responses plus known offsets; not physical readings.",
            "series": deepcopy(recipe["response_series"]), "samples": samples}


@pytest.fixture
def fake_adapter(monkeypatch):
    identity, calls = {"runtime": "EXPLICIT-UNIT-TEST-DOUBLE", "version": 1}, []

    def run(site, model, spec, output_dir):
        calls.append(deepcopy(spec))
        root = Path(output_dir) / "explicit-synthetic-pair"
        root.mkdir()
        files = {name: str(root / name) for name in bench_replay._PAIR_FILES}
        for name in files:
            path = Path(files[name])
            path.parent.mkdir(exist_ok=True)
            if name not in {"result.json", "manifest.json"}:
                path.write_bytes(b"Explicit unit-test artifact, not SWMM output.")
        step = model["numerics"]["report_step_s"]
        result = {"valid": True, "status": "succeeded", "errors": [], "engine_identity": deepcopy(identity),
                  "site_package_sha256": content_sha256(site), "model_sha256": content_sha256(model), "run_sha256": content_sha256(spec),
                  "step_halving": {"passed": True}, "files": files,
                  "timeseries": [{"elapsed_s": t, "stage_m": {"A": t / 1000, "S": t / 2000}, "outflow_m3_s": {"O": t / 1000000},
                                  "spill_m3_s": {"A": 0, "S": 0}, "storage_m3": t / 100000} for t in range(0, int(spec["duration_s"]) + 1, int(step))]}
        (root / "result.json").write_text(canonical_json(result), encoding="utf-8")
        hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in files.items() if name != "manifest.json"}
        (root / "manifest.json").write_text(canonical_json({"schema_version": "monsoon.bench-pair-evidence/1", "file_sha256": hashes}), encoding="utf-8")
        return result

    monkeypatch.setattr(bench_model, "bench_engine_identity", lambda: deepcopy(identity))
    monkeypatch.setattr(bench_model, "run_bench_model", run)
    monkeypatch.setattr(bench_model, "verify_bench_result", lambda result: {"valid": True, "errors": []})
    audit_identity = {"runtime": "EXPLICIT-UNIT-TEST-AUDIT", "version": 1}
    def audit_run(prediction, output_dir):
        root = Path(output_dir) / "explicit-synthetic-audit"
        root.mkdir()
        files = {name: str(root / name) for name in bench_replay._PAIR_FILES}
        for name in files:
            path = Path(files[name])
            path.parent.mkdir(exist_ok=True)
            if name not in {"result.json", "manifest.json"}:
                path.write_bytes(b"Explicit unit-test additional audit artifact, not SWMM evidence.")
        audit = {"valid": True, "status": "succeeded", "rule": bench_balance_audit.RULE,
                 "attempts": {"base": {"valid": True}, "half": {"valid": True}},
                 "errors": [], "audit_identity": deepcopy(audit_identity), "files": files}
        (root / "result.json").write_text(canonical_json(audit), encoding="utf-8")
        hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in files.items() if name != "manifest.json"}
        (root / "manifest.json").write_text(canonical_json({"schema_version": "monsoon.bench-balance-audit-pair-evidence/1", "file_sha256": hashes}), encoding="utf-8")
        return audit
    monkeypatch.setattr(bench_balance_audit, "bench_balance_audit_identity", lambda: deepcopy(audit_identity))
    monkeypatch.setattr(bench_balance_audit, "audit_bench_balance", audit_run)
    monkeypatch.setattr(bench_balance_audit, "verify_bench_balance_audit", lambda audit, parent_result=None: {"valid": True, "errors": []})
    return {"calls": calls, "identity": identity, "run": run, "audit_run": audit_run, "audit_identity": audit_identity}


@pytest.fixture
def store(tmp_path, fake_adapter):
    with BenchReplayStore(tmp_path / "replay.sqlite3") as value:
        yield value


def calibration_boundaries(store, inputs):
    state = store.create_study(inputs["site"], title="Explicit synthetic replay unit test")
    return store.record_calibration_boundaries(state["study_id"], state["version"], model_spec=inputs["model"], recipe=inputs["recipe"],
                                               event=inputs["calibration_event"], boundaries=inputs["calibration_boundaries"])


def calibration(store, inputs):
    result = calibration_boundaries(store, inputs)
    return store.record_responses(result["study"]["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"],
                                  responses=response(result["record"], inputs["calibration_boundaries"]))


def frozen(store, inputs):
    result = calibration(store, inputs)
    state = result["study"]
    return store.freeze_study(state["study_id"], state["version"], selected_model_sha256=content_sha256(inputs["model"]),
                              selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]],
                              rationale="Manual synthetic software model/recipe choice; no physical model acceptance.")


def validation_boundaries(store, state, inputs):
    return store.record_validation_boundaries(state["study_id"], state["version"], event_id=inputs["validation_event"]["event_id"],
                                              boundaries=inputs["validation_boundaries"])


def test_full_separate_receipts_actual_forcing_and_append_only_order(store, inputs, fake_adapter):
    state = frozen(store, inputs)["study"]
    freeze = state["freeze"]
    assert freeze["actual_validation_boundary_values_known"] is False
    assert "series" not in freeze["validation_plan"][0]
    result = validation_boundaries(store, state, inputs)
    record, state = result["record"], result["study"]
    assert record["response_status"] == "pending" and record["responses"] is None
    assert record["prediction_seal_sha256"]
    assert len(record["prediction_artifacts"]) == 19
    assert len(record["balance_audit_artifacts"]) == 18 and record["prediction_qualified"] is True
    assert set(a["name"] for a in record["prediction_artifacts"]) == bench_replay._PAIR_FILES | {"replay-prediction.json"}
    assert record["derived_run"]["inflows"] != inputs["validation_event"]["planned_targets"]["inflows"]
    assert fake_adapter["calls"][-1] == record["derived_run"]
    assert state["pending_validation_event_ids"] == [] and state["pending_response_receipt_ids"] == [record["receipt_id"]]
    done = store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"],
                                 responses=response(record, inputs["validation_boundaries"], 10))
    assert done["study"]["status"] == "withheld_records_complete"
    assert done["record"]["comparison"]["status"] == "resolved_errors"
    for row in done["record"]["comparison"]["series"]:
        expected = {"m": 0.01, "m3/s": 1e-6, "m3": 1e-5}[row["unit"]]
        assert row["rmse"] == pytest.approx(expected)
        assert row["bias"] == pytest.approx(expected)
    kinds = [r[0] for r in store.db.execute("SELECT kind FROM replay_events ORDER BY version")]
    assert kinds == ["created", "boundary_receipt", "prediction_seal", "response_receipt", "freeze", "boundary_receipt", "prediction_seal", "response_receipt"]
    assert store.verify(state["study_id"])["valid"]
    assert store.list_studies()[0]["study_id"] == state["study_id"]
    for key in bench_replay._FLAGS:
        assert done["record"][key] is False and done["record"]["comparison"][key] is False


@pytest.mark.parametrize("change", [
    lambda r: r.update(run={}),
    lambda r: r.update(units={"time": "ms", "stage": "m", "flow": "m3/s", "volume": "m3"}),
    lambda r: r.update(vertical_datum="OTHER"),
    lambda r: r["boundary_series"].pop(),
    lambda r: r["boundary_series"][0].update(unit="L/s"),
    lambda r: r["boundary_series"][0].update(expanded_uncertainty_abs=0),
    lambda r: r["response_series"][0].update(quantity="receiving_stage_m", location_id="O"),
    lambda r: r["response_series"][0].update(quantity="stage_m", location_id="O"),
    lambda r: r["response_series"][0].update(id="INPUT-A"),
    lambda r: r["interpolation"].update(missing_policy="fill_zero"),
    lambda r: r["interpolation"].update(extrapolation="hold_last"),
    lambda r: r["clock"].update(kind="measured_utc_elapsed"),
    lambda r: r["clock"].update(max_synchronization_uncertainty_s=True),
    lambda r: r.update(initial_conditions={"kind": "measured_wet", "source_id": "SYN-BENCH-SOURCE"}),
])
def test_recipe_rejects_ambiguous_or_unsupported_contract(inputs, change):
    change(inputs["recipe"])
    assert not bench_replay.validate_replay_recipe(inputs["site"], inputs["model"], inputs["recipe"])["valid"]


@pytest.mark.parametrize("change", [
    lambda b: b.update(predictions={}),
    lambda b: b.update(samples=[]),
    lambda b: b.update(vertical_datum="OTHER"),
    lambda b: b.update(start_at="2026-10-15T00:00:00Z"),
    lambda b: b["series"].pop(),
    lambda b: b["series"][0].update(quantity="stage_m"),
    lambda b: b["series"][0].update(unit="L/s"),
    lambda b: b["series"][0].update(expanded_uncertainty_abs=None),
    lambda b: b["series"][0]["points"][0].update(value=0.0001),
    lambda b: b["series"][0]["points"][1].update(value=None),
    lambda b: b["series"][0]["points"][1].update(value=True),
    lambda b: b["series"][0]["points"][1].update(value=float("nan")),
    lambda b: b["series"][0]["points"][1].update(elapsed_s=10.5),
    lambda b: b["series"][0]["points"][1].update(elapsed_s=0),
    lambda b: b["series"][0]["points"].pop(1),
    lambda b: b["series"][0]["points"].pop(),
    lambda b: b["series"][1]["points"][0].update(value=0.23),
    lambda b: b["clock"].update(synchronization_uncertainty_s=0.02),
])
def test_invalid_boundary_is_retained_consumes_assignment_and_never_runs_model(store, inputs, fake_adapter, change):
    state = frozen(store, inputs)["study"]
    change(inputs["validation_boundaries"])
    count = len(fake_adapter["calls"])
    result = validation_boundaries(store, state, inputs)
    record = result["record"]
    assert record["boundary_status"] == "invalid"
    assert record["prediction"]["valid"] is False
    assert record["boundary_errors"] and record["prediction_seal_sha256"]
    assert len(fake_adapter["calls"]) == count
    assert result["study"]["pending_validation_event_ids"] == []
    with pytest.raises(BenchReplayError) as error:
        validation_boundaries(store, result["study"], inputs)
    assert error.value.code == "validation_order"
    done = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=record["receipt_id"], responses=b"{invalid")
    assert done["record"]["response_status"] == "invalid"
    assert done["study"]["status"] == "withheld_records_complete"


@pytest.mark.parametrize("raw", [b"{\"series\":[],\"series\":[]}", b"not JSON", b"\xff", b""])
def test_exact_malformed_boundary_bytes_survive_receipt(store, inputs, raw):
    inputs["calibration_boundaries"] = raw
    result = calibration_boundaries(store, inputs)
    record = result["record"]
    assert record["boundary_status"] == "invalid"
    assert store._read_blob(record["boundary_attachments"][0]["sha256"]) == raw


def test_exact_bytes_and_attachment_separation(store, inputs):
    state = store.create_study(inputs["site"], title="Exact bytes synthetic check")
    raw = (" \n" + json.dumps(inputs["calibration_boundaries"], indent=3) + " \n").encode()
    result = store.record_calibration_boundaries(state["study_id"], 1, model_spec=inputs["model"], recipe=inputs["recipe"], event=inputs["calibration_event"],
                                               boundaries=raw, raw_files={"input.csv": b"explicit synthetic attachment"})
    record = result["record"]
    assert store._read_blob(record["boundary_attachments"][0]["sha256"]) == raw
    obs = ("\n" + json.dumps(response(record, inputs["calibration_boundaries"]), indent=2)).encode()
    result = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=record["receipt_id"], responses=obs,
                                   raw_files={"response.csv": b"different synthetic attachment"})
    assert store._read_blob(result["record"]["response_attachments"][0]["sha256"]) == obs
    sealed = json.loads(store._read_blob(record["prediction_seal_sha256"]))
    assert sealed["response_receipt_present"] is False
    assert "responses" not in sealed


@pytest.mark.parametrize("change", [
    lambda r: r.update(predictions={}),
    lambda r: r.update(inflows=[]),
    lambda r: r["samples"].pop(),
    lambda r: r["samples"][0]["observed"].update({"INPUT-A": 1}),
    lambda r: r["samples"][0]["observed"].update({"STAGE-A": True}),
    lambda r: r["samples"][0].update(elapsed_s=0.001),
    lambda r: r.update(vertical_datum="OTHER"),
    lambda r: r["series"][0].update(expanded_uncertainty_abs=0),
])
def test_bad_response_attempt_is_recorded_and_cannot_be_replaced(store, inputs, change):
    result = calibration_boundaries(store, inputs)
    state, record = result["study"], result["record"]
    supplied = response(record, inputs["calibration_boundaries"])
    change(supplied)
    done = store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"], responses=supplied)
    assert done["record"]["response_status"] == "invalid" and done["record"]["comparison"]["status"] == "unresolved"
    with pytest.raises(BenchReplayError) as error:
        store.record_responses(state["study_id"], done["study"]["version"], receipt_id=record["receipt_id"], responses=response(record, inputs["calibration_boundaries"]))
    assert error.value.code == "response_consumed"


def test_missing_responses_retained_and_cannot_qualify_freeze(store, inputs):
    result = calibration_boundaries(store, inputs)
    state, record = result["study"], result["record"]
    value = response(record, inputs["calibration_boundaries"])
    for sample in value["samples"]:
        sample["observed"]["STAGE-A"] = None
    result = store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"], responses=value)
    series = result["record"]["comparison"]["series"][0]
    assert series["missing_count"] == 121 and series["rmse"] is None
    with pytest.raises(BenchReplayError) as error:
        store.freeze_study(state["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(inputs["model"]),
                           selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]], rationale="Cannot qualify")
    assert error.value.code == "calibration_required"


def test_freeze_requires_prior_complete_internal_calibration(store, inputs):
    state = store.create_study(inputs["site"], title="No evidence synthetic study")
    with pytest.raises(BenchReplayError) as error:
        store.freeze_study(state["study_id"], 1, selected_model_sha256=content_sha256(inputs["model"]), selected_recipe_sha256=content_sha256(inputs["recipe"]),
                           validation_plan=[inputs["validation_event"]], rationale="No calibration")
    assert error.value.code == "calibration_required"


def test_engine_failure_is_sealed_and_cannot_qualify_or_replace(store, inputs, monkeypatch):
    monkeypatch.setattr(bench_model, "run_bench_model", lambda *args: (_ for _ in ()).throw(RuntimeError("Synthetic numerical failure")))
    result = calibration_boundaries(store, inputs)
    assert result["record"]["prediction"]["status"] == "failed"
    assert result["record"]["prediction_seal_sha256"]
    result = store.record_responses(result["study"]["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"], responses=b"invalid response")
    with pytest.raises(BenchReplayError) as error:
        store.record_calibration_boundaries(result["study"]["study_id"], result["study"]["version"], model_spec=inputs["model"], recipe=inputs["recipe"],
                                           event=inputs["calibration_event"], boundaries=inputs["calibration_boundaries"])
    assert error.value.code == "duplicate_attempt"


def test_interruption_keeps_durable_receipt_and_partial_files_without_retry(store, inputs, monkeypatch, fake_adapter):
    def interrupted(site, model, run, folder):
        (Path(folder) / "partial-worker.log").write_bytes(b"Synthetic interrupted attempt")
        raise KeyboardInterrupt("Explicit simulated process interruption")
    monkeypatch.setattr(bench_model, "run_bench_model", interrupted)
    with pytest.raises(KeyboardInterrupt):
        calibration_boundaries(store, inputs)
    state = store.get(store.list_studies()[0]["study_id"])
    record = state["calibrations"][0]
    assert state["version"] == 2 and record["prediction_status"] == "pending"
    with pytest.raises(BenchReplayError) as error:
        store.record_responses(state["study_id"], 2, receipt_id=record["receipt_id"], responses=b"{}")
    assert error.value.code == "seal_required"
    closed = store.close_interrupted_receipt(state["study_id"], 2, receipt_id=record["receipt_id"], reason="Simulated interruption; no retry")
    assert closed["record"]["prediction_status"] == "interrupted"
    assert {a["name"] for a in closed["record"]["prediction_artifacts"]} == {"partial-worker.log", "replay-interrupted-prediction.json"}
    done = store.record_responses(state["study_id"], closed["study"]["version"], receipt_id=record["receipt_id"], responses=b"{}")
    assert done["record"]["comparison"]["status"] == "unresolved"
    assert fake_adapter["calls"] == []


def test_complete_18_file_inventory_required_even_if_verifier_claims_success(store, inputs, fake_adapter, monkeypatch):
    def incomplete(*args):
        result = fake_adapter["run"](*args)
        result["files"].pop("half/worker.log")
        return result
    monkeypatch.setattr(bench_model, "run_bench_model", incomplete)
    result = calibration_boundaries(store, inputs)
    assert result["record"]["prediction"]["status"] == "failed"
    assert "18-file" in result["record"]["prediction"]["errors"][0]["message"]


def test_additional_audit_failure_blocks_comparison_and_freeze_without_mutating_native_pair(store, inputs, fake_adapter, monkeypatch):
    def failed_audit(*args):
        value = fake_adapter["audit_run"](*args)
        value.update(valid=False, status="numerically_unresolved", errors=["Explicit synthetic cumulative balance failure"])
        Path(value["files"]["result.json"]).write_text(canonical_json(value), encoding="utf-8")
        return value
    monkeypatch.setattr(bench_balance_audit, "audit_bench_balance", failed_audit)
    result = calibration_boundaries(store, inputs)
    record, state = result["record"], result["study"]
    assert record["prediction"]["valid"] is True
    assert record["balance_audit"]["valid"] is False and record["prediction_qualified"] is False
    assert json.loads(Path(record["prediction"]["files"]["result.json"]).read_bytes()) == record["prediction"]
    done = store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"], responses=response(record, inputs["calibration_boundaries"]))
    assert done["record"]["comparison"]["status"] == "unresolved" and done["record"]["comparison"]["series"] == []
    with pytest.raises(BenchReplayError) as error:
        store.freeze_study(state["study_id"], done["study"]["version"], selected_model_sha256=content_sha256(inputs["model"]),
                           selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]], rationale="Failed audit cannot qualify")
    assert error.value.code == "calibration_required"


def test_audit_verifier_and_exact_inventory_are_required(store, inputs, fake_adapter, monkeypatch):
    monkeypatch.setattr(bench_balance_audit, "verify_bench_balance_audit", lambda *args: {"valid": False, "errors": ["Explicit verification rejection"]})
    result = calibration_boundaries(store, inputs)
    assert result["record"]["prediction"]["valid"] is True
    assert result["record"]["prediction_qualified"] is False
    assert result["record"]["balance_audit"]["status"] == "audit_unresolved"
    assert len(result["record"]["balance_audit_artifacts"]) == 18


def test_audit_artifact_mutation_blocks_read_and_export(store, inputs):
    result = calibration_boundaries(store, inputs)
    item = result["record"]["balance_audit_artifacts"][0]
    (store.artifact_root / item["relative_path"]).write_bytes(b"Mutated audit evidence")
    assert not store.verify(result["study"]["study_id"])["valid"]
    with pytest.raises(BenchReplayError):
        store.export_evidence(result["study"]["study_id"])


def test_original_artifact_mutation_blocks_later_read_and_response(store, inputs):
    result = calibration_boundaries(store, inputs)
    state, record = result["study"], result["record"]
    path = Path(record["prediction"]["files"]["half/model.out"])
    path.write_bytes(b"mutated synthetic artifact")
    assert not store.verify(state["study_id"])["valid"]
    with pytest.raises(BenchReplayError):
        store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"], responses=response(record, inputs["calibration_boundaries"]))


def test_sqlite_events_and_raw_blobs_have_append_only_guards(store, inputs):
    state = calibration(store, inputs)["study"]
    for command in ("UPDATE replay_events SET kind='x'", "DELETE FROM replay_events", "UPDATE replay_blobs SET content=x'01'", "DELETE FROM replay_blobs"):
        with pytest.raises(sqlite3.IntegrityError):
            store.db.execute(command)
    assert store.verify(state["study_id"])["valid"]


def test_verified_export_contains_exact_bytes_both_evidence_bundles_and_safe_manifest(store, inputs):
    state = frozen(store, inputs)["study"]
    result = validation_boundaries(store, state, inputs)
    done = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"],
                                 responses=response(result["record"], inputs["validation_boundaries"], 10))
    raw = store.export_evidence(state["study_id"])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert set(names) == set(manifest["files"]) | {"manifest.json"}
        assert all(not name.startswith("/") and ".." not in name and "\\" not in name and ":" not in name for name in names)
        for name, item in manifest["files"].items():
            value = archive.read(name)
            assert hashlib.sha256(value).hexdigest() == item["sha256"] and len(value) == item["size"]
        assert json.loads(archive.read("study.json")) == done["study"]
        for record in done["study"]["calibrations"] + done["study"]["validations"]:
            prefix = "records/" + record["receipt_id"]
            assert archive.read(prefix + "/boundaries/boundaries.json") == store._read_blob(record["boundary_attachments"][0]["sha256"])
            assert archive.read(prefix + "/responses/responses.json") == store._read_blob(record["response_attachments"][0]["sha256"])
            assert archive.read(prefix + "/prediction/base/model.inp") == Path(record["prediction"]["files"]["base/model.inp"]).read_bytes()
            assert archive.read(prefix + "/balance-audit/base/model.inp")
        assert not any(name.endswith(".sqlite3") for name in names)
        assert manifest["physical_validation_established"] is False


def test_export_blocks_changed_lineage(store, inputs, fake_adapter):
    state = calibration(store, inputs)["study"]
    fake_adapter["audit_identity"]["version"] = 2
    with pytest.raises(BenchReplayError) as error:
        store.export_evidence(state["study_id"])
    assert error.value.code == "lineage_changed"


def test_old_study_database_is_never_modified(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE studies (id TEXT)")
        database.execute("INSERT INTO studies VALUES ('historical')")
    before = path.read_bytes()
    with pytest.raises(BenchReplayError) as error:
        BenchReplayStore(path)
    assert error.value.code == "store_schema" and path.read_bytes() == before


def test_changed_runtime_blocks_new_validation_and_retains_late_response_unresolved(store, inputs, fake_adapter):
    state = frozen(store, inputs)["study"]
    fake_adapter["identity"]["version"] = 2
    assert store.verify(state["study_id"])["current_runtime_matches_freeze"] is False
    with pytest.raises(BenchReplayError) as error:
        validation_boundaries(store, state, inputs)
    assert error.value.code == "lineage_changed"
    fake_adapter["identity"]["version"] = 1
    result = validation_boundaries(store, state, inputs)
    fake_adapter["identity"]["version"] = 2
    done = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"],
                                 responses=response(result["record"], inputs["validation_boundaries"], 10))
    assert done["record"]["response_status"] == "invalid"
    assert done["record"]["response_errors"][0]["code"] == "lineage_changed"


def test_creation_lineage_change_requires_new_study_before_calibration(store, inputs, fake_adapter):
    state = store.create_study(inputs["site"], title="Creation lineage guard test")
    fake_adapter["audit_identity"]["version"] = 2
    verified = store.verify(state["study_id"])
    assert verified["integrity_valid"] is True and verified["current_runtime_matches_freeze"] is None
    assert verified["current_runtime_matches_study"] is False and verified["valid"] is False
    with pytest.raises(BenchReplayError) as error:
        store.record_calibration_boundaries(state["study_id"], 1, model_spec=inputs["model"], recipe=inputs["recipe"],
                                           event=inputs["calibration_event"], boundaries=inputs["calibration_boundaries"])
    assert error.value.code == "lineage_changed"
    assert store.get(state["study_id"])["version"] == 1 and fake_adapter["calls"] == []


def test_semantic_response_reuse_ignores_labels_and_numeric_spelling(store, inputs):
    result = calibration_boundaries(store, inputs)
    value = response(result["record"], inputs["calibration_boundaries"])
    for sample in value["samples"]:
        sample["observed"] = {sid: 0 for sid in sample["observed"]}
    result = store.record_responses(result["study"]["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"], responses=value)
    state = store.freeze_study(result["study"]["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(inputs["model"]),
                              selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]], rationale="Synthetic numeric spelling test")["study"]
    result = validation_boundaries(store, state, inputs)
    copied = response(result["record"], inputs["validation_boundaries"])
    for sample in copied["samples"]:
        sample["elapsed_s"] = float(sample["elapsed_s"])
        sample["observed"] = {sid: -0.0 for sid in sample["observed"]}
    copied["source_id"] = "RENAMED-SOURCE"
    done = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=result["record"]["receipt_id"], responses=copied)
    assert done["record"]["suspected_reuse_matches"]
    assert done["record"]["comparison"]["status"] == "unresolved"
    assert done["record"]["comparison"]["series"] == []


def measured(inputs, clock):
    """Relabel only an explicit unit-test fixture; never real measured evidence."""
    inputs = deepcopy(inputs)
    inputs["site"]["evidence_kind"] = "supplied_survey"
    inputs["site"]["sources"][0]["kind"] = "survey"
    inputs["model"]["evidence_kind"] = "supplied_bench_model"
    inputs["model"]["site_package_sha256"] = content_sha256(inputs["site"])
    inputs["recipe"]["model_sha256"] = content_sha256(inputs["model"])
    inputs["recipe"]["clock"]["kind"] = "measured_utc_elapsed"
    for partition, start in (("calibration", clock - timedelta(seconds=300)), ("validation", clock + timedelta(seconds=120))):
        window = {"start_at": start.isoformat(), "end_at": (start + timedelta(seconds=120)).isoformat()}
        inputs[partition + "_event"]["window"] = window
        boundary = inputs[partition + "_boundaries"]
        boundary.update(evidence_kind="measured_bench", **window)
        boundary["clock"]["kind"] = "measured_utc_elapsed"
    return inputs


def test_measured_future_guard_and_final_freeze_clock(store, inputs, monkeypatch):
    clock = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(bench_replay, "_now", lambda: clock.isoformat())
    data = measured(inputs, clock)
    state = frozen(store, data)["study"]
    with pytest.raises(BenchReplayError) as error:
        validation_boundaries(store, state, data)
    assert error.value.code == "future_receipt"
    clock += timedelta(seconds=241)
    result = validation_boundaries(store, state, data)
    assert result["record"]["boundary_status"] == "valid"


def test_final_freeze_rechecks_after_preparation_time_has_elapsed(store, inputs, monkeypatch):
    clock = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(bench_replay, "_now", lambda: clock.isoformat())
    data = measured(inputs, clock)
    result = calibration(store, data)
    original = bench_replay._event
    def slow(*args, **kwargs):
        nonlocal clock
        value = original(*args, **kwargs)
        clock += timedelta(seconds=61)
        return value
    monkeypatch.setattr(bench_replay, "_event", slow)
    with pytest.raises(BenchReplayError) as error:
        store.freeze_study(result["study"]["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(data["model"]),
                           selected_recipe_sha256=content_sha256(data["recipe"]), validation_plan=[data["validation_event"]], rationale="Explicit race test")
    assert error.value.code == "prospectivity"
    assert store.get(result["study"]["study_id"])["freeze"] is None


def test_server_clock_rollback_blocks_receipt(store, inputs, monkeypatch):
    state = calibration(store, inputs)["study"]
    monkeypatch.setattr(bench_replay, "_now", lambda: "2000-01-01T00:00:00+00:00")
    with pytest.raises(BenchReplayError) as error:
        store.freeze_study(state["study_id"], state["version"], selected_model_sha256=content_sha256(inputs["model"]),
                           selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]], rationale="Clock test")
    assert error.value.code == "clock_rollback"


def test_stale_writers_cannot_duplicate_response(store, inputs):
    result = calibration_boundaries(store, inputs)
    state, record = result["study"], result["record"]
    value = response(record, inputs["calibration_boundaries"])
    answers = []
    def submit():
        with BenchReplayStore(store.path) as other:
            try:
                other.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"], responses=value)
                answers.append("received")
            except BenchReplayError as exc:
                answers.append(exc.code)
    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(answers) == ["received", "stale_version"]


def test_public_api_has_no_prediction_run_or_runner_injection(store, inputs):
    state = store.create_study(inputs["site"], title="API injection software test")
    with pytest.raises(TypeError):
        store.record_calibration_boundaries(state["study_id"], 1, model_spec=inputs["model"], recipe=inputs["recipe"],
                                           event=inputs["calibration_event"], boundaries=inputs["calibration_boundaries"], prediction={})
    with pytest.raises(TypeError):
        store.record_validation_boundaries(state["study_id"], 1, event_id="X", boundaries={}, run={})


def test_native_swmm_separate_boundary_response_roundtrip(tmp_path, inputs):
    """Actual pinned native engine; circular responses prove software only."""
    with BenchReplayStore(tmp_path / "native.sqlite3") as store:
        state = frozen(store, inputs)["study"]
        result = validation_boundaries(store, state, inputs)
        record = result["record"]
        assert record["prediction"]["valid"], record["prediction"].get("errors")
        assert record["prediction_qualified"], record["balance_audit"]
        assert record["balance_audit"]["valid"] is True
        assert bench_model.verify_bench_result(record["prediction"])["valid"]
        done = store.record_responses(state["study_id"], result["study"]["version"], receipt_id=record["receipt_id"],
                                     responses=response(record, inputs["validation_boundaries"], 10))
        assert done["record"]["comparison"]["status"] == "resolved_errors"
        assert done["record"]["comparison"]["series"][0]["rmse"] == pytest.approx(0.01)
        assert store.verify(state["study_id"])["valid"]
        assert len(record["prediction_artifacts"]) == 19
        assert len(record["balance_audit_artifacts"]) == 18
        assert done["study"]["full_protocol_completed"] is False


def test_native_original_flowing_candidate_remains_unqualified_adverse_evidence(tmp_path, inputs):
    folder = ROOT / "data/templates"
    inputs["site"] = json.loads((folder / "synthetic_bench_site_v1.json").read_bytes())
    inputs["model"] = json.loads((folder / "synthetic_bench_model_v1.json").read_bytes())
    for key in ("recipe", "calibration_event", "calibration_boundaries", "validation_event", "validation_boundaries"):
        inputs[key] = json.loads((folder / "replay_development_failures" / ("synthetic_bench_replay_" + key + "_v1.json")).read_bytes())
    with BenchReplayStore(tmp_path / "adverse.sqlite3") as store:
        result = calibration_boundaries(store, inputs)
        record, state = result["record"], result["study"]
        assert record["prediction"]["valid"] is True
        assert record["balance_audit"]["valid"] is False
        assert record["prediction_qualified"] is False
        done = store.record_responses(state["study_id"], state["version"], receipt_id=record["receipt_id"],
                                     responses=response(record, inputs["calibration_boundaries"]))
        assert done["record"]["comparison"]["status"] == "unresolved"
        assert done["record"]["comparison"]["series"] == []
        with pytest.raises(BenchReplayError) as error:
            store.freeze_study(state["study_id"], done["study"]["version"], selected_model_sha256=content_sha256(inputs["model"]),
                               selected_recipe_sha256=content_sha256(inputs["recipe"]), validation_plan=[inputs["validation_event"]], rationale="Original candidate must remain unresolved")
        assert error.value.code == "calibration_required"
