import copy
import json
import math
from pathlib import Path

import pytest

from monsoon import measurements
from monsoon.site_data import content_sha256

TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "templates"


@pytest.fixture
def inputs():
    return (json.loads((TEMPLATES / "synthetic_measurements_v1.json").read_text()),
            json.loads((TEMPLATES / "synthetic_site_v1.json").read_text()))


def codes(report):
    return {issue["code"] for issue in report["errors"]}


def test_protocol_is_pinned_and_predates_fixture_observations(inputs):
    protocol = measurements.load_protocol()
    assert content_sha256(protocol) == measurements.PROTOCOL_SHA256
    assert measurements.validate_measurement_package(*inputs)["valid"]
    protocol["thresholds"]["mass_balance_relative"] = 1
    assert content_sha256(protocol) != measurements.PROTOCOL_SHA256
    assert measurements.load_protocol()["thresholds"]["mass_balance_relative"] == 0.03


def test_modified_protocol_file_cannot_be_used(inputs, tmp_path, monkeypatch):
    protocol = measurements.load_protocol()
    protocol["thresholds"]["mass_balance_relative"] = 1
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol))
    monkeypatch.setattr(measurements, "PROTOCOL_PATH", path)
    report = measurements.analyze_measurements(*inputs)
    assert not report["valid"] and report["arithmetic_acceptance"] == "not_evaluated"


def test_fixture_never_establishes_physical_validation(inputs):
    before = copy.deepcopy(inputs)
    report = measurements.analyze_measurements(*inputs)
    assert inputs == before
    assert report["valid"] and report["arithmetic_acceptance"] == "pass"
    assert report["status"] == "synthetic_arithmetic_only"
    assert not report["physical_validation_established"] and not report["operational_activation_allowed"]
    assert not report["ready_for_physical_review"]
    assert not any(e["counts_as_validation"] for e in report["event_results"])


def test_irregular_actual_intervals_and_storage_mass_balance(inputs):
    report = measurements.analyze_measurements(*inputs)
    balance = report["event_results"][1]["mass_balance"]
    assert balance["duration_s"] == 5
    assert balance["external_inflow_m3"] == pytest.approx(0.001)
    assert balance["receiving_signed_outflow_m3"] == pytest.approx(0.0005)
    assert balance["final_storage_m3"] - balance["initial_storage_m3"] == pytest.approx(0.0005)
    assert balance["residual_m3"] == pytest.approx(0, abs=1e-15)


def test_signed_backflow_included_in_balance_and_relative_scale(inputs):
    package, site = inputs
    for event in package["events"]:
        for row, volume in zip(event["samples"], [0.01, 0.0106, 0.0115]):
            for column in ("observed", "predicted"):
                row[column]["QOUT"] = -0.0001
                row[column]["VA"] = volume
    report = measurements.analyze_measurements(package, site)
    balance = report["event_results"][1]["mass_balance"]
    assert balance["receiving_backflow_m3"] == pytest.approx(0.0005)
    assert balance["receiving_gross_outflow_m3"] == 0
    assert balance["receiving_signed_outflow_m3"] == pytest.approx(-0.0005)
    assert balance["residual_m3"] == pytest.approx(0, abs=1e-15)


def test_signed_zero_crossing_separates_triangular_volume_exactly(inputs):
    package, site = inputs
    event = package["events"][1]
    for row, q in zip(event["samples"], [-0.001, 0.001, 0.001]):
        row["observed"]["QOUT"] = q
        row["predicted"]["QOUT"] = q
    balance = measurements.analyze_measurements(package, site)["event_results"][1]["mass_balance"]
    assert balance["receiving_backflow_m3"] == pytest.approx(0.0005)
    assert balance["receiving_gross_outflow_m3"] == pytest.approx(0.0035)
    assert balance["receiving_signed_outflow_m3"] == pytest.approx(0.003)


@pytest.mark.parametrize("value", [None, True, "0.1", float("nan"), float("inf"), 10**400, 1e308, [], {}])
def test_unknown_nonfinite_or_bad_measurements_never_integrate(inputs, value):
    package, site = inputs
    package["events"][1]["samples"][1]["observed"]["QIN"] = value
    report = measurements.analyze_measurements(package, site)
    assert not report["valid"] and report["arithmetic_acceptance"] == "not_evaluated"
    assert report["event_results"] == []


def test_sampling_gap_prevents_even_partial_integration(inputs):
    package, site = inputs
    event = package["events"][1]
    event["samples"][-1]["timestamp"] = "2026-10-15T11:00:10+08:00"
    event["end_at"] = event["samples"][-1]["timestamp"]
    report = measurements.analyze_measurements(package, site)
    assert "sampling_gap" in codes(report) and not report["event_results"]


