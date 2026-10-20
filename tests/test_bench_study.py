"""Ledger tests use explicit synthetic doubles; no physical evidence is created."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from monsoon import bench_model, bench_study
from monsoon.bench_study import BenchStudyError, BenchStudyStore
from monsoon.site_data import canonical_json, content_sha256, parse_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    folder = ROOT / "data" / "templates"
    site = parse_json((folder / "synthetic_bench_site_v1.json").read_bytes())
    model = parse_json((folder / "synthetic_bench_model_v1.json").read_bytes())
    model["numerics"]["routing_step_s"] = 0.02
    run = parse_json((folder / "synthetic_bench_run_v1.json").read_bytes())
    run["model_sha256"] = content_sha256(model)
    return site, model, run


def make_event(model, run, identifier="SYN-CAL-01", window=None):
    run = deepcopy(run)
    run.update(run_id=identifier, model_sha256=content_sha256(model))
    return {"event_id": identifier, "run": run, "window": window,
            "series": [{"id": "STAGE-A", "quantity": "stage_m", "location_id": "A", "unit": "m",
                        "expanded_uncertainty_abs": 0.001, "source_id": "SYNTHETIC-UNIT-TEST"}]}


def make_observations(event, model, offset=0.0001, kind="synthetic_fixture"):
    step = model["numerics"]["report_step_s"]
    times = [i * step for i in range(round(event["run"]["duration_s"] / step) + 1)]
    window = event["window"] or {"start_at": None, "end_at": None}
    return {"schema_version": "monsoon.bench-observations/1", "event_id": event["event_id"],
            "evidence_kind": kind, **window, "source_id": "SYNTHETIC-UNIT-TEST",
            "notes": "Invented unit-test observations; not physical measurements.",
            "samples": [{"elapsed_s": t, "observed": {s["id"]: t / 1000 + offset for s in event["series"]}} for t in times]}


@pytest.fixture
def fake_adapter(monkeypatch):
    identity = {"runtime": "explicit-unit-test-double", "version": 1}
    calls = []

    def run(site, model, spec, output_dir):
        calls.append({"site": deepcopy(site), "model": deepcopy(model), "run": deepcopy(spec)})
        folder = Path(output_dir) / "synthetic-attempt"
        folder.mkdir()
        files = {}
        for prefix in ("base", "half"):
            (folder / prefix).mkdir()
            for suffix in ("inp", "rpt", "out"):
                key = f"{prefix}/model.{suffix}"
                path = folder / key
                path.write_bytes(b"Explicit unit-test artifact, not SWMM output")
                files[key] = str(path)
        files.update({name: str(folder / name) for name in ("result.json", "manifest.json")})
        step = model["numerics"]["report_step_s"]
        times = [i * step for i in range(round(spec["duration_s"] / step) + 1)]
        result = {"valid": True, "status": "succeeded", "errors": [], "step_halving": {"passed": True},
                  "site_package_sha256": content_sha256(site), "model_sha256": content_sha256(model),
                  "run_sha256": content_sha256(spec), "engine_identity": deepcopy(identity), "files": files,
                  "timeseries": [{"elapsed_s": t, "stage_m": {n["id"]: t / 1000 for n in site["nodes"]},
                                  "storage_m3": t / 1000, "spill_m3_s": {n: t / 1000 for n in site["boundaries"]["spill_node_ids"]},
                                  "outflow_m3_s": {n: t / 1000 for n in site["boundaries"]["outfall_node_ids"]}} for t in times]}
        (folder / "result.json").write_text(canonical_json(result), encoding="utf-8")
        hashes = {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in files.items() if name != "manifest.json"}
        (folder / "manifest.json").write_text(canonical_json({"file_sha256": hashes}), encoding="utf-8")
        return result

    monkeypatch.setattr(bench_model, "bench_engine_identity", lambda: deepcopy(identity))
    monkeypatch.setattr(bench_model, "run_bench_model", run)
    monkeypatch.setattr(bench_model, "verify_bench_result", lambda result: {"valid": True, "errors": []})
    return {"identity": identity, "calls": calls, "run": run}


@pytest.fixture
def store(tmp_path, fake_adapter):
    with BenchStudyStore(tmp_path / "study.sqlite3") as value:
        yield value


def calibration(store, inputs, *, offset=0.0001):
    site, model, run = inputs
    study = store.create_study(site, title="Explicit synthetic unit-test study")
    event = make_event(model, run)
    result = store.record_calibration(study["study_id"], study["version"], model_spec=model, event=event,
                                      observations=make_observations(event, model, offset))
    return result["study"], model, run


def freeze(store, inputs):
    study, model, run = calibration(store, inputs)
    event = make_event(model, run, "SYN-VAL-01")
    result = store.freeze_study(study["study_id"], study["version"], selected_model_sha256=content_sha256(model),
                               validation_plan=[event], rationale="Manual parameter choice for synthetic software test only")
    return result["study"], model, event


def test_end_to_end_internal_predictions_and_retained_error_lineage(store, inputs, fake_adapter):
    study, model, event = freeze(store, inputs)
    result = store.record_validation(study["study_id"], study["version"], event_id=event["event_id"],
                                     observations=make_observations(event, model, offset=0.0002))
    record, state = result["record"], result["study"]
    assert state["status"] == "withheld_records_complete"
    assert state["pending_validation_event_ids"] == []
    assert record["prediction_origin"] == "internally_run_research_swmm"
    assert record["comparison"]["status"] == "resolved_errors"
    assert record["comparison"]["series"][0]["rmse"] == pytest.approx(0.0002)
    assert len(record["prediction_artifacts"]) == 9
    assert record["prediction_seal_sha256"]
    assert len(fake_adapter["calls"]) == 2
    assert all(set(call) == {"site", "model", "run"} for call in fake_adapter["calls"])
    assert store.verify(study["study_id"])["valid"]
    assert store.list_studies()[0]["study_id"] == study["study_id"]
    for key in ("physical_validation_established", "operational_activation_allowed", "full_protocol_completed",
                "external_prospectivity_verified", "evidence_authenticity_verified", "automatic_fit_performed"):
        assert state[key] is False and record[key] is False


def test_zero_data_freeze_and_unfrozen_validation_are_blocked(store, inputs):
    site, model, run = inputs
    study = store.create_study(site, title="No data test")
    event = make_event(model, run, "SYN-VAL-01")
    with pytest.raises(BenchStudyError, match="nonempty calibration"):
        store.freeze_study(study["study_id"], 1, selected_model_sha256=content_sha256(model), validation_plan=[event], rationale="No observations exist")
    with pytest.raises(BenchStudyError, match="Freeze model"):
        store.record_validation(study["study_id"], 1, event_id=event["event_id"], observations=make_observations(event, model))
    assert store.get(study["study_id"])["version"] == 1


def test_manual_candidates_are_retained_without_automatic_selection(store, inputs):
    study, model, run = calibration(store, inputs)
    changed = deepcopy(model)
    changed["link_parameters"][0]["roughness_n"] *= 1.1
    event = make_event(changed, run)
    more = store.record_calibration(study["study_id"], study["version"], model_spec=changed, event=event,
                                    observations=make_observations(event, changed))
    assert len(more["study"]["calibrations"]) == 2
    assert more["study"]["freeze"] is None
    assert len({r["model_sha256"] for r in more["study"]["calibrations"]}) == 2
    val = make_event(changed, run, "SYN-VAL-01")
    final = store.freeze_study(study["study_id"], more["study"]["version"], selected_model_sha256=content_sha256(changed),
                               validation_plan=[val], rationale="Declared manual model development choice, not automatic fit")
    assert final["freeze"]["model_sha256"] == content_sha256(changed)
    assert len(final["freeze"]["calibration_record_sha256s"]) == 2


def test_failed_engine_result_is_retained_but_cannot_qualify_freeze(store, inputs, monkeypatch):
    def failed(*args):
        raise RuntimeError("Synthetic unit-test engine failure")
    monkeypatch.setattr(bench_model, "run_bench_model", failed)
    study, model, run = calibration(store, inputs)
    record = study["calibrations"][0]
    assert record["prediction"]["status"] == "failed"
    assert record["comparison"]["status"] == "unresolved"
    assert "Synthetic unit-test engine failure" in record["prediction"]["errors"][0]
    with pytest.raises(BenchStudyError, match="calibration"):
        store.freeze_study(study["study_id"], study["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[make_event(model, run, "VAL")], rationale="Failed run is not calibration")


def test_missing_readings_are_retained_without_deletion_or_zero_imputation(store, inputs):
    site, model, run = inputs
    study = store.create_study(site, title="All missing data test")
    event = make_event(model, run)
    obs = make_observations(event, model)
    for row in obs["samples"]:
        row["observed"]["STAGE-A"] = None
    result = store.record_calibration(study["study_id"], 1, model_spec=model, event=event, observations=obs)
    series = result["record"]["comparison"]["series"][0]
    assert series["status"] == "unresolved" and series["rmse"] is None
    assert series["missing_count"] == len(obs["samples"])
    with pytest.raises(BenchStudyError):
        store.freeze_study(study["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[make_event(model, run, "VAL")], rationale="Missing data cannot qualify")


@pytest.mark.parametrize("mutation", [
    lambda o: o.update(predicted={"STAGE-A": 0}),
    lambda o: o["samples"][0].update(predicted={"STAGE-A": 0}),
    lambda o: o["samples"][0]["observed"].update({"STAGE-A": True}),
    lambda o: o["samples"][0]["observed"].update({"STAGE-A": float("nan")}),
    lambda o: o["samples"][0]["observed"].update({"STAGE-A": float("inf")}),
    lambda o: o["samples"][0]["observed"].update({"STAGE-A": "0"}),
    lambda o: o["samples"].pop(),
    lambda o: o["samples"][1].update(elapsed_s=1.000000001),
    lambda o: o["samples"][0].update(elapsed_s=False),
    lambda o: o.update(evidence_kind="measured_bench"),
    lambda o: o.update(start_at="2027-01-01T12:00:00Z"),
])
def test_malformed_or_injected_observations_do_not_call_model(store, inputs, fake_adapter, mutation):
    site, model, run = inputs
    study = store.create_study(site, title="Strict intake test")
    event = make_event(model, run)
    obs = make_observations(event, model)
    mutation(obs)
    with pytest.raises(BenchStudyError):
        store.record_calibration(study["study_id"], 1, model_spec=model, event=event, observations=obs)
    assert fake_adapter["calls"] == []
    assert store.get(study["study_id"])["version"] == 1


@pytest.mark.parametrize("quantity,location,unit", [("stage_m", "O", "m"), ("inflow_m3_s", "A", "m3/s"),
                                                      ("stage_m", "UNKNOWN", "m"), ("stage_m", "A", "mm")])
def test_prescribed_inputs_unknown_locations_and_unit_changes_cannot_be_responses(store, inputs, quantity, location, unit):
    site, model, run = inputs
    study = store.create_study(site, title="Response role test")
    event = make_event(model, run)
    event["series"][0].update(quantity=quantity, location_id=location, unit=unit)
    with pytest.raises(BenchStudyError):
        store.record_calibration(study["study_id"], 1, model_spec=model, event=event,
                                 observations=make_observations(event, model))


def test_duplicate_keys_rejected_before_parsing_can_erase_them(store, inputs):
    site, model, run = inputs
    study = store.create_study(site, title="Duplicate JSON test")
    event = make_event(model, run)
    raw = canonical_json(make_observations(event, model))
    raw = raw[:-1] + ',"event_id":"SOMETHING-ELSE"}'
    with pytest.raises(BenchStudyError, match="Duplicate JSON key"):
        store.record_calibration(study["study_id"], 1, model_spec=model, event=event, observations=raw)


@pytest.mark.parametrize("name,data", [("../outside.txt", b"x"), ("folder/file.txt", b"x"), ("C:\\outside.txt", b"x"),
                                       ("observations.json", b"x"), ("source.csv", "not bytes"), ("source.csv", b"")])
def test_attachments_are_bounded_basename_only(store, inputs, name, data):
    site, model, run = inputs
    study = store.create_study(site, title="Attachment boundary test")
    event = make_event(model, run)
    with pytest.raises(BenchStudyError):
        store.record_calibration(study["study_id"], 1, model_spec=model, event=event,
                                 observations=make_observations(event, model), raw_files={name: data})


def test_raw_observation_bytes_and_extra_source_bytes_are_hashed_exactly(store, inputs):
    site, model, run = inputs
    study = store.create_study(site, title="Raw evidence retention test")
    event = make_event(model, run)
    raw = json.dumps(make_observations(event, model), indent=3).encode()
    result = store.record_calibration(study["study_id"], 1, model_spec=model, event=event,
                                      observations=raw, raw_files={"source.csv": b"synthetic,unit-test\n1,2\n"})
    attachments = result["record"]["attachments"]
    assert attachments[0]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert attachments[1]["name"] == "source.csv"
    assert store.verify(study["study_id"])["valid"]


def test_freeze_is_immutable_and_does_not_follow_mutated_caller_dicts(store, inputs):
    study, model, event = freeze(store, inputs)
    original_hash = study["freeze"]["validation_plan_sha256"]
    event["run"]["inflows"][0]["points"][1]["value_m3_s"] *= 10
    assert store.get(study["study_id"])["freeze"]["validation_plan_sha256"] == original_hash
    with pytest.raises(BenchStudyError, match="Calibration is closed"):
        store.record_calibration(study["study_id"], study["version"], model_spec=model, event=event,
                                 observations=make_observations(event, model))
    with pytest.raises(BenchStudyError, match="only once"):
        store.freeze_study(study["study_id"], study["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[event], rationale="Cannot change after seeing outcomes")


def test_failed_withheld_record_consumes_assignment_and_cannot_be_replaced(store, inputs):
    study, model, event = freeze(store, inputs)
    obs = make_observations(event, model, offset=0.0002)
    obs["samples"][1]["observed"]["STAGE-A"] = None
    result = store.record_validation(study["study_id"], study["version"], event_id=event["event_id"], observations=obs)
    assert result["record"]["comparison"]["status"] == "unresolved"
    with pytest.raises(BenchStudyError, match="once, in order"):
        store.record_validation(study["study_id"], result["study"]["version"], event_id=event["event_id"],
                                observations=make_observations(event, model, offset=0.0003))


def test_renaming_series_or_reordering_cannot_hide_partition_content_match(store, inputs):
    site, model, run = inputs
    study = store.create_study(site, title="Semantic duplicate test")
    event = make_event(model, run)
    event["series"].append({"id": "TOTAL", "quantity": "storage_m3", "location_id": "SYSTEM", "unit": "m3",
                            "expanded_uncertainty_abs": 0.0001, "source_id": "SYNTHETIC-TEST"})
    cal = store.record_calibration(study["study_id"], 1, model_spec=model, event=event, observations=make_observations(event, model))
    val = deepcopy(event)
    val["event_id"] = val["run"]["run_id"] = "SYN-VAL-01"
    val["series"].reverse()
    val["series"][0]["id"] = "RENAMED"
    frozen = store.freeze_study(study["study_id"], cal["study"]["version"], selected_model_sha256=content_sha256(model),
                               validation_plan=[val], rationale="Test semantic duplicate detection")
    result = store.record_validation(study["study_id"], frozen["study"]["version"], event_id=val["event_id"],
                                     observations=make_observations(val, model))
    assert result["record"]["comparison"]["status"] == "unresolved"
    assert result["record"]["suspected_reuse_matches"]
    assert result["record"]["observation_response_sha256"] == cal["record"]["observation_response_sha256"]
    assert result["study"]["pending_validation_event_ids"] == []
    assert "do not prove reuse" in result["record"]["comparison"]["errors"][0]


def test_validation_content_cannot_become_calibration_in_another_study(store, inputs):
    study, model, event = freeze(store, inputs)
    obs = make_observations(event, model, offset=0.0002)
    store.record_validation(study["study_id"], study["version"], event_id=event["event_id"], observations=obs)
    other = store.create_study(inputs[0], title="Later synthetic study")
    cal = make_event(model, inputs[2], "NEW-CAL")
    copied = make_observations(cal, model, offset=0.0002)
    copied["source_id"] = "RENAMED-SOURCE"
    result = store.record_calibration(other["study_id"], 1, model_spec=model, event=cal, observations=copied)
    assert result["record"]["comparison"]["status"] == "unresolved"
    with pytest.raises(BenchStudyError, match="calibration"):
        store.freeze_study(other["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[make_event(model, inputs[2], "NEW-VAL")], rationale="Reused validation is ineligible")


def test_artifact_tampering_blocks_later_calculation(store, inputs, fake_adapter):
    study, model, event = freeze(store, inputs)
    artifact = study["calibrations"][0]["prediction_artifacts"][0]
    (store.artifact_root / artifact["relative_path"]).write_bytes(b"altered after freeze")
    assert not store.verify(study["study_id"])["valid"]
    with pytest.raises(BenchStudyError, match="artifact bytes changed"):
        store.record_validation(study["study_id"], study["version"], event_id=event["event_id"], observations=make_observations(event, model, offset=0.0002))
    assert len(fake_adapter["calls"]) == 1


def test_append_only_events_and_blob_tampering_are_detected(store, inputs):
    study, model, event = freeze(store, inputs)
    with pytest.raises(sqlite3.IntegrityError, match="Immutable"):
        store.db.execute("UPDATE events SET kind='calibration'")
    store.db.execute("DROP TRIGGER immutable_blobs_update")
    digest = study["calibrations"][0]["attachments"][0]["sha256"]
    store.db.execute("UPDATE blobs SET content=? WHERE sha256=?", (b"changed", digest))
    assert not store.verify(study["study_id"])["valid"]


def test_source_engine_lineage_change_blocks_validation(store, inputs, fake_adapter):
    study, model, event = freeze(store, inputs)
    fake_adapter["identity"]["version"] = 2
    checked = store.verify(study["study_id"])
    assert checked["integrity_valid"] and not checked["current_runtime_matches_freeze"]
    with pytest.raises(BenchStudyError, match="differs"):
        store.record_validation(study["study_id"], study["version"], event_id=event["event_id"], observations=make_observations(event, model, offset=0.0002))


@pytest.mark.parametrize("alteration", ["result_values", "native_output", "model_identity", "convergence"])
def test_prediction_is_verified_before_observation_join(store, inputs, fake_adapter, monkeypatch, alteration):
    original = fake_adapter["run"]
    def altered(*args):
        result = original(*args)
        if alteration == "result_values":
            result["timeseries"][0]["stage_m"]["A"] = 999
        elif alteration == "native_output":
            Path(result["files"]["base/model.out"]).write_bytes(b"altered after model manifest")
        elif alteration == "model_identity":
            result["model_sha256"] = "0" * 64
        else:
            result["step_halving"]["passed"] = False
        return result
    monkeypatch.setattr(bench_model, "run_bench_model", altered)
    study, _, _ = calibration(store, inputs)
    record = study["calibrations"][0]
    assert record["prediction"]["valid"] is False
    assert record["comparison"]["status"] == "unresolved"
    assert record["comparison"]["series"] == []
    assert record["prediction_artifacts"]  # Failed attempt bytes are still retained.
    assert store.verify(study["study_id"])["integrity_valid"]


def test_concurrent_writes_use_atomic_expected_version(tmp_path, inputs, fake_adapter):
    site, model, run = inputs
    path = tmp_path / "shared.sqlite3"
    with BenchStudyStore(path) as first:
        study = first.create_study(site, title="Concurrency unit test")
    barrier = threading.Barrier(2)
    outcomes = []
    def writer(index):
        with BenchStudyStore(path) as connection:
            event = make_event(model, run, f"CAL-{index}")
            barrier.wait()
            try:
                connection.record_calibration(study["study_id"], 1, model_spec=model, event=event,
                                              observations=make_observations(event, model, offset=index / 1000))
                outcomes.append("saved")
            except BenchStudyError as exc:
                outcomes.append(exc.code)
    workers = [threading.Thread(target=writer, args=(i,)) for i in (1, 2)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["saved", "stale_version"]
    with BenchStudyStore(path) as result:
        assert len(result.get(study["study_id"])["calibrations"]) == 1


def test_server_clock_rollback_is_not_a_caller_override(store, inputs, monkeypatch):
    clock = [datetime(2027, 1, 1, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(bench_study, "_now", lambda: clock[0].isoformat())
    study, model, run = calibration(store, inputs)
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(BenchStudyError, match="backwards"):
        store.freeze_study(study["study_id"], study["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[make_event(model, run, "VAL")], rationale="Rollback is not prospective")


def test_measured_windows_are_prospective_without_public_clock_injection(store, inputs, monkeypatch):
    # All timestamps/measurements here are unit-test doubles, never field records.
    clock = [datetime(2027, 1, 1, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(bench_study, "_now", lambda: clock[0].isoformat())
    monkeypatch.setattr(bench_study, "validate_site_package", lambda s: {"valid": True, "errors": [], "package_sha256": content_sha256(s)})
    monkeypatch.setattr(bench_model, "validate_bench_run", lambda *a: {"valid": True, "errors": []})
    site, model, run = deepcopy(inputs)
    site["evidence_kind"] = "supplied_survey"
    model.update(evidence_kind="supplied_bench_model", site_package_sha256=content_sha256(site))
    study = store.create_study(site, title="Synthetic test of measured-clock guards")
    past = {"start_at": (clock[0] - timedelta(seconds=180)).isoformat(), "end_at": (clock[0] - timedelta(seconds=60)).isoformat()}
    cal = make_event(model, run, window=past)
    result = store.record_calibration(study["study_id"], 1, model_spec=model, event=cal,
                                      observations=make_observations(cal, model, kind="measured_bench"))
    retro = make_event(model, run, "VAL", window=past)
    with pytest.raises(BenchStudyError, match="after server freeze"):
        store.freeze_study(study["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[retro], rationale="Retrospective event cannot be withheld")
    future = {"start_at": (clock[0] + timedelta(seconds=60)).isoformat(), "end_at": (clock[0] + timedelta(seconds=180)).isoformat()}
    val = make_event(model, run, "VAL", window=future)
    frozen = store.freeze_study(study["study_id"], result["study"]["version"], selected_model_sha256=content_sha256(model),
                               validation_plan=[val], rationale="Future declared window for clock test")
    obs = make_observations(val, model, offset=0.0002, kind="measured_bench")
    with pytest.raises(BenchStudyError, match="already have ended"):
        store.record_validation(study["study_id"], frozen["study"]["version"], event_id="VAL", observations=obs)
    clock[0] += timedelta(seconds=180)
    accepted = store.record_validation(study["study_id"], frozen["study"]["version"], event_id="VAL", observations=obs)
    assert accepted["record"]["comparison"]["status"] == "resolved_errors"
    assert not accepted["record"]["external_prospectivity_verified"]


def test_freeze_rechecks_fresh_clock_after_lineage_preparation(store, inputs, monkeypatch):
    clock = [datetime(2027, 1, 1, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(bench_study, "_now", lambda: clock[0].isoformat())
    monkeypatch.setattr(bench_study, "validate_site_package", lambda s: {"valid": True, "errors": [], "package_sha256": content_sha256(s)})
    monkeypatch.setattr(bench_model, "validate_bench_run", lambda *a: {"valid": True, "errors": []})
    site, model, run = deepcopy(inputs)
    site["evidence_kind"] = "supplied_survey"
    model.update(evidence_kind="supplied_bench_model", site_package_sha256=content_sha256(site))
    study = store.create_study(site, title="Synthetic test of freeze preparation race")
    past = {"start_at": (clock[0] - timedelta(seconds=180)).isoformat(), "end_at": (clock[0] - timedelta(seconds=60)).isoformat()}
    cal = make_event(model, run, window=past)
    captured = store.record_calibration(study["study_id"], 1, model_spec=model, event=cal,
                                        observations=make_observations(cal, model, kind="measured_bench"))
    future = {"start_at": (clock[0] + timedelta(seconds=60)).isoformat(), "end_at": (clock[0] + timedelta(seconds=180)).isoformat()}
    val = make_event(model, run, "VAL", window=future)
    original = bench_study._lineage
    def delayed_lineage():
        result = original()
        clock[0] += timedelta(seconds=61)
        return result
    monkeypatch.setattr(bench_study, "_lineage", delayed_lineage)
    with pytest.raises(BenchStudyError, match="final server freeze time"):
        store.freeze_study(study["study_id"], captured["study"]["version"], selected_model_sha256=content_sha256(model),
                           validation_plan=[val], rationale="A run that starts during preparation is not future")
    assert store.get(study["study_id"])["freeze"] is None


def test_real_swmm_adapter_roundtrip_has_sealed_paired_predictions(tmp_path):
    # The observations remain deliberately invented. This checks software
    # provenance with real SWMM execution, not physical model accuracy.
    folder = ROOT / "data" / "templates"
    site, model, run = [parse_json((folder / f"synthetic_bench_{name}_v1.json").read_bytes()) for name in ("site", "model", "run")]
    with BenchStudyStore(tmp_path / "real-engine-synthetic-study.sqlite3") as store:
        study = store.create_study(site, title="Explicit synthetic real-engine software integration")
        cal = make_event(model, run)
        recorded = store.record_calibration(study["study_id"], 1, model_spec=model, event=cal,
                                            observations=make_observations(cal, model))
        assert recorded["record"]["prediction"]["valid"], recorded["record"]["prediction"]
        assert recorded["record"]["prediction"]["step_halving"]["passed"]
        assert recorded["record"]["comparison"]["status"] == "resolved_errors"
        val = make_event(model, run, "SYN-VAL-01")
        for point in val["run"]["inflows"][0]["points"]:
            point["value_m3_s"] *= 1.1
        frozen = store.freeze_study(study["study_id"], recorded["study"]["version"], selected_model_sha256=content_sha256(model),
                                   validation_plan=[val], rationale="Synthetic software integration only; no parameter fit claimed")
        final = store.record_validation(study["study_id"], frozen["study"]["version"], event_id=val["event_id"],
                                        observations=make_observations(val, model, offset=0.0002))
        assert final["record"]["prediction"]["valid"], final["record"]["prediction"]
        assert final["record"]["comparison"]["status"] == "resolved_errors"
        assert len(final["record"]["prediction_artifacts"]) >= 15
        assert store.verify(study["study_id"])["valid"]
        assert not final["study"]["physical_validation_established"]
