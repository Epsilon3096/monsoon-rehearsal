"""Prospective bench measurement intake and bounded arithmetic comparisons.

No simulator fitting, resampling, extrapolation, missing-data filling, or field
activation occurs here. A passing arithmetic result is not physical proof.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from .site_data import _Checks, _records, content_sha256, parse_json, timestamp, validate_site_package

SCHEMA_VERSION = "monsoon.measurements/1"
PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "data" / "templates" / "bench_protocol_v1.json"
PROTOCOL_SHA256 = "cc7f5c8eb301f0be18aa54d43a93420d54dbf5237aa8d520acc994063ea83d26"
QUANTITY_UNITS = {"inflow_m3_s": "m3/s", "outflow_m3_s": "m3/s", "spill_m3_s": "m3/s", "stage_m": "m", "storage_m3": "m3"}
LIMITATIONS = [
    "Imported provenance, calibration certificates, model freeze times and observations are supplied claims requiring independent review.",
    "No fitting, sample deletion, interpolation across gaps, missing-value substitution or extrapolation is performed.",
    "Trapezoidal integration assumes approximately linear variation within each observed interval; rapid unobserved fluctuations remain a sampling limitation.",
    "A low mass-balance residual alone cannot validate local stage, flow, intervention physics, similarity scaling, or field suitability.",
    "Passing these project arithmetic thresholds does not activate a model or authorise work.",
]


def load_protocol() -> dict:
    protocol = parse_json(PROTOCOL_PATH.read_bytes())
    if content_sha256(protocol) != PROTOCOL_SHA256:
        raise ValueError("Frozen bench protocol content changed; preserve the old protocol and create a new version before new validation.")
    return copy.deepcopy(protocol)


def _report():
    return {"schema_version": SCHEMA_VERSION, "valid": False, "status": "draft_invalid", "package_sha256": None,
            "protocol_sha256": PROTOCOL_SHA256, "evidence_kind": None, "errors": [], "warnings": [],
            "operational_activation_allowed": False, "physical_validation_established": False,
            "limitations": list(LIMITATIONS)}


def validate_measurement_package(payload: dict | str | bytes, site_package: dict | str | bytes | None = None) -> dict:
    report, c = _report(), _Checks()
    try:
        p = parse_json(payload)
        site_snapshot = parse_json(site_package) if site_package is not None else None
        protocol = load_protocol()
        report["package_sha256"] = content_sha256(p)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        c.error("$", "invalid_json_or_protocol", str(exc))
        report["errors"] = c.errors
        return report
    c.obj(p, "$", {"schema_version", "dataset_id", "site_id", "site_package_sha256", "evidence_kind", "vertical_datum", "protocol_id", "protocol_sha256", "recorded_at", "model", "control_volume", "sensors", "events", "notes"})
    c.choice(p.get("schema_version"), {SCHEMA_VERSION}, "$.schema_version")
    c.ident(p.get("dataset_id"), "$.dataset_id")
    c.ident(p.get("site_id"), "$.site_id")
    c.sha(p.get("site_package_sha256"), "$.site_package_sha256")
    c.choice(p.get("evidence_kind"), {"synthetic_fixture", "measured_bench", "measured_site"}, "$.evidence_kind")
    report["evidence_kind"] = p.get("evidence_kind")
    c.text(p.get("vertical_datum"), "$.vertical_datum")
    c.text(p.get("notes"), "$.notes")
    recorded = c.when(p.get("recorded_at"), "$.recorded_at")
    if p.get("protocol_id") != protocol["protocol_id"] or p.get("protocol_sha256") != PROTOCOL_SHA256:
        c.error("$.protocol_sha256", "protocol_mismatch", "Measurement file must bind the unchanged frozen protocol ID and hash.")
    site = None
    if site_package is None:
        c.error("$.site_package_sha256", "site_required", "Supply the matching site package to check geometry identity, datum, sensor locations and boundaries.")
    else:
        site_report = validate_site_package(site_snapshot)
        if not site_report["valid"]:
            c.error("$.site_package_sha256", "invalid_site", "The supplied site package is not structurally ready for review.")
        if site_report["package_sha256"]:
            site = site_snapshot
        if site_report["package_sha256"] != p.get("site_package_sha256"):
            c.error("$.site_package_sha256", "site_hash_mismatch", "Measurements reference a different site revision.")
        if site and (site.get("site_id") != p.get("site_id") or site.get("vertical_datum") != p.get("vertical_datum")):
            c.error("$.vertical_datum", "site_datum_or_id_mismatch", "Site identity and vertical datum must match exactly; no offset is inferred.")
        if site and ((p.get("evidence_kind") == "synthetic_fixture") != (site.get("evidence_kind") == "synthetic_fixture")):
            c.error("$.evidence_kind", "mixed_evidence", "Synthetic site evidence cannot be relabelled measured, or measured site evidence relabelled synthetic.")
    nodes = {r["id"] for r in site.get("nodes", []) if isinstance(r, dict) and isinstance(r.get("id"), str)} if site and isinstance(site.get("nodes"), list) else set()
    jobs = {r["id"] for r in site.get("jobs", []) if isinstance(r, dict) and isinstance(r.get("id"), str)} if site and isinstance(site.get("jobs"), list) else set()
    model = c.obj(p.get("model"), "$.model", {"id", "sha256", "frozen_at", "calibration_event_ids", "freeze_evidence_sha256"})
    c.ident(model.get("id"), "$.model.id")
    c.sha(model.get("sha256"), "$.model.sha256")
    c.sha(model.get("freeze_evidence_sha256"), "$.model.freeze_evidence_sha256")
    model_frozen = c.when(model.get("frozen_at"), "$.model.frozen_at")
    fitted_ids = c.array(model.get("calibration_event_ids"), "$.model.calibration_event_ids")
    if any(not isinstance(x, str) for x in fitted_ids) or (all(isinstance(x, str) for x in fitted_ids) and len(set(fitted_ids)) != len(fitted_ids)):
        c.error("$.model.calibration_event_ids", "invalid_calibration_ids", "Calibration event IDs must be distinct strings.")
    cv = c.obj(p.get("control_volume"), "$.control_volume", {"boundary_inventory_complete", "inventory_evidence_sha256", "unmeasured_loss_upper_bound_m3", "loss_bound_evidence_sha256", "storage_scope", "timestamp_uncertainty_s"})
    if cv.get("boundary_inventory_complete") is not True:
        c.error("$.control_volume", "incomplete_boundaries", "All inflow, receiving exchange, spill and total stored water must be represented.")
    c.sha(cv.get("inventory_evidence_sha256"), "$.control_volume.inventory_evidence_sha256")
    c.sha(cv.get("loss_bound_evidence_sha256"), "$.control_volume.loss_bound_evidence_sha256")
    c.number(cv.get("unmeasured_loss_upper_bound_m3"), "$.control_volume.unmeasured_loss_upper_bound_m3", minimum=0)
    c.number(cv.get("timestamp_uncertainty_s"), "$.control_volume.timestamp_uncertainty_s", positive=True)
    c.choice(cv.get("storage_scope"), {"all_water_inside_control_volume_including_links_and_nodes"}, "$.control_volume.storage_scope")
    sensors = _records(c, p.get("sensors"), "$.sensors", 5)
    by_quantity = {q: set() for q in QUANTITY_UNITS}
    sensor_locations = set()
    for sid, sensor in sensors.items():
        q = f"$.sensors[{sid}]"
        c.obj(sensor, q, {"id", "quantity", "location_id", "unit", "vertical_datum", "calibration"})
        quantity = sensor.get("quantity")
        c.choice(quantity, set(QUANTITY_UNITS), f"{q}.quantity")
        location = sensor.get("location_id")
        if not isinstance(location, str) or (quantity == "storage_m3" and location != "SYSTEM") or (quantity != "storage_m3" and location not in nodes):
            c.error(f"{q}.location_id", "sensor_location", "Use a matching surveyed node ID, or SYSTEM only for total stored volume.")
        if isinstance(quantity, str) and quantity in QUANTITY_UNITS:
            if sensor.get("unit") != QUANTITY_UNITS[quantity]:
                c.error(f"{q}.unit", "wrong_unit", f"Expected {QUANTITY_UNITS[quantity]}; no unit conversion is inferred.")
            if isinstance(location, str):
                by_quantity[quantity].add(location)
                pair = (quantity, location)
                if pair in sensor_locations:
                    c.error(q, "duplicate_boundary_sensor", "Only one counting sensor per quantity/location is allowed; redundant instruments require prior reconciliation.")
                sensor_locations.add(pair)
        if quantity == "stage_m":
            if sensor.get("vertical_datum") != p.get("vertical_datum"):
                c.error(f"{q}.vertical_datum", "datum_mismatch", "Stage must use the package's exact vertical datum.")
        elif sensor.get("vertical_datum") is not None:
            c.error(f"{q}.vertical_datum", "unexpected_datum", "Non-stage quantities use null vertical datum.")
        cal = c.obj(sensor.get("calibration"), f"{q}.calibration", {"record_id", "calibrated_at", "valid_until", "evidence_sha256", "expanded_uncertainty_abs", "coverage_factor"})
        c.ident(cal.get("record_id"), f"{q}.calibration.record_id")
        c.sha(cal.get("evidence_sha256"), f"{q}.calibration.evidence_sha256")
        start = c.when(cal.get("calibrated_at"), f"{q}.calibration.calibrated_at")
        end = c.when(cal.get("valid_until"), f"{q}.calibration.valid_until")
        if start and end and start >= end:
            c.error(q, "invalid_calibration_period", "Calibration expiry must follow calibration time.")
        c.number(cal.get("expanded_uncertainty_abs"), f"{q}.calibration.expanded_uncertainty_abs", positive=True)
        if type(cal.get("coverage_factor")) not in (int, float) or cal.get("coverage_factor") != 2:
            c.error(q, "coverage_factor", "Protocol requires declared expanded absolute instrument uncertainty with coverage factor 2.")
    if site and isinstance(site.get("boundaries"), dict):
        for quantity, field in (("inflow_m3_s", "inflow_node_ids"), ("outflow_m3_s", "outfall_node_ids"), ("spill_m3_s", "spill_node_ids")):
            values = site["boundaries"].get(field)
            if isinstance(values, list) and all(isinstance(v, str) for v in values) and by_quantity[quantity] != set(values):
                c.error("$.sensors", "boundary_coverage", f"{quantity} sensors must cover exactly the site's {field}.")
        if by_quantity["stage_m"] != nodes:
            c.error("$.sensors", "stage_coverage", "Observe stage at every declared node including receiving-water outfalls.")
    if by_quantity["storage_m3"] != {"SYSTEM"}:
        c.error("$.sensors", "storage_coverage", "One independent SYSTEM total-storage observation is required.")
    events = _records(c, p.get("events"), "$.events", 1)
    actual_calibration = set()
    validation_ids, raw_ids = set(), set()
    event_windows = []
    expected_mechanisms = {eid: protocol["mechanisms"][i // 4] for i, eid in enumerate(protocol["event_plan"]["validation_ids"])}
    for eid, event in events.items():
        q = f"$.events[{eid}]"
        c.obj(event, q, {"id", "partition", "mechanism", "state", "completed_job_ids", "paired_event_id", "forcing_sha256", "raw_data_sha256", "start_at", "end_at", "initialisation", "samples"})
        c.choice(event.get("partition"), {"calibration", "validation"}, f"{q}.partition")
        c.choice(event.get("mechanism"), set(protocol["mechanisms"]), f"{q}.mechanism")
        c.choice(event.get("state"), {"current", "restored"}, f"{q}.state")
        c.choice(event.get("initialisation"), {"observed_cold_start", "observed_equilibrated"}, f"{q}.initialisation")
        completed = c.array(event.get("completed_job_ids"), f"{q}.completed_job_ids")
        if any(not isinstance(j, str) or j not in jobs for j in completed):
            c.error(q, "unknown_job", "Completed jobs must reference the matched site package.")
        if all(isinstance(j, str) for j in completed) and len(set(completed)) != len(completed):
            c.error(q, "duplicate_job", "Completed-job IDs must be unique.")
        if (event.get("state") == "current" and completed) or (event.get("state") == "restored" and not completed):
            c.error(q, "state_mismatch", "Current means no declared intervention; restored requires identified approved jobs.")
        c.sha(event.get("forcing_sha256"), f"{q}.forcing_sha256")
        c.sha(event.get("raw_data_sha256"), f"{q}.raw_data_sha256")
        raw = event.get("raw_data_sha256")
        if isinstance(raw, str):
            if raw in raw_ids:
                c.error(q, "duplicate_event_record", "The same raw-event record cannot count as another independent event.")
            raw_ids.add(raw)
        start, end = c.when(event.get("start_at"), f"{q}.start_at"), c.when(event.get("end_at"), f"{q}.end_at")
        if start and end and start >= end:
            c.error(q, "event_order", "Event end must follow event start.")
        elif start and end:
            event_windows.append((start, end, eid))
        if recorded and end and end > recorded:
            c.error(q, "recorded_before_event", "Package recorded_at must follow the event's final observation.")
        if start and start <= timestamp(protocol["frozen_at"]):
            c.error(q, "protocol_not_prospective", "This protocol was not frozen before the event began; retain such data as development evidence under another record.")
        partition = event.get("partition")
        if partition == "calibration":
            actual_calibration.add(eid)
            if end and model_frozen and end >= model_frozen:
                c.error(q, "calibration_after_freeze", "Calibration events must end before model freeze.")
        elif partition == "validation":
            validation_ids.add(eid)
            if start and model_frozen and start <= model_frozen:
                c.error(q, "validation_before_freeze", "Model must be frozen before the validation event begins.")
            if p.get("evidence_kind") != "synthetic_fixture":
                if eid not in expected_mechanisms or expected_mechanisms[eid] != event.get("mechanism"):
                    c.error(q, "unplanned_validation_event", "Measured validation must use the protocol's predeclared event ID and mechanism.")
                pair = event.get("paired_event_id")
                if not isinstance(pair, str) or pair not in events or pair == eid:
                    c.error(q, "missing_pair", "Measured validation requires its predeclared current/restored pair in this package.")
                else:
                    other = events[pair]
                    if other.get("paired_event_id") != eid or other.get("mechanism") != event.get("mechanism") or other.get("forcing_sha256") != event.get("forcing_sha256") or other.get("state") == event.get("state") or other.get("partition") != "validation":
                        c.error(q, "pair_mismatch", "Pair must be reciprocal, same forcing/mechanism/partition, and opposite current/restored state.")
                if eid in expected_mechanisms:
                    index = protocol["event_plan"]["validation_ids"].index(eid)
                    expected_pair = protocol["event_plan"]["validation_ids"][index ^ 1]
                    expected_state = "current" if index % 2 == 0 else "restored"
                    if pair != expected_pair or event.get("state") != expected_state:
                        c.error(q, "predeclared_pair_mismatch", "Use the frozen 01/02 and 03/04 pair assignments: odd current, even restored.")
        if p.get("evidence_kind") != "synthetic_fixture" and partition == "calibration" and not eid.startswith(protocol["event_plan"]["calibration_prefix"]):
            c.error(q, "calibration_id", "Measured calibration event IDs must use the frozen BENCH-CAL- prefix.")
        if event.get("paired_event_id") is not None and not isinstance(event.get("paired_event_id"), str):
            c.error(q, "pair_id", "paired_event_id is an ID or null.")
        if event.get("mechanism") == "cold_start" and event.get("initialisation") != "observed_cold_start":
            c.error(q, "initialisation_mismatch", "Cold-start mechanism requires its observed cold-start initialisation.")
        if event.get("mechanism") == "equilibrated_control" and event.get("initialisation") != "observed_equilibrated":
            c.error(q, "initialisation_mismatch", "Equilibrated control requires observed equilibration.")
        rows = c.array(event.get("samples"), f"{q}.samples", 2)
        previous = None
        sample_times = []
        for i, row in enumerate(rows):
            r = f"{q}.samples[{i}]"
            row = c.obj(row, r, {"timestamp", "observed", "predicted"})
            when = c.when(row.get("timestamp"), f"{r}.timestamp")
            sample_times.append(when)
            if when:
                if start and end and not start <= when <= end:
                    c.error(r, "sample_outside_event", "Sample lies outside the declared event window.")
                if previous:
                    delta = (when - previous).total_seconds()
                    if delta <= 0:
                        c.error(r, "timestamp_order", "Samples must have strictly increasing timestamps.")
                    elif delta > protocol["thresholds"]["maximum_sample_gap_s"]:
                        c.error(r, "sampling_gap", "Gap exceeds frozen limit; no integration is performed across it.")
                    uncertainty = cv.get("timestamp_uncertainty_s")
                    if type(uncertainty) in (int, float) and delta <= 2 * uncertainty:
                        c.error(r, "timestamp_resolution", "Timestamp uncertainty does not resolve the order of adjacent samples.")
                previous = when
            for column in ("observed", "predicted"):
                values = c.obj(row.get(column), f"{r}.{column}", set(sensors))
                for sid, sensor in sensors.items():
                    value = values.get(sid)
                    if c.number(value, f"{r}.{column}.{sid}") and sensor.get("quantity") != "stage_m" and sensor.get("quantity") != "outflow_m3_s" and value < 0:
                        c.error(f"{r}.{column}.{sid}", "negative_quantity", "Only signed receiving-boundary outflow or absolute stage may be negative.")
                    if column == "observed" and when and isinstance(sensor.get("calibration"), dict):
                        begin = timestamp(sensor["calibration"].get("calibrated_at"))
                        finish = timestamp(sensor["calibration"].get("valid_until"))
                        if begin and finish and not begin <= when <= finish:
                            c.error(r, "expired_calibration", f"Sensor {sid} is outside its stated calibration interval.")
        if sample_times and (sample_times[0] != start or sample_times[-1] != end):
            c.error(q, "window_coverage", "First and last observations must exactly cover the declared analysis window; no extrapolation.")
    if all(isinstance(x, str) for x in fitted_ids) and set(fitted_ids) != actual_calibration:
        c.error("$.model.calibration_event_ids", "calibration_partition_mismatch", "Declared fit events must equal the package's calibration events; include complete calibration lineage.")
    if all(isinstance(x, str) for x in fitted_ids) and set(fitted_ids) & validation_ids:
        c.error("$.model.calibration_event_ids", "calibration_validation_leakage", "A validation event cannot be a model-fitting event.")
    event_windows.sort()
    for previous, current in zip(event_windows, event_windows[1:]):
        if current[0] <= previous[1]:
            c.error("$.events", "overlapping_events", f"Events {previous[2]} and {current[2]} overlap; independent reset events need distinct time windows.")
    if not validation_ids:
        c.warn("$.events", "no_validation_events", "Only calibration evidence supplied; no withheld response comparison is established.")
    if p.get("evidence_kind") == "synthetic_fixture":
        c.warn("$", "synthetic_only", "All observations, predictions, provenance and dates in this fixture are invented arithmetic examples, not physical measurements.")
    else:
        c.warn("$", "unverified_measurement_claims", "Measured labels and provenance are supplied claims; authenticity and independent event assignment require review.")
    missing = sorted(set(protocol["event_plan"]["validation_ids"]) - validation_ids)
    report.update(valid=not c.errors, status="ready_for_arithmetic_review" if not c.errors else "draft_invalid", errors=c.errors,
                  warnings=c.warnings, counts={"sensors": len(sensors), "calibration_events": len(actual_calibration), "validation_events": len(validation_ids)},
                  protocol_coverage={"complete": not missing, "missing_validation_ids": missing})
    return report


def _integrate(values: list[float], times: list[float]) -> float:
    return math.fsum((times[i + 1] - times[i]) * (values[i] + values[i + 1]) / 2 for i in range(len(times) - 1))


def _uncertainty_integral(values, times, instrument_uncertainty, timestamp_uncertainty):
    # A conservative linear interval bound; no independence is assumed.
    return math.fsum((times[i + 1] - times[i]) * instrument_uncertainty
                     + timestamp_uncertainty * (abs(values[i]) + abs(values[i + 1]) + 2 * instrument_uncertainty)
                     for i in range(len(times) - 1))


def _acceptance(error: float, uncertainty: float, tolerance: float) -> dict:
    lower, upper = max(0.0, abs(error) - uncertainty), abs(error) + uncertainty
    return {"error": error, "conservative_uncertainty_bound": uncertainty, "lower_abs_bound": lower, "upper_abs_bound": upper,
            "tolerance": tolerance, "status": "pass" if upper <= tolerance else "fail" if lower > tolerance else "unresolved"}


def analyze_measurements(payload: dict | str | bytes, site_package: dict | str | bytes | None = None) -> dict:
    """Evaluate complete intervals and withheld predictions; never fit a model."""
    try:
        p = parse_json(payload)
        site_snapshot = parse_json(site_package) if site_package is not None else None
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        report = _report()
        report.update(errors=[{"path": "$", "code": "invalid_json_or_protocol", "message": str(exc)}], event_results=[], arithmetic_acceptance="not_evaluated")
        return report
    report = validate_measurement_package(p, site_snapshot)
    report["event_results"] = []
    report["arithmetic_acceptance"] = "not_evaluated"
    if not report["valid"]:
        return report
    protocol = load_protocol()
    sensors = {r["id"]: r for r in p["sensors"]}
    outfall_ids = set(site_snapshot["boundaries"]["outfall_node_ids"])
    thresholds, cv = protocol["thresholds"], p["control_volume"]
    validation_states = []
    for event in p["events"]:
        samples = event["samples"]
        start = timestamp(event["start_at"])
        times = [(timestamp(row["timestamp"]) - start).total_seconds() for row in samples]
        obs = {sid: [row["observed"][sid] for row in samples] for sid in sensors}
        pred = {sid: [row["predicted"][sid] for row in samples] for sid in sensors}
        volumes, uncertainties = {}, {}
        for quantity in ("inflow_m3_s", "outflow_m3_s", "spill_m3_s"):
            selected = [sid for sid, sensor in sensors.items() if sensor["quantity"] == quantity]
            volumes[quantity] = math.fsum(_integrate(obs[sid], times) for sid in selected)
            uncertainties[quantity] = math.fsum(_uncertainty_integral(obs[sid], times, sensors[sid]["calibration"]["expanded_uncertainty_abs"], cv["timestamp_uncertainty_s"]) for sid in selected)
        storage_id = next(sid for sid, sensor in sensors.items() if sensor["quantity"] == "storage_m3")
        initial, final = obs[storage_id][0], obs[storage_id][-1]
        # Split signed receiving exchange before integration, so backflow is not
        # hidden in a net discharge or omitted from the relative denominator.
        gross_out, backflow = 0.0, 0.0
        for sid, sensor in sensors.items():
            if sensor["quantity"] == "outflow_m3_s":
                for i in range(len(times) - 1):
                    a, b, dt = obs[sid][i], obs[sid][i + 1], times[i + 1] - times[i]
                    if a * b < 0:
                        split = dt * abs(a) / (abs(a) + abs(b))
                        pieces = ((a, split), (b, dt - split))
                        gross_out += sum(abs(value) * duration / 2 for value, duration in pieces if value > 0)
                        backflow += sum(abs(value) * duration / 2 for value, duration in pieces if value < 0)
                    else:
                        gross_out += dt * (max(0, a) + max(0, b)) / 2
                        backflow += dt * (max(0, -a) + max(0, -b)) / 2
        residual = initial + volumes["inflow_m3_s"] - final - volumes["outflow_m3_s"] - volumes["spill_m3_s"]
        scale = initial + volumes["inflow_m3_s"] + backflow
        tolerance = max(thresholds["mass_balance_absolute_m3"], thresholds["mass_balance_relative"] * scale)
        bound = math.fsum(uncertainties.values()) + 2 * sensors[storage_id]["calibration"]["expanded_uncertainty_abs"] + cv["unmeasured_loss_upper_bound_m3"]
        balance = {"initial_storage_m3": initial, "final_storage_m3": final, "external_inflow_m3": volumes["inflow_m3_s"],
                   "receiving_signed_outflow_m3": volumes["outflow_m3_s"], "receiving_gross_outflow_m3": gross_out,
                   "receiving_backflow_m3": backflow, "spill_m3": volumes["spill_m3_s"], "duration_s": times[-1],
                   "residual_m3": residual, "acceptance": _acceptance(residual, bound, tolerance)}
        metrics = []
        for sid, sensor in sensors.items():
            quantity = sensor["quantity"]
            # Time-weighted trapezoidal squared error; timestamps may be irregular.
            squared = [(a - b) ** 2 for a, b in zip(pred[sid], obs[sid])]
            rmse = math.sqrt(max(0.0, _integrate(squared, times) / times[-1]))
            limit = thresholds["stage_rmse_m"] if quantity == "stage_m" else thresholds["storage_rmse_m3"] if quantity == "storage_m3" else thresholds["flow_rmse_m3_s"]
            slopes = [abs(values[i + 1] - values[i]) / (times[i + 1] - times[i]) for values in (obs[sid], pred[sid]) for i in range(len(times) - 1)]
            timing_bound = 2 * cv["timestamp_uncertainty_s"] * max(slopes, default=0.0)
            metric = {"sensor_id": sid, "quantity": quantity, "location_id": sensor["location_id"], "time_weighted_rmse": rmse,
                      "comparison_role": "boundary_replay_not_independent_response" if quantity == "inflow_m3_s" or (quantity == "stage_m" and sensor["location_id"] in outfall_ids) else "withheld_response" if event["partition"] == "validation" else "calibration_response",
                      "timing_uncertainty_bound": timing_bound,
                      "acceptance": _acceptance(rmse, sensor["calibration"]["expanded_uncertainty_abs"] + timing_bound, limit)}
            if quantity == "spill_m3_s":
                measured, predicted = _integrate(obs[sid], times), _integrate(pred[sid], times)
                limit_volume = max(thresholds["spill_volume_absolute_m3"], thresholds["spill_volume_relative"] * measured)
                uncertainty = _uncertainty_integral(obs[sid], times, sensor["calibration"]["expanded_uncertainty_abs"], cv["timestamp_uncertainty_s"])
                metric["spill_volume"] = {"observed_m3": measured, "predicted_m3": predicted,
                                          "acceptance": _acceptance(predicted - measured, uncertainty, limit_volume)}
            metrics.append(metric)
        states = [balance["acceptance"]["status"]] + [m["acceptance"]["status"] for m in metrics] + [m["spill_volume"]["acceptance"]["status"] for m in metrics if "spill_volume" in m]
        status = "fail" if "fail" in states else "unresolved" if "unresolved" in states else "pass"
        if event["partition"] == "validation":
            validation_states.append(status)
        report["event_results"].append({"event_id": event["id"], "partition": event["partition"], "mechanism": event["mechanism"],
                                        "state": event["state"], "mass_balance": balance, "prediction_comparisons": metrics,
                                        "arithmetic_acceptance": status, "counts_as_validation": event["partition"] == "validation" and p["evidence_kind"] != "synthetic_fixture"})
    report["arithmetic_acceptance"] = "fail" if "fail" in validation_states else "unresolved" if "unresolved" in validation_states else "pass" if validation_states else "no_validation_events"
    report["status"] = "synthetic_arithmetic_only" if p["evidence_kind"] == "synthetic_fixture" else "measured_claims_require_independent_review"
    report["ready_for_physical_review"] = bool(validation_states) and report["protocol_coverage"]["complete"] and p["evidence_kind"] != "synthetic_fixture"
    return report