def test_equal_instants_in_different_offsets_are_duplicate_timestamps(inputs):
    package, site = inputs
    package["events"][1]["samples"][1]["timestamp"] = "2026-10-15T03:00:00Z"
    assert "timestamp_order" in codes(measurements.analyze_measurements(package, site))


def test_no_extrapolation_to_window_end(inputs):
    package, site = inputs
    package["events"][1]["end_at"] = "2026-10-15T11:00:06+08:00"
    assert "window_coverage" in codes(measurements.analyze_measurements(package, site))


def test_timezone_units_datum_and_sensor_coverage(inputs):
    package, site = inputs
    package["sensors"][0]["unit"] = "L/s"
    package["sensors"][4]["vertical_datum"] = "unknown"
    package["sensors"][1]["location_id"] = "MISSING"
    package["events"][0]["samples"][0]["timestamp"] = "2026-10-15T09:00:00"
    result = measurements.validate_measurement_package(package, site)
    assert {"wrong_unit", "datum_mismatch", "sensor_location", "boundary_coverage", "timezone_required"} <= codes(result)


@pytest.mark.parametrize("field,value", [("quantity", []), ("location_id", {}), ("calibration", []), ("id", {})])
def test_malformed_sensor_fields_return_issues(inputs, field, value):
    package, site = inputs
    package["sensors"][0][field] = value
    assert not measurements.analyze_measurements(package, site)["valid"]


def test_expired_calibration_and_missing_uncertainty_cannot_pass(inputs):
    package, site = inputs
    package["sensors"][0]["calibration"]["valid_until"] = "2026-10-15T08:30:00+08:00"
    package["sensors"][1]["calibration"]["expanded_uncertainty_abs"] = None
    report = measurements.analyze_measurements(package, site)
    assert {"expired_calibration", "finite_number_required"} <= codes(report)


def test_large_measurement_uncertainty_is_unresolved_even_exact_predictions(inputs):
    package, site = inputs
    package["sensors"][4]["calibration"]["expanded_uncertainty_abs"] = 0.02
    report = measurements.analyze_measurements(package, site)
    assert report["valid"] and report["arithmetic_acceptance"] == "unresolved"


def test_bad_mass_balance_and_local_prediction_error_are_not_averaged_away(inputs):
    package, site = inputs
    package["events"][1]["samples"][-1]["observed"]["VA"] = 0.02
    package["events"][1]["samples"][-1]["predicted"]["HA"] = 0.5
    report = measurements.analyze_measurements(package, site)
    event = report["event_results"][1]
    assert event["mass_balance"]["acceptance"]["status"] == "fail"
    assert any(m["sensor_id"] == "HA" and m["acceptance"]["status"] == "fail" for m in event["prediction_comparisons"])
    assert report["arithmetic_acceptance"] == "fail"


def test_time_weighted_rmse_uses_real_intervals(inputs):
    package, site = inputs
    event = package["events"][1]
    # [0,2,5] seconds, squared errors [0,.0001,.0001].
    for row, error in zip(event["samples"], [0, 0.01, 0.01]):
        row["predicted"]["HA"] = row["observed"]["HA"] + error
    report = measurements.analyze_measurements(package, site)
    metric = next(m for m in report["event_results"][1]["prediction_comparisons"] if m["sensor_id"] == "HA")
    assert metric["time_weighted_rmse"] == pytest.approx(math.sqrt(0.00008))


def test_fitted_events_cannot_also_be_validation(inputs):
    package, site = inputs
    package["model"]["calibration_event_ids"].append("FIXTURE-VAL-01")
    report = measurements.analyze_measurements(package, site)
    assert {"calibration_partition_mismatch", "calibration_validation_leakage"} <= codes(report)


def test_model_must_be_frozen_between_partitions(inputs):
    package, site = inputs
    package["model"]["frozen_at"] = "2026-10-15T12:00:00+08:00"
    assert "validation_before_freeze" in codes(measurements.analyze_measurements(package, site))
    package["model"]["frozen_at"] = "2026-10-15T08:00:00+08:00"
    assert "calibration_after_freeze" in codes(measurements.analyze_measurements(package, site))


def test_protocol_must_be_frozen_before_collection_and_cannot_be_replaced(inputs):
    package, site = inputs
    package["protocol_sha256"] = "0" * 64
    package["events"][0]["start_at"] = "2026-10-13T08:00:00+08:00"
    assert {"protocol_mismatch", "protocol_not_prospective"} <= codes(measurements.analyze_measurements(package, site))


def test_same_raw_event_cannot_count_twice(inputs):
    package, site = inputs
    package["events"][1]["raw_data_sha256"] = package["events"][0]["raw_data_sha256"]
    assert "duplicate_event_record" in codes(measurements.analyze_measurements(package, site))


def test_site_revision_and_real_synthetic_labels_cannot_be_mixed(inputs):
    package, site = inputs
    package["evidence_kind"] = "measured_bench"
    package["site_package_sha256"] = "0" * 64
    report = measurements.analyze_measurements(package, site)
    assert {"mixed_evidence", "site_hash_mismatch", "unplanned_validation_event"} <= codes(report)
    assert not report["physical_validation_established"]
    assert "site_required" in codes(measurements.analyze_measurements(package))


def test_calibration_only_is_not_validation(inputs):
    package, site = inputs
    package["events"] = package["events"][:1]
    report = measurements.analyze_measurements(package, site)
    assert report["valid"] and report["arithmetic_acceptance"] == "no_validation_events"
    assert not report["ready_for_physical_review"]


def test_analysis_snapshots_before_validation_and_binds_hash(inputs, monkeypatch):
    package, site = inputs
    original = measurements.validate_measurement_package
    expected = content_sha256(package)
    def mutate_caller(snapshot, site_snapshot):
        package["events"][1]["samples"][0]["observed"]["QIN"] = 1e100
        site["nodes"][0]["invert_m"] = None
        return original(snapshot, site_snapshot)
    monkeypatch.setattr(measurements, "validate_measurement_package", mutate_caller)
    result = measurements.analyze_measurements(package, site)
    assert result["valid"] and result["package_sha256"] == expected
    assert result["event_results"][1]["mass_balance"]["external_inflow_m3"] == pytest.approx(0.001)
    json.dumps(result, allow_nan=False)


def test_timestamp_uncertainty_must_resolve_sample_order(inputs):
    package, site = inputs
    package["control_volume"]["timestamp_uncertainty_s"] = 1
    report = measurements.analyze_measurements(package, site)
    assert "timestamp_resolution" in codes(report)
    assert not report["event_results"]


def _invented_measured_claim(inputs):
    """In-memory adversarial claims only; never write as real supplied evidence."""
    package, site = inputs
    site["evidence_kind"] = "supplied_survey"
    site["sources"][0]["kind"] = "survey"
    approval = copy.deepcopy(site["sources"][0])
    approval.update(id="FAKE-APPROVAL", kind="engineering_approval")
    site["sources"].append(approval)
    site["jobs"][0]["approval"]["source_id"] = "FAKE-APPROVAL"
    package["site_package_sha256"] = content_sha256(site)
    package["evidence_kind"] = "measured_bench"
    package["events"][0]["id"] = "BENCH-CAL-001"
    package["model"]["calibration_event_ids"] = ["BENCH-CAL-001"]
    template = package["events"][1]
    package["events"] = package["events"][:1]
    protocol = measurements.load_protocol()
    ids = protocol["event_plan"]["validation_ids"]
    for i, eid in enumerate(ids):
        event = copy.deepcopy(template)
        event.update(id=eid, mechanism=protocol["mechanisms"][i // 4], state="current" if i % 2 == 0 else "restored",
                     paired_event_id=ids[i ^ 1], completed_job_ids=[] if i % 2 == 0 else ["J1"],
                     forcing_sha256=content_sha256({"invented_pair": i // 2}), raw_data_sha256=content_sha256({"invented_event": eid}),
                     initialisation="observed_cold_start" if i // 4 == 4 else "observed_equilibrated")
        for row, second in zip(event["samples"], [0, 2, 5]):
            row["timestamp"] = f"2026-10-15T11:{i + 1:02}:{second:02}+08:00"
        event["start_at"], event["end_at"] = event["samples"][0]["timestamp"], event["samples"][-1]["timestamp"]
        package["events"].append(event)
    return package, site


def test_even_complete_measured_claims_do_not_establish_physical_validation(inputs):
    package, site = _invented_measured_claim(inputs)
    result = measurements.analyze_measurements(package, site)
    assert result["valid"], result["errors"]
    assert result["arithmetic_acceptance"] == "pass" and result["protocol_coverage"]["complete"]
    assert result["ready_for_physical_review"]
    assert not result["physical_validation_established"] and not result["operational_activation_allowed"]
    assert any("independent review" in value for value in result["limitations"])
    assert result["event_results"][1]["prediction_comparisons"][0]["comparison_role"] == "boundary_replay_not_independent_response"


def test_measured_pair_assignments_and_independent_windows_are_fixed(inputs):
    package, site = _invented_measured_claim(inputs)
    package["events"][1]["paired_event_id"] = package["events"][4]["id"]
    package["events"][2]["start_at"] = package["events"][1]["start_at"]
    result = measurements.analyze_measurements(package, site)
    assert {"predeclared_pair_mismatch", "pair_mismatch", "overlapping_events"} <= codes(result)


def test_validation_input_snapshot_has_strict_json_finite_results(inputs):
    result = measurements.analyze_measurements(*inputs)
    assert json.loads(json.dumps(result, allow_nan=False))["valid"]
