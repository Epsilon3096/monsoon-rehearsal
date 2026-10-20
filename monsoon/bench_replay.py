"""Measured-boundary replay ledger, separate from the v1 declared-forcing study.

Only the new, explicitly synthetic fixtures exercise this code today. Receipts
and hashes establish local consistency, never evidence authenticity, physical
acceptance, witnessed blindness, or authority to operate an apparatus.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import uuid
import zipfile

from . import bench_model
from . import bench_balance_audit
from .measurements import PROTOCOL_PATH, PROTOCOL_SHA256, load_protocol
from .site_data import MAX_JSON_BYTES, canonical_json, content_sha256, parse_json, timestamp, validate_site_package

SCHEMA_VERSION = "monsoon.bench-replay-study/1"
RECIPE_SCHEMA = "monsoon.bench-replay-recipe/1"
BOUNDARY_SCHEMA = "monsoon.bench-boundaries/1"
RESPONSE_SCHEMA = "monsoon.bench-replay-responses/1"
MINIMUM_FREEZE_LEAD_SECONDS = 60
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOADED_DEPENDENCIES = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                        for name in ("site_data.py", "measurements.py")}
_FLAGS = {"operational_activation_allowed": False, "physical_validation_established": False,
          "full_protocol_completed": False, "external_prospectivity_verified": False,
          "evidence_authenticity_verified": False, "automatic_fit_performed": False,
          "parameter_error_isolated": False, "boundary_uncertainty_propagated": False,
          "planned_target_reproduction_assessed": False}
_UNITS = {"stage_m": "m", "outflow_m3_s": "m3/s", "spill_m3_s": "m3/s", "storage_m3": "m3"}
_SERIES_KEYS = {"id", "quantity", "location_id", "unit", "expanded_uncertainty_abs", "source_id"}
_PAIR_FILES = {"result.json", "manifest.json"} | {
    f"{prefix}/{name}" for prefix in ("base", "half") for name in
    ("model.inp", "model.rpt", "model.out", "request.json", "worker.log", "worker-result.json", "result.json", "manifest.json")}
_LIMITATIONS = [
    "Residuals are conditional on the supplied boundary values and the frozen interpolation/initial-state recipe. They do not isolate parameter error from boundary, clock, datum, initial-state, representation, response, or numerical error.",
    "Declared input and response uncertainties are retained, not propagated into a physical acceptance test. No tolerance pass or physical model acceptance is calculated.",
    "This replay slice supports only a whole-event dry-zero-flow start. The separate prepared-run wrapper and wet/equilibrated events cannot be used through this schema.",
    "Synthetic native-SWMM roundtrips test software only. No real boundary trace, measured apparatus, instrument calibration, operator, or independently blinded experiment is established.",
]


class BenchReplayError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise BenchReplayError(code, message)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _keys(value, fields, name):
    _require(isinstance(value, dict) and set(value) == set(fields), "schema", f"{name} requires exactly its documented fields.")


def _text(value, name, *, identifier=False):
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= 4000, "text", f"{name} requires bounded nonempty text.")
    if identifier:
        _require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", value) is not None, "id", f"{name} is not a supported identifier.")
    return value


def _number(value, name, *, minimum=None, maximum=None, integer=False):
    _require(type(value) in (int, float), "number", f"{name} requires a finite number, not a boolean or string.")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise BenchReplayError("number", f"{name} exceeds numeric limits.") from exc
    _require(math.isfinite(result) and (minimum is None or result >= minimum) and
             (maximum is None or result <= maximum) and (not integer or result.is_integer()),
             "number", f"{name} is outside its finite supported range.")
    return 0.0 if result == 0 else result  # Numeric spelling/negative zero cannot evade semantic reuse checks.


def _parsed(payload):
    try:
        return parse_json(payload)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise BenchReplayError("json", str(exc)) from exc


def _capture(payload):
    """Retain bounded attempted bytes before validating their JSON structure."""
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, dict):
        try:
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=True).encode("utf-8")
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
            raise BenchReplayError("unserializable_receipt", "Supply bounded JSON bytes for an invalid or unrepresentable receipt.") from exc
    else:
        raise BenchReplayError("receipt_type", "Receipt must be JSON bytes, text, or an object; use an explicit null reading for missing data.")
    _require(len(raw) <= MAX_JSON_BYTES, "receipt_size", "Receipt exceeds 5 MiB; no unbounded evidence is accepted.")
    return raw


def _raw(payload):
    raw = _capture(payload)
    return _parsed(raw), raw


def _lineage():
    _require(_hash(Path(__file__).read_bytes()) == _LOADED_SHA256, "source_changed", "Replay source changed after import; restart before a new study revision.")
    current = {name: _hash(Path(__file__).with_name(name).read_bytes()) for name in _LOADED_DEPENDENCIES}
    _require(current == _LOADED_DEPENDENCIES, "source_changed", "Loaded replay dependency source changed; restart before writing.")
    load_protocol()
    return {"replay_source_sha256": _LOADED_SHA256, "dependency_source_sha256": current,
            "protocol_sha256": PROTOCOL_SHA256, "protocol_file_sha256": _hash(PROTOCOL_PATH.read_bytes()),
            "engine_identity": bench_model.bench_engine_identity(), "balance_audit_identity": bench_balance_audit.bench_balance_audit_identity()}


def _grid(model, recipe):
    step, duration = model["numerics"]["report_step_s"], recipe["duration_s"]
    _require(duration % step == 0 and duration / step < 4001, "sample_grid", "Duration must end on the complete bounded engine report grid.")
    return [i * step for i in range(round(duration / step) + 1)]


def _run_from_series(model, recipe, event_id, rows):
    run = {"schema_version": "monsoon.bench-run/1", "run_id": event_id,
           "model_sha256": content_sha256(model), "duration_s": recipe["duration_s"],
           "initial_conditions": deepcopy(recipe["initial_conditions"]), "inflows": [], "receiving_stages": [],
           "notes": "Internally derived exclusively from the retained boundary receipt under a frozen replay recipe; planned targets and responses are not forcing."}
    for row in rows:
        inflow = row["quantity"] == "inflow_m3_s"
        run["inflows" if inflow else "receiving_stages"].append({"node_id": row["location_id"],
            "points": [{"elapsed_s": p["elapsed_s"], "value_m3_s" if inflow else "stage_m": p["value"]} for p in row["points"]]})
    return run


def _recipe(payload, site, model, kind):
    recipe = _parsed(payload)
    _keys(recipe, {"schema_version", "recipe_id", "model_sha256", "duration_s", "initial_conditions", "clock", "units",
                   "vertical_datum", "interpolation", "boundary_series", "response_series", "sign_convention", "notes"}, "Replay recipe")
    _require(recipe["schema_version"] == RECIPE_SCHEMA and recipe["model_sha256"] == content_sha256(model), "recipe_binding", "Recipe schema/model hash must match the exact candidate.")
    _text(recipe["recipe_id"], "Recipe ID", identifier=True)
    _text(recipe["notes"], "Recipe notes")
    model_check = bench_model.validate_bench_model(site, model)
    _require(model_check.get("valid") is True, "model_contract", canonical_json(model_check.get("errors", [])))
    _number(recipe["duration_s"], "Recipe duration", minimum=1, maximum=3600, integer=True)
    _grid(model, recipe)
    _require(recipe["units"] == {"time": "s", "stage": "m", "flow": "m3/s", "volume": "m3"}, "units", "Replay requires exact SI units; no conversion is inferred.")
    _require(recipe["vertical_datum"] == site["vertical_datum"], "datum", "Replay stage datum must exactly match the supplied site datum.")
    _require(recipe["sign_convention"] == {"inflow": "positive_into_control_volume", "outfall_exchange": "positive_outward_negative_backflow", "spill": "positive_outward"}, "sign", "Explicit signed boundary/response conventions are required.")
    clock = recipe["clock"]
    _keys(clock, {"kind", "origin", "time_unit", "max_synchronization_uncertainty_s", "source_id"}, "Clock recipe")
    _require(clock["kind"] == ("synthetic_virtual_elapsed" if kind == "synthetic_fixture" else "measured_utc_elapsed") and
             clock["origin"] == "window_start" and clock["time_unit"] == "s", "clock", "Declare the evidence-specific clock, SI seconds, and exact window origin.")
    clock_uncertainty = _number(clock["max_synchronization_uncertainty_s"], "Maximum synchronization uncertainty", minimum=0, maximum=model["numerics"]["report_step_s"] / 2)
    _require(kind == "synthetic_fixture" or clock_uncertainty > 0, "clock_uncertainty", "Measured clock uncertainty must be explicitly positive; no exact synchronization by assumption.")
    _text(clock["source_id"], "Clock design source")
    interpolation = recipe["interpolation"]
    _keys(interpolation, {"kind", "knots", "max_gap_s", "extrapolation", "missing_policy", "response_alignment"}, "Interpolation recipe")
    _require(interpolation["kind"] == "piecewise_linear" and interpolation["knots"] == "integer_seconds" and
             interpolation["extrapolation"] == "forbidden" and interpolation["missing_policy"] == "unresolved_no_fill" and
             interpolation["response_alignment"] == "exact_report_grid_no_interpolation", "interpolation", "Only explicit bounded linear boundary interpolation, no extrapolation/filling, and exact response grids are supported.")
    _number(interpolation["max_gap_s"], "Maximum boundary gap", minimum=1, maximum=recipe["duration_s"], integer=True)
    boundaries = recipe["boundary_series"]
    _require(isinstance(boundaries, list) and 1 <= len(boundaries) <= 40, "boundary_inventory", "Declare every inflow and receiving-stage boundary once.")
    expected = {("inflow_m3_s", n) for n in site["boundaries"]["inflow_node_ids"]} | {("receiving_stage_m", n) for n in site["boundaries"]["outfall_node_ids"]}
    actual, ids = set(), set()
    for row in boundaries:
        _series(row, ids)
        pair = (row["quantity"], row["location_id"])
        _require(pair in expected and pair not in actual and row["unit"] == ("m3/s" if row["quantity"] == "inflow_m3_s" else "m"), "boundary_inventory", "Boundary inventory, quantity, and SI unit must match the site exactly.")
        actual.add(pair)
    _require(actual == expected, "boundary_inventory", "Every declared inflow and outfall requires a boundary trace.")
    responses = recipe["response_series"]
    _require(isinstance(responses, list) and 1 <= len(responses) <= 64, "response_inventory", "Declare 1–64 independent response series.")
    nodes = {n["id"] for n in site["nodes"]}
    outfalls, spills = set(site["boundaries"]["outfall_node_ids"]), set(site["boundaries"]["spill_node_ids"])
    pairs = set()
    for row in responses:
        _series(row, ids)
        quantity, location = row["quantity"], row["location_id"]
        _require(quantity in _UNITS and row["unit"] == _UNITS[quantity], "response_role", "Only independent SI response quantities may be scored; inflow and receiving-stage inputs cannot be responses.")
        allowed = nodes - outfalls if quantity == "stage_m" else outfalls if quantity == "outflow_m3_s" else spills if quantity == "spill_m3_s" else {"SYSTEM"}
        _require(location in allowed and (quantity, location) not in pairs, "response_role", "Response location is invalid or repeated; receiving-outfall stage cannot be scored.")
        pairs.add((quantity, location))
    # Probe the adapter's horizon/initial-state/numerical limits without using any
    # planned or measured forcing. This structural probe never executes SWMM.
    node_map = {n["id"]: n for n in site["nodes"]}
    probe_rows = [{**row, "points": [{"elapsed_s": t, "value": 0 if row["quantity"] == "inflow_m3_s" else node_map[row["location_id"]]["invert_m"]}
                                    for t in (0, recipe["duration_s"])]} for row in boundaries]
    check = bench_model.validate_bench_run(site, model, _run_from_series(model, recipe, "STRUCTURAL-PROBE", probe_rows))
    _require(check.get("valid") is True, "run_contract", canonical_json(check.get("errors", [])))
    return recipe


def _series(row, ids):
    _keys(row, _SERIES_KEYS, "Series")
    sid = _text(row["id"], "Series ID", identifier=True)
    _require(sid not in ids, "series_id", "Boundary and response series IDs must be distinct.")
    ids.add(sid)
    _text(row["quantity"], "Series quantity")
    _text(row["location_id"], "Series location")
    _require(_number(row["expanded_uncertainty_abs"], "Expanded absolute uncertainty", minimum=0) > 0, "uncertainty", "Declare positive instrument uncertainty; uncertainty is not guessed or propagated.")
    _text(row["source_id"], "Instrument/calibration and uncertainty source")


def _event(payload, site, model, recipe, kind):
    event = _parsed(payload)
    _keys(event, {"event_id", "window", "planned_targets"}, "Replay event")
    _text(event["event_id"], "Event ID", identifier=True)
    if kind == "synthetic_fixture":
        _require(event["window"] is None, "synthetic_clock", "Synthetic event windows must be null; virtual time is not a physical collection timestamp.")
    else:
        _keys(event["window"], {"start_at", "end_at"}, "Measured event window")
        start, end = (timestamp(event["window"][key]) for key in ("start_at", "end_at"))
        _require(start is not None and end is not None and start < end and start.utcoffset().total_seconds() == 0 and end.utcoffset().total_seconds() == 0, "window", "Measured windows require ordered explicit UTC timestamps.")
        _require((end - start).total_seconds() == recipe["duration_s"], "window", "Measured window must equal the frozen whole-event duration.")
    targets = event["planned_targets"]
    if targets is not None:
        _keys(targets, {"inflows", "receiving_stages"}, "Planned targets")
        probe = {"schema_version": "monsoon.bench-run/1", "run_id": event["event_id"], "model_sha256": content_sha256(model),
                 "duration_s": recipe["duration_s"], "initial_conditions": recipe["initial_conditions"],
                 **targets, "notes": "Prospective target schedule only; never actual replay forcing."}
        check = bench_model.validate_bench_run(site, model, probe)
        _require(check.get("valid") is True, "planned_target_contract", canonical_json(check.get("errors", [])))
    return event


def _receipt_common(value, schema, event, recipe, kind, now, extra):
    _keys(value, {"schema_version", "event_id", "evidence_kind", "start_at", "end_at", "clock", "vertical_datum", "source_id", "notes"} | set(extra), "Evidence receipt")
    _require(value["schema_version"] == schema and value["event_id"] == event["event_id"] and value["evidence_kind"] == kind, "receipt_binding", "Receipt schema, event ID, and evidence kind must match the assigned event.")
    window = event["window"] or {"start_at": None, "end_at": None}
    _require(all(value[key] == window[key] for key in window), "window_binding", "Receipt UTC window must exactly match its assignment; it cannot be relabelled.")
    if kind == "measured_bench":
        _require(timestamp(value["end_at"]) <= timestamp(now), "future_receipt", "Measured collection must end before the server receipt time.")
    _require(value["vertical_datum"] == recipe["vertical_datum"], "datum", "Receipt datum must exactly match the frozen site/recipe; no conversion is inferred.")
    clock = value["clock"]
    _keys(clock, {"kind", "origin", "time_unit", "synchronization_uncertainty_s", "source_id"}, "Receipt clock")
    _require(all(clock[key] == recipe["clock"][key] for key in ("kind", "origin", "time_unit")), "clock", "Receipt clock must use the frozen clock kind, SI seconds, and window origin.")
    clock_uncertainty = _number(clock["synchronization_uncertainty_s"], "Receipt synchronization uncertainty", minimum=0, maximum=recipe["clock"]["max_synchronization_uncertainty_s"])
    _require(kind == "synthetic_fixture" or clock_uncertainty > 0, "clock_uncertainty", "Measured clock synchronization uncertainty must be positive and explicit.")
    _text(clock["source_id"], "Clock synchronization source")
    _text(value["source_id"], "Receipt source")
    _text(value["notes"], "Receipt notes")


def _boundaries(payload, event, recipe, site, model, kind, now):
    value = _parsed(payload)
    _receipt_common(value, BOUNDARY_SCHEMA, event, recipe, kind, now, {"series"})
    rows = value["series"]
    _require(isinstance(rows, list) and len(rows) == len(recipe["boundary_series"]), "boundary_inventory", "Boundary receipt must contain the complete frozen input inventory.")
    expected = {row["id"]: row for row in recipe["boundary_series"]}
    seen, missing = set(), 0
    semantic = []
    for row in rows:
        _keys(row, _SERIES_KEYS | {"points"}, "Boundary trace")
        sid = row["id"]
        _require(isinstance(sid, str) and sid in expected and sid not in seen, "boundary_inventory", "Unexpected, repeated, or response series in boundary receipt.")
        seen.add(sid)
        _number(row["expanded_uncertainty_abs"], "Actual boundary expanded uncertainty", minimum=0)
        _require({key: row[key] for key in _SERIES_KEYS} == expected[sid], "boundary_contract", "Boundary identity, SI units, declared uncertainty and source must match the frozen recipe.")
        points = row["points"]
        _require(isinstance(points, list) and 2 <= len(points) <= 1000, "boundary_points", "Each boundary needs 2–1000 knots including both event endpoints.")
        previous, values = None, []
        for point in points:
            _keys(point, {"elapsed_s", "value"}, "Boundary point")
            t = _number(point["elapsed_s"], "Boundary elapsed time", minimum=0, maximum=recipe["duration_s"], integer=True)
            _require(previous is None or 0 < t - previous <= recipe["interpolation"]["max_gap_s"], "boundary_gap", "Boundary times must increase strictly within the frozen maximum gap; no interpolation across a larger gap.")
            previous = t
            v = point["value"]
            if v is None:
                missing += 1
            else:
                v = _number(v, "Boundary value", minimum=0 if row["quantity"] == "inflow_m3_s" else None)
            values.append([t, v])
        _require(points[0]["elapsed_s"] == 0 and points[-1]["elapsed_s"] == recipe["duration_s"], "boundary_coverage", "Every boundary must cover exactly zero through the event horizon; no extrapolation or endpoint substitution.")
        semantic.append({"quantity": row["quantity"], "location_id": row["location_id"], "unit": row["unit"], "values": values})
    _require(not missing, "missing_boundary", f"{missing} missing boundary readings retained; replay is unresolved and no filling is allowed.")
    run = _run_from_series(model, recipe, event["event_id"], sorted(rows, key=lambda row: row["id"]))
    check = bench_model.validate_bench_run(site, model, run)
    _require(check.get("valid") is True, "derived_run_contract", canonical_json(check.get("errors", [])))
    return value, run, content_sha256(sorted(semantic, key=lambda row: (row["quantity"], row["location_id"])))


def _responses(payload, event, recipe, model, kind, now):
    value = _parsed(payload)
    _receipt_common(value, RESPONSE_SCHEMA, event, recipe, kind, now, {"series", "samples"})
    _require(isinstance(value["series"], list), "response_contract", "Response inventory must be a list.")
    actual_ids = set()
    for row in value["series"]:
        _series(row, actual_ids)
    _require(value["series"] == recipe["response_series"], "response_contract", "Response identities, SI units, uncertainties and sources must exactly match the frozen inventory/order.")
    times, series = _grid(model, recipe), recipe["response_series"]
    _require(isinstance(value["samples"], list) and len(value["samples"]) == len(times), "response_grid", "Responses must cover the exact report grid with explicit nulls for missing readings.")
    ids = {row["id"] for row in series}
    for t, sample in zip(times, value["samples"]):
        _keys(sample, {"elapsed_s", "observed"}, "Response sample")
        _require(_number(sample["elapsed_s"], "Response time", minimum=0) == t, "response_grid", "Responses use the exact report grid without interpolation, deletion, or time shifting.")
        _keys(sample["observed"], ids, "Observed responses")
        for row in series:
            v = sample["observed"][row["id"]]
            if v is not None:
                _number(v, "Observed response", minimum=0 if row["quantity"] in {"spill_m3_s", "storage_m3"} else None)
    semantic = [{"quantity": row["quantity"], "location_id": row["location_id"], "unit": row["unit"],
                 "values": [[_number(s["elapsed_s"], "Response time"), None if s["observed"][row["id"]] is None else _number(s["observed"][row["id"]], "Response value")]
                            for s in value["samples"]]}
                for row in sorted(series, key=lambda row: (row["quantity"], row["location_id"]))]
    return value, content_sha256(semantic)


def _unresolved(message, errors=None):
    return {"status": "unresolved", "summary": message, "errors": errors or [message], "series": [],
            "acceptance_assessed": False, "limitations": list(_LIMITATIONS), **_FLAGS}


def _comparison(value, recipe, prediction):
    report = _unresolved("Replay response errors remain unresolved.", [])
    report["errors"] = []
    if prediction.get("valid") is not True:
        return _unresolved("Boundary replay did not produce a complete internally verified prediction; no response error is credited.")
    for row in recipe["response_series"]:
        observed = [s["observed"][row["id"]] for s in value["samples"]]
        item = {"series_id": row["id"], "quantity": row["quantity"], "location_id": row["location_id"], "unit": row["unit"],
                "sample_count": len(observed), "missing_count": sum(v is None for v in observed), "status": "unresolved",
                "rmse": None, "bias": None, "maximum_absolute_error": None, "expanded_uncertainty_abs": row["expanded_uncertainty_abs"]}
        if item["missing_count"]:
            report["errors"].append(f"{row['id']}: missing readings retained without substitution or sample deletion.")
        else:
            try:
                predicted = [s[row["quantity"]] if row["quantity"] == "storage_m3" else s[row["quantity"]][row["location_id"]] for s in prediction["timeseries"]]
                _require(len(predicted) == len(observed), "prediction_grid", "Prediction/response sample counts differ.")
                errors = [float(a) - _number(b, "Predicted response") for a, b in zip(observed, predicted)]
                metrics = (math.hypot(*errors) / math.sqrt(len(errors)), math.fsum(errors) / len(errors), max(map(abs, errors)))
                _require(all(math.isfinite(v) for v in metrics), "arithmetic", "Nonfinite error arithmetic.")
                item.update(status="resolved_errors", rmse=metrics[0], bias=metrics[1], maximum_absolute_error=metrics[2])
            except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError):
                report["errors"].append(f"{row['id']}: finite comparison arithmetic is unresolved.")
        report["series"].append(item)
    if not report["errors"]:
        report.update(status="resolved_errors", summary="Complete conditional replay residuals retained; no physical acceptance or causal parameter-error claim.")
    return report


def validate_replay_recipe(site, model, recipe):
    """Read-only structural check; it does not supply or execute boundaries."""
    try:
        s, m = _parsed(site), _parsed(model)
        kind = "synthetic_fixture" if s["evidence_kind"] == "synthetic_fixture" else "measured_bench"
        value = _recipe(recipe, s, m, kind)
        return {"valid": True, "recipe_sha256": content_sha256(value), "errors": [], **_FLAGS}
    except (ValueError, KeyError, TypeError) as exc:
        return {"valid": False, "errors": [{"code": getattr(exc, "code", "schema"), "message": str(exc)}], **_FLAGS}


class BenchReplayStore:
    """Append-only boundary reservation → prediction seal → response receipts.

    A boundary reservation commits before executing SWMM. A killed process can
    leave a pending reservation; it may be closed unresolved, never executed a
    second time. No user-supplied runner, prediction, clock, or frozen run exists.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = self.path.with_name(self.path.name + ".artifacts")
        self.db = sqlite3.connect(self.path, timeout=120, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables and not tables <= {"replay_meta", "replay_studies", "replay_events", "replay_blobs"}:
            self.db.close()
            raise BenchReplayError("store_schema", "Use a separate replay ledger; an existing study or other database cannot be migrated or edited here.")
        if tables:
            try:
                schema = self.db.execute("SELECT schema_version FROM replay_meta").fetchall()
                _require(len(schema) == 1 and schema[0][0] == SCHEMA_VERSION, "store_schema", "Replay database schema differs from this module.")
            except BaseException:
                self.db.close()
                raise
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS replay_meta (schema_version TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS replay_studies (id TEXT PRIMARY KEY, version INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS replay_blobs (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS replay_events (study_id TEXT NOT NULL REFERENCES replay_studies(id), version INTEGER NOT NULL,
            kind TEXT NOT NULL, at TEXT NOT NULL, previous_sha256 TEXT, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY(study_id,version));
          CREATE TRIGGER IF NOT EXISTS replay_events_no_update BEFORE UPDATE ON replay_events BEGIN SELECT RAISE(ABORT,'Immutable replay event'); END;
          CREATE TRIGGER IF NOT EXISTS replay_events_no_delete BEFORE DELETE ON replay_events BEGIN SELECT RAISE(ABORT,'Immutable replay event'); END;
          CREATE TRIGGER IF NOT EXISTS replay_blobs_no_update BEFORE UPDATE ON replay_blobs BEGIN SELECT RAISE(ABORT,'Immutable replay blob'); END;
          CREATE TRIGGER IF NOT EXISTS replay_blobs_no_delete BEFORE DELETE ON replay_blobs BEGIN SELECT RAISE(ABORT,'Immutable replay blob'); END;
          CREATE TRIGGER IF NOT EXISTS replay_meta_no_update BEFORE UPDATE ON replay_meta BEGIN SELECT RAISE(ABORT,'Immutable replay schema'); END;
          CREATE TRIGGER IF NOT EXISTS replay_meta_no_delete BEFORE DELETE ON replay_meta BEGIN SELECT RAISE(ABORT,'Immutable replay schema'); END;
        """)
        if not tables:
            self.db.execute("INSERT INTO replay_meta VALUES (?)", (SCHEMA_VERSION,))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def _transaction(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise BenchReplayError("busy", "Replay store is busy; reread its version when the active operation finishes.") from exc
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _blob(self, raw):
        digest = _hash(raw)
        self.db.execute("INSERT OR IGNORE INTO replay_blobs VALUES (?,?)", (digest, raw))
        self._read_blob(digest)
        return digest

    def _read_blob(self, digest):
        row = self.db.execute("SELECT content FROM replay_blobs WHERE sha256=?", (digest,)).fetchone()
        _require(row is not None and _hash(row[0]) == digest, "blob_integrity", "Retained evidence bytes are missing or changed.")
        return row[0]

    def _append(self, study_id, kind, payload, at):
        payload = _parsed(payload)
        last = self.db.execute("SELECT * FROM replay_events WHERE study_id=? ORDER BY version DESC LIMIT 1", (study_id,)).fetchone()
        version, previous = (last["version"] + 1, last["sha256"]) if last else (1, None)
        _require(timestamp(at) is not None and (last is None or timestamp(at) >= timestamp(last["at"])), "clock_rollback", "Server receipt clock moved before the last ledger event.")
        envelope = {"study_id": study_id, "version": version, "kind": kind, "at": at, "previous_sha256": previous, "payload": payload}
        digest = content_sha256(envelope)
        self.db.execute("INSERT INTO replay_events VALUES (?,?,?,?,?,?,?)", (study_id, version, kind, at, previous, canonical_json(payload), digest))
        self.db.execute("UPDATE replay_studies SET version=? WHERE id=?", (version, study_id))
        return version, digest

    def _artifact_bytes(self, item):
        relative = PurePosixPath(item["relative_path"])
        _require(not relative.is_absolute() and ".." not in relative.parts and "\\" not in str(relative) and ":" not in str(relative), "artifact_integrity", "Unsafe replay artifact path.")
        path = self.artifact_root / relative
        _require(not any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(self.artifact_root)), "artifact_integrity", "Replay artifacts cannot contain symbolic links.")
        resolved = path.resolve()
        _require(resolved.is_relative_to(self.artifact_root.resolve()) and resolved.is_file() and resolved.stat().st_size <= MAX_ARTIFACT_BYTES, "artifact_integrity", "Retained prediction artifact is missing, unsafe, or oversized.")
        raw = resolved.read_bytes()
        _require(len(raw) == item["size"] and _hash(raw) == item["sha256"] and self._read_blob(item["sha256"]) == raw, "artifact_integrity", "Prediction artifact or its stored copy changed after sealing.")
        return raw

    def _events(self, study_id):
        _text(study_id, "Study ID", identifier=True)
        head = self.db.execute("SELECT version FROM replay_studies WHERE id=?", (study_id,)).fetchone()
        _require(head is not None, "unknown_study", "Replay study does not exist.")
        rows = self.db.execute("SELECT * FROM replay_events WHERE study_id=? ORDER BY version", (study_id,)).fetchall()
        _require(rows and len(rows) == head["version"], "integrity", "Replay study event count/head mismatch.")
        previous, prior_time, result = None, None, []
        for index, row in enumerate(rows, 1):
            payload = _parsed(row["payload"])
            envelope = {"study_id": study_id, "version": index, "kind": row["kind"], "at": row["at"], "previous_sha256": previous, "payload": payload}
            _require(row["version"] == index and row["previous_sha256"] == previous and row["sha256"] == content_sha256(envelope) and row["payload"] == canonical_json(payload), "integrity", "Replay append-only hash chain changed.")
            when = timestamp(row["at"])
            _require(when is not None and (prior_time is None or when >= prior_time), "integrity", "Replay receipt chronology changed.")
            for digest in payload.get("blob_sha256s", []):
                self._read_blob(digest)
            for artifact in payload.get("prediction_artifacts", []) + payload.get("balance_audit_artifacts", []):
                self._artifact_bytes(artifact)
            result.append({**dict(row), "payload": payload})
            previous, prior_time = row["sha256"], when
        return result

    def get(self, study_id):
        rows = self._events(study_id)
        _require(rows[0]["kind"] == "created" and rows[0]["payload"].get("schema_version") == SCHEMA_VERSION, "integrity", "Replay creation record/schema is invalid.")
        state = deepcopy(rows[0]["payload"])
        state.update(version=rows[-1]["version"], head_sha256=rows[-1]["sha256"], created_at=rows[0]["at"], calibrations=[], validations=[], freeze=None)
        receipts = {}
        for row in rows[1:]:
            item = {**deepcopy(row["payload"]), "record_sha256": row["sha256"], "recorded_at": row["at"]}
            kind = row["kind"]
            if kind == "freeze":
                _require(state["freeze"] is None, "integrity", "Duplicate replay freeze.")
                state["freeze"] = item
            elif kind == "boundary_receipt":
                rid = item["receipt_id"]
                _require(rid not in receipts, "integrity", "Duplicate boundary receipt ID.")
                receipts[rid] = item
                state["calibrations" if item["partition"] == "calibration" else "validations"].append(item)
            elif kind in {"prediction_seal", "response_receipt"}:
                rid = item["receipt_id"]
                _require(rid in receipts, "integrity", "Seal/response has no earlier boundary receipt.")
                record = receipts[rid]
                if kind == "prediction_seal":
                    _require(record["prediction_seal_sha256"] is None and record["response_status"] == "pending" and item["boundary_receipt_sha256"] == record["record_sha256"], "integrity", "Prediction must seal its exact boundary receipt once before responses.")
                    record.update({key: item[key] for key in ("prediction_status", "prediction", "prediction_artifacts", "prediction_seal_sha256", "sealed_at",
                                                            "prediction_qualified", "balance_audit", "balance_audit_artifacts")})
                    record["prediction_record_sha256"] = row["sha256"]
                else:
                    _require(record["prediction_seal_sha256"] is not None and record["response_status"] == "pending" and item["prediction_seal_sha256"] == record["prediction_seal_sha256"], "integrity", "Response must join an already sealed prediction exactly once.")
                    record.update({key: item[key] for key in ("response_status", "responses", "response_errors", "response_received_at", "response_attachments", "response_sha256", "suspected_reuse_matches", "comparison")})
                    record["response_record_sha256"] = row["sha256"]
            else:
                raise BenchReplayError("integrity", "Unknown replay ledger event kind.")
        consumed = {r["event"]["event_id"] for r in state["validations"]}
        pending = [e["event_id"] for e in state["freeze"]["validation_plan"] if e["event_id"] not in consumed] if state["freeze"] else []
        open_responses = [r["receipt_id"] for r in receipts.values() if r["response_status"] == "pending"]
        state.update(pending_validation_event_ids=pending, pending_response_receipt_ids=open_responses,
                     status="calibration" if state["freeze"] is None else "withheld_pending" if pending or open_responses else "withheld_records_complete", **_FLAGS)
        return state

    def list_studies(self):
        return [{key: state[key] for key in ("study_id", "title", "evidence_kind", "version", "status", "created_at")}
                for state in [self.get(row[0]) for row in self.db.execute("SELECT id FROM replay_studies ORDER BY rowid")]]

    def verify(self, study_id):
        try:
            state = self.get(study_id)
            expected = state["freeze"]["lineage"] if state["freeze"] else None
            current = _lineage()
            matches = expected == current if expected is not None else None
            study_matches = state["created_lineage"] == current
            return {"valid": matches is not False and study_matches, "integrity_valid": True, "current_runtime_matches_freeze": matches,
                    "current_runtime_matches_study": study_matches,
                    "study_id": study_id, "version": state["version"], "head_sha256": state["head_sha256"],
                    "errors": [] if matches is not False and study_matches else ["Current replay/model/audit/engine/protocol differs from the creation or frozen lineage."], **_FLAGS}
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as exc:
            return {"valid": False, "integrity_valid": False, "study_id": study_id, "errors": [str(exc)], **_FLAGS}

    def _checked(self, study_id, expected_version):
        state = self.get(study_id)
        _require(type(expected_version) is int and expected_version == state["version"], "stale_version", "Study changed; read its current version before writing.")
        last = self.db.execute("SELECT at FROM replay_events WHERE study_id=? ORDER BY version DESC LIMIT 1", (study_id,)).fetchone()[0]
        _require(timestamp(_now()) >= timestamp(last), "clock_rollback", "Server receipt clock moved backwards.")
        return state

    def create_study(self, site_package, *, title):
        site, raw = _raw(site_package)
        check = validate_site_package(site)
        _require(check.get("valid") is True, "site", canonical_json(check.get("errors", [])))
        _text(title, "Study title")
        lineage, protocol = _lineage(), load_protocol()
        with self._transaction():
            sid, at = "REPLAY-" + uuid.uuid4().hex, _now()
            self.db.execute("INSERT INTO replay_studies VALUES (?,0)", (sid,))
            digest = self._blob(raw)
            self._append(sid, "created", {"schema_version": SCHEMA_VERSION, "study_id": sid, "title": title,
                "evidence_kind": "synthetic_fixture" if site["evidence_kind"] == "synthetic_fixture" else "measured_bench",
                "site_package": site, "site_package_sha256": check["package_sha256"], "site_blob_sha256": digest,
                "protocol": protocol, "protocol_sha256": PROTOCOL_SHA256, "created_lineage": lineage, "blob_sha256s": [digest],
                "scope": "Separate whole-event dry-start boundary-replay slice; prepared/wet replay and full physical protocol completion are unsupported.", **_FLAGS}, at)
        return self.get(sid)

    def _attachments(self, raw, raw_files, reserved):
        files = {} if raw_files is None else raw_files
        _require(isinstance(files, dict) and len(files) <= 8, "attachments", "Supply at most eight plain-basename evidence attachments.")
        result = [{"name": reserved, "sha256": self._blob(raw), "size": len(raw)}]
        total = 0
        for name, data in files.items():
            _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", name) is not None and
                     ".." not in name and name.lower() not in {"boundaries.json", "responses.json"}, "attachment_path", "Attachments need safe basenames; boundaries.json and responses.json are reserved.")
            _require(isinstance(data, bytes) and 0 < len(data) <= MAX_ATTACHMENT_BYTES, "attachments", "Attachment must contain 1 byte–8 MiB of raw bytes.")
            total += len(data)
            _require(total <= 2 * MAX_ATTACHMENT_BYTES, "attachments", "Total attachments exceed 16 MiB.")
            result.append({"name": name, "sha256": self._blob(data), "size": len(data)})
        return result

    def _find_receipt(self, state, receipt_id):
        record = next((r for r in state["calibrations"] + state["validations"] if r["receipt_id"] == receipt_id), None)
        _require(record is not None, "unknown_receipt", "Boundary receipt does not belong to this study.")
        return record

    def _reserve(self, state, model, recipe, event, boundaries, raw_files, partition, source_raw):
        _require(not state["pending_response_receipt_ids"], "open_receipt", "Close the earlier receipt's prediction/response stages before reserving another event.")
        at, lineage = _now(), _lineage()
        _require(state["created_lineage"] == lineage, "lineage_changed", "Current replay/model/audit/runtime/protocol differs from study creation; start a new study before reserving an event.")
        if state["evidence_kind"] == "measured_bench":
            _require(timestamp(event["window"]["end_at"]) <= timestamp(at), "future_receipt", "Measured event must end before any boundary receipt can be reserved.")
        raw = _capture(boundaries)
        attachments = self._attachments(raw, raw_files, "boundaries.json")
        value, run, semantic, errors = None, None, None, []
        try:
            value, run, semantic = _boundaries(raw, event, recipe, state["site_package"], model, state["evidence_kind"], at)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            errors = [{"code": getattr(exc, "code", "boundary_schema"), "message": str(exc)}]
        source_blobs = {name: self._blob(data) for name, data in source_raw.items()}
        attempt_relative_path = uuid.uuid4().hex
        (self.artifact_root / attempt_relative_path).mkdir()
        record = {"receipt_id": "RECEIPT-" + uuid.uuid4().hex, "partition": partition, "evidence_kind": state["evidence_kind"],
                  "event": event, "model_spec": model, "model_sha256": content_sha256(model), "recipe": recipe, "recipe_sha256": content_sha256(recipe),
                  "source_blobs": source_blobs, "boundary_received_at": at, "lineage": lineage, "boundaries": value,
                  "boundary_status": "invalid" if errors else "valid", "boundary_errors": errors, "boundary_attachments": attachments,
                  "boundary_content_sha256": semantic, "derived_run": run, "derived_run_sha256": content_sha256(run) if run else None,
                  "attempt_relative_path": attempt_relative_path,
                  "prediction_origin": "internally_run_measured_boundary_replay", "prediction_status": "pending", "prediction": None,
                  "prediction_qualified": False, "balance_audit": None, "balance_audit_artifacts": [],
                  "prediction_artifacts": [], "prediction_seal_sha256": None, "response_status": "pending", "responses": None,
                  "comparison": _unresolved("Responses have not been received; no response fields were supplied to this replay stage."),
                  "blob_sha256s": [item["sha256"] for item in attachments] + list(source_blobs.values()), **_FLAGS}
        version, digest = self._append(state["study_id"], "boundary_receipt", record, at)
        return record["receipt_id"], version, digest

    def record_calibration_boundaries(self, study_id, expected_version, *, model_spec, recipe, event, boundaries, raw_files=None):
        """Reserve/execute one calibration attempt before any response receipt."""
        with self._transaction():
            state = self._checked(study_id, expected_version)
            _require(state["freeze"] is None and len(state["calibrations"]) < 50, "calibration_closed", "Calibration is closed after freeze or 50 attempts.")
            model, model_raw = _raw(model_spec)
            parsed_recipe, recipe_raw = _raw(recipe)
            parsed_recipe = _recipe(parsed_recipe, state["site_package"], model, state["evidence_kind"])
            parsed_event, event_raw = _raw(event)
            parsed_event = _event(parsed_event, state["site_package"], model, parsed_recipe, state["evidence_kind"])
            # Repeating a calibration observation across candidates is allowed;
            # an exact candidate+recipe+event attempt cannot be replaced/retried.
            _require(not any(r["event"]["event_id"] == parsed_event["event_id"] and r["model_sha256"] == content_sha256(model) and
                             r["recipe_sha256"] == content_sha256(parsed_recipe) for r in state["calibrations"]), "duplicate_attempt", "This candidate/recipe/event attempt already exists; failed attempts cannot be replaced.")
            rid, version, _ = self._reserve(state, model, parsed_recipe, parsed_event, boundaries, raw_files, "calibration",
                                           {"model": model_raw, "recipe": recipe_raw, "event": event_raw})
        return self._seal_reserved(study_id, version, rid)

    def record_validation_boundaries(self, study_id, expected_version, *, event_id, boundaries, raw_files=None):
        """Consume the next frozen boundary assignment using later supplied values."""
        with self._transaction():
            state = self._checked(study_id, expected_version)
            freeze = state["freeze"]
            _require(freeze is not None, "freeze_required", "Freeze a calibrated model/recipe and future assignments before validation receipt.")
            _require(freeze["lineage"] == _lineage(), "lineage_changed", "Current replay/model/runtime/protocol differs from the immutable freeze.")
            _require(state["pending_validation_event_ids"] and event_id == state["pending_validation_event_ids"][0], "validation_order", "Receive the next frozen event once and in order; failure does not reopen it.")
            event = next(e for e in freeze["validation_plan"] if e["event_id"] == event_id)
            rid, version, _ = self._reserve(state, freeze["model_spec"], freeze["recipe"], event, boundaries, raw_files, "validation", {})
        return self._seal_reserved(study_id, version, rid)

    def _retain_artifact(self, path, name):
        data = path.read_bytes()
        return {"name": name, "relative_path": path.relative_to(self.artifact_root).as_posix(),
                "size": len(data), "sha256": self._blob(data)}

    def _predict(self, state, record, folder):
        artifacts, result = [], None
        run, model, lineage = record["derived_run"], record["model_spec"], record["lineage"]
        if record["boundary_status"] != "valid":
            return {"valid": False, "status": "boundary_unresolved", "timeseries": [], "errors": record["boundary_errors"], **_FLAGS}, []
        try:
            _require(_lineage() == lineage, "lineage_changed", "Runtime/source changed after the durable boundary receipt; no new model identity may replace it.")
            result = bench_model.run_bench_model(state["site_package"], model, run, folder)
            _require(isinstance(result, dict), "prediction", "Internal adapter returned no result object.")
            _require(_lineage() == lineage, "lineage_changed", "Runtime/source changed during boundary replay.")
            if result.get("valid") is True:
                _require(result.get("engine_identity") == lineage["engine_identity"] and result.get("site_package_sha256") == state["site_package_sha256"] and
                         result.get("model_sha256") == record["model_sha256"] and result.get("run_sha256") == record["derived_run_sha256"], "prediction_binding", "Internal prediction is bound to a different site/model/derived boundary run/runtime.")
                _require(result.get("status") == "succeeded" and result.get("step_halving", {}).get("passed") is True, "numerics", "Prediction needs a successful automatic paired step-halving check.")
                verification = bench_model.verify_bench_result(result)
                _require(verification.get("valid") is True, "artifact_integrity", "Internal paired prediction verification failed: " + canonical_json(verification.get("errors", [])))
                _require(set(result.get("files", {})) == _PAIR_FILES, "artifact_inventory", "A usable replay requires the complete exact 18-file native paired artifact inventory.")
                _require(isinstance(result.get("timeseries"), list) and [row.get("elapsed_s") for row in result["timeseries"]] == _grid(model, record["recipe"]), "prediction_grid", "Internal prediction must retain every exact report-grid endpoint.")
                for row in result["timeseries"]:
                    _number(row["elapsed_s"], "Prediction time", minimum=0)
            paths = result.get("files", {})
            _require(isinstance(paths, dict) and len(paths) <= 24, "artifact_inventory", "Internal prediction artifact inventory exceeds its bound.")
            pair_root = Path(paths.get("result.json", folder / "result.json")).resolve().parent
            _require(pair_root.is_relative_to(folder.resolve()), "artifact_integrity", "Prediction pair folder escaped the private attempt.")
            total = 0
            for name, supplied in paths.items():
                relative = PurePosixPath(name)
                _require(isinstance(name, str) and not relative.is_absolute() and ".." not in relative.parts and "\\" not in name and ":" not in name and str(relative) == name,
                         "artifact_integrity", "Unsafe internal artifact name.")
                path = Path(supplied)
                _require(path.resolve() == (pair_root / name).resolve() and path.resolve().is_relative_to(folder.resolve()) and
                         not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(folder)) and path.is_file() and path.stat().st_size <= MAX_ARTIFACT_BYTES,
                         "artifact_integrity", "Internal artifact path is missing, unsafe, or oversized.")
                total += path.stat().st_size
                _require(total <= 4 * MAX_ARTIFACT_BYTES, "artifact_size", "Paired evidence exceeds the bounded storage size.")
                artifacts.append(self._retain_artifact(path, name))
            stored = next((item for item in artifacts if item["name"] == "result.json"), None)
            _require(stored is None or _parsed(self._artifact_bytes(stored)) == result, "artifact_integrity", "Internal result differs from the retained result.json bytes.")
            manifest = next((item for item in artifacts if item["name"] == "manifest.json"), None)
            if manifest is not None:
                value = _parsed(self._artifact_bytes(manifest))
                _require(value.get("schema_version") == "monsoon.bench-pair-evidence/1" and value.get("file_sha256") ==
                         {item["name"]: item["sha256"] for item in artifacts if item["name"] != "manifest.json"},
                         "artifact_integrity", "Paired manifest does not match every retained native artifact.")
            for item in artifacts:
                self._artifact_bytes(item)
            # Failed numerical attempts remain failed even if their evidence is
            # locally consistent. They never provide usable response columns.
            _parsed(result)
        except Exception as exc:
            previous_errors = result.get("errors", []) if isinstance(result, dict) else []
            result = {"valid": False, "status": "failed", "timeseries": [],
                      "errors": [{"code": getattr(exc, "code", "prediction_failed"), "message": f"{type(exc).__name__}: {exc}"}],
                      "retained_adapter_errors": previous_errors, **_FLAGS}
            artifacts, total = [], 0
            # Preserve safe bounded failed-attempt bytes without allowing an
            # invalid output inventory to erase the already committed receipt.
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()):
                    if len(artifacts) >= 24 or path.stat().st_size > MAX_ARTIFACT_BYTES or total + path.stat().st_size > 4 * MAX_ARTIFACT_BYTES:
                        result["errors"].append({"code": "failed_artifact_limit", "message": "Additional failed-attempt artifact exceeds bounded safe retention; no metrics released."})
                        continue
                    total += path.stat().st_size
                    artifacts.append(self._retain_artifact(path, path.relative_to(folder).as_posix()))
        return result, artifacts

    def _audit_prediction(self, state, record, prediction, folder):
        if prediction.get("valid") is not True:
            return {"valid": False, "status": "not_attempted", "errors": ["Native paired replay is unresolved; no numerical audit qualification."], **_FLAGS}, []
        output = folder / "balance-audit"
        output.mkdir()
        artifacts, audit = [], None
        try:
            audit = bench_balance_audit.audit_bench_balance(prediction, output)
            _require(isinstance(audit, dict) and audit.get("audit_identity") == record["lineage"]["balance_audit_identity"] and
                     _lineage() == record["lineage"], "audit_lineage", "Balance audit/runtime/source does not match the boundary receipt lineage.")
            checked = bench_balance_audit.verify_bench_balance_audit(audit, prediction)
            _require(checked.get("valid") is True, "audit_integrity", "Additional balance audit evidence failed verification: " + canonical_json(checked.get("errors", [])))
            if audit.get("valid") is True:
                _require(audit.get("status") == "succeeded" and audit.get("rule") == bench_balance_audit.RULE and
                         all(audit.get("attempts", {}).get(label, {}).get("valid") is True for label in ("base", "half")),
                         "audit_qualification", "A usable audit requires both actual numerical attempts to pass its frozen every-step rule.")
            paths = audit.get("files", {})
            _require(isinstance(paths, dict) and set(paths) == _PAIR_FILES, "audit_inventory", "Numerical audit must retain its exact complete 18-file evidence inventory.")
            root = Path(paths["result.json"]).resolve().parent
            _require(root.is_relative_to(output.resolve()), "audit_integrity", "Audit evidence escaped its private attempt directory.")
            total = 0
            for name, supplied in paths.items():
                path = Path(supplied)
                _require(path.resolve() == (root / name).resolve() and path.resolve().is_relative_to(output.resolve()) and
                         not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(output)) and path.is_file() and path.stat().st_size <= MAX_ARTIFACT_BYTES,
                         "audit_integrity", "Audit artifact is missing, unsafe, or oversized.")
                total += path.stat().st_size
                _require(total <= 4 * MAX_ARTIFACT_BYTES, "audit_size", "Audit evidence exceeds the bounded retention size.")
                artifacts.append(self._retain_artifact(path, name))
            saved = next(item for item in artifacts if item["name"] == "result.json")
            _require(_parsed(self._artifact_bytes(saved)) == audit, "audit_integrity", "Audit object differs from its retained result.json bytes.")
            manifest = _parsed(self._artifact_bytes(next(item for item in artifacts if item["name"] == "manifest.json")))
            _require(manifest.get("schema_version") == "monsoon.bench-balance-audit-pair-evidence/1" and manifest.get("file_sha256") ==
                     {item["name"]: item["sha256"] for item in artifacts if item["name"] != "manifest.json"},
                     "audit_integrity", "Audit manifest does not match every retained additional native artifact.")
            for item in artifacts:
                self._artifact_bytes(item)
            _parsed(audit)
        except Exception as exc:
            audit = {"valid": False, "status": "audit_unresolved", "errors": [{"code": getattr(exc, "code", "audit_failed"), "message": f"{type(exc).__name__}: {exc}"}], **_FLAGS}
            artifacts, total = [], 0
            for path in sorted(output.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(output.resolve()):
                    if len(artifacts) >= 24 or path.stat().st_size > MAX_ARTIFACT_BYTES or total + path.stat().st_size > 4 * MAX_ARTIFACT_BYTES:
                        audit["errors"].append({"code": "failed_audit_artifact_limit", "message": "Additional failed audit bytes exceed safe bounded retention."})
                        continue
                    total += path.stat().st_size
                    artifacts.append(self._retain_artifact(path, path.relative_to(output).as_posix()))
        return audit, artifacts

    def _write_seal(self, state, record, prediction, artifacts, folder, status, audit, audit_artifacts):
        at = _now()
        qualified = prediction.get("valid") is True and audit.get("valid") is True and status == "sealed"
        seal = {"schema_version": "monsoon.bench-boundary-prediction-seal/1", "receipt_id": record["receipt_id"],
                "generated_at": at, "boundary_receipt_sha256": record["record_sha256"], "boundary_raw_sha256": record["boundary_attachments"][0]["sha256"],
                "boundary_content_sha256": record["boundary_content_sha256"], "site_package_sha256": state["site_package_sha256"],
                "model_sha256": record["model_sha256"], "recipe_sha256": record["recipe_sha256"], "derived_run_sha256": record["derived_run_sha256"],
                "lineage": record["lineage"], "prediction_status": status, "response_receipt_present": False,
                "prediction": prediction, "artifact_sha256": {item["name"]: item["sha256"] for item in artifacts}, **_FLAGS}
        seal.update(prediction_qualified=qualified, balance_audit=audit,
                    balance_audit_artifact_sha256={item["name"]: item["sha256"] for item in audit_artifacts})
        raw = (canonical_json(seal) + "\n").encode("utf-8")
        path = folder / ("replay-interrupted-prediction.json" if status == "interrupted" else "replay-prediction.json")
        with path.open("xb") as stream:
            stream.write(raw)
        item = self._retain_artifact(path, path.name)
        artifacts.append(item)
        reread = _parsed(self._artifact_bytes(item))
        payload = {"receipt_id": record["receipt_id"], "boundary_receipt_sha256": record["record_sha256"], "sealed_at": at,
                   "prediction_status": status, "prediction": reread["prediction"], "prediction_artifacts": artifacts,
                   "prediction_seal_sha256": item["sha256"], "prediction_qualified": qualified, "balance_audit": audit,
                   "balance_audit_artifacts": audit_artifacts, "blob_sha256s": [a["sha256"] for a in artifacts + audit_artifacts], **_FLAGS}
        self._append(state["study_id"], "prediction_seal", payload, at)

    def _seal_reserved(self, study_id, expected_version, receipt_id):
        with self._transaction():
            state = self._checked(study_id, expected_version)
            record = self._find_receipt(state, receipt_id)
            _require(record["prediction_status"] == "pending" and record["prediction_seal_sha256"] is None, "already_sealed", "This boundary attempt was already sealed; no replacement execution is allowed.")
            folder = self.artifact_root / record["attempt_relative_path"]
            _require(folder.is_dir() and not folder.is_symlink() and folder.resolve().is_relative_to(self.artifact_root.resolve()), "artifact_integrity", "Reserved attempt directory is missing or unsafe.")
            prediction, artifacts = self._predict(state, record, folder)
            audit, audit_artifacts = self._audit_prediction(state, record, prediction, folder)
            self._write_seal(state, record, prediction, artifacts, folder, "sealed", audit, audit_artifacts)
        state = self.get(study_id)
        return {"study": state, "record": self._find_receipt(state, receipt_id)}

    def close_interrupted_receipt(self, study_id, expected_version, *, receipt_id, reason):
        """Close an abandoned reservation unresolved, without ever rerunning it."""
        _text(reason, "Interruption reason")
        with self._transaction():
            state = self._checked(study_id, expected_version)
            record = self._find_receipt(state, receipt_id)
            _require(record["prediction_status"] == "pending" and record["prediction_seal_sha256"] is None, "already_sealed", "Only an unsealed interrupted reservation can be closed.")
            folder = self.artifact_root / record["attempt_relative_path"]
            _require(folder.is_dir() and not folder.is_symlink() and folder.resolve().is_relative_to(self.artifact_root.resolve()), "artifact_integrity", "Reserved interrupted attempt directory is missing or unsafe.")
            prediction = {"valid": False, "status": "interrupted", "timeseries": [],
                          "errors": [{"code": "interrupted_no_retry", "message": reason}], **_FLAGS}
            artifacts, total = [], 0
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()):
                    if len(artifacts) >= 48 or path.stat().st_size > MAX_ARTIFACT_BYTES or total + path.stat().st_size > 8 * MAX_ARTIFACT_BYTES:
                        prediction["errors"].append({"code": "interrupted_artifact_limit", "message": "Partial artifact exceeds bounded safe retention; attempt remains unresolved."})
                        continue
                    total += path.stat().st_size
                    artifacts.append(self._retain_artifact(path, path.relative_to(folder).as_posix()))
            self._write_seal(state, record, prediction, artifacts, folder, "interrupted",
                             {"valid": False, "status": "not_attempted", "errors": ["Interrupted replay never qualifies."], **_FLAGS}, [])
        state = self.get(study_id)
        return {"study": state, "record": self._find_receipt(state, receipt_id)}

    def _reuse(self, response_hash, partition):
        matches = []
        for row in self.db.execute("SELECT id FROM replay_studies"):
            state = self.get(row[0])
            for old in state["calibrations"] + state["validations"]:
                if old.get("response_sha256") == response_hash and not old["partition"] == partition == "calibration":
                    matches.append({"study_id": state["study_id"], "receipt_id": old["receipt_id"], "partition": old["partition"]})
        return matches

    def record_responses(self, study_id, expected_version, *, receipt_id, responses, raw_files=None):
        """Retain one response attempt after its boundary-only prediction seal.

        A bounded malformed/missing receipt consumes this stage and stores its
        exact attempted bytes and errors. There is no favourable replacement.
        """
        with self._transaction():
            state = self._checked(study_id, expected_version)
            record = self._find_receipt(state, receipt_id)
            _require(record["prediction_seal_sha256"] is not None, "seal_required", "Seal the boundary-only prediction before accepting any response receipt; interrupted reservations must close unresolved.")
            _require(record["response_status"] == "pending", "response_consumed", "This response stage is already consumed; failed or malformed receipts cannot be replaced.")
            raw, at = _capture(responses), _now()
            attachments = self._attachments(raw, raw_files, "responses.json")
            value, semantic, errors, matches = None, None, [], []
            try:
                value, semantic = _responses(raw, record["event"], record["recipe"], record["model_spec"], state["evidence_kind"], at)
                matches = self._reuse(semantic, record["partition"])
                _require(_lineage() == record["lineage"], "lineage_changed", "Current replay/runtime/protocol differs from the sealed prediction; response is retained unresolved.")
                # Recheck the seal and all original bytes after intake, before
                # calculations; get() already verifies the complete chain.
                for item in record["prediction_artifacts"] + record["balance_audit_artifacts"]:
                    self._artifact_bytes(item)
                sealed = _parsed(self._read_blob(record["prediction_seal_sha256"]))
                _require(sealed["prediction"] == record["prediction"] and sealed["boundary_receipt_sha256"] == record["record_sha256"], "seal_integrity", "Prediction seal differs from the received boundary record/result.")
                _require(sealed["balance_audit"] == record["balance_audit"] and sealed["prediction_qualified"] == record["prediction_qualified"], "seal_integrity", "Prediction qualification or balance audit differs from the sealed evidence.")
                if matches:
                    comparison = _unresolved("Suspected semantic response reuse across calibration/withheld partitions; no numeric residuals released.")
                elif not record["prediction_qualified"]:
                    comparison = _unresolved("Native paired replay or its additional every-step balance audit is unresolved; no conditional response residuals are released.")
                else:
                    checked = bench_balance_audit.verify_bench_balance_audit(record["balance_audit"], record["prediction"])
                    _require(checked.get("valid") is True, "audit_integrity", "Retained additional balance audit no longer verifies against its exact native parent.")
                    comparison = _comparison(value, record["recipe"], sealed["prediction"])
            except (ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
                errors = [{"code": getattr(exc, "code", "response_schema"), "message": str(exc)}]
                comparison = _unresolved("Response attempt retained unresolved; this receipt cannot be replaced.", errors)
            response = {"receipt_id": receipt_id, "prediction_seal_sha256": record["prediction_seal_sha256"], "response_received_at": at,
                        "response_status": "invalid" if errors else "received", "responses": value, "response_errors": errors,
                        "response_attachments": attachments, "response_sha256": semantic, "suspected_reuse_matches": matches,
                        "comparison": comparison, "blob_sha256s": [item["sha256"] for item in attachments], **_FLAGS}
            self._append(study_id, "response_receipt", response, _now())
        state = self.get(study_id)
        return {"study": state, "record": self._find_receipt(state, receipt_id)}

    def freeze_study(self, study_id, expected_version, *, selected_model_sha256, selected_recipe_sha256, validation_plan, rationale):
        with self._transaction():
            state = self._checked(study_id, expected_version)
            _require(state["freeze"] is None, "already_frozen", "Model/recipe may be frozen only once; changes need a new prospective study.")
            _require(not state["pending_response_receipt_ids"], "open_receipt", "Complete or close every calibration receipt before freezing.")
            _text(rationale, "Manual model/recipe selection rationale")
            selected = [r for r in state["calibrations"] if r["model_sha256"] == selected_model_sha256 and r["recipe_sha256"] == selected_recipe_sha256]
            complete = [r for r in selected if r["prediction"].get("valid") is True and r["prediction_qualified"] is True and
                        r["response_status"] == "received" and r["comparison"]["status"] == "resolved_errors"]
            _require(complete, "calibration_required", "Freeze requires a complete nonempty internally generated calibration residual record for this exact model and recipe.")
            lineage = _lineage()
            _require(state["created_lineage"] == lineage, "lineage_changed", "Current replay/model/audit/runtime/protocol differs from study creation; a clean freeze requires a new study.")
            _require(all(r["lineage"] == lineage for r in selected), "lineage_changed", "Selected calibration attempts differ from current exact replay/model/runtime/protocol lineage.")
            _require(isinstance(validation_plan, list) and 1 <= len(validation_plan) <= 24, "validation_plan", "Freeze 1–24 future withheld assignments for the bounded cold-start replay slice.")
            model, recipe = selected[0]["model_spec"], selected[0]["recipe"]
            _recipe(recipe, state["site_package"], model, state["evidence_kind"])
            plan_raw = [_capture(e) for e in validation_plan]
            plan = [_event(e, state["site_package"], model, recipe, state["evidence_kind"]) for e in plan_raw]
            identifiers = [event["event_id"] for event in plan]
            calibration_ids = {r["event"]["event_id"] for r in state["calibrations"]}
            _require(len(set(identifiers)) == len(identifiers) and not set(identifiers) & calibration_ids, "partition_ids", "Validation IDs must be distinct and cannot reuse any calibration event ID.")
            if state["evidence_kind"] == "measured_bench":
                for left, right in zip(plan, plan[1:]):
                    _require(timestamp(left["window"]["end_at"]) <= timestamp(right["window"]["start_at"]), "window_order", "Measured validation windows must follow the frozen nonoverlapping order.")
            plan_blobs = [self._blob(raw) for raw in plan_raw]
            plan_digest, response_grid = content_sha256(plan), _grid(model, recipe)
            # No actual validation boundary/response values are accepted by this
            # API. Read the final server instant only after source/plan checks.
            _require(_lineage() == lineage, "lineage_changed", "Source/runtime changed while preparing the freeze.")
            now = _now()
            if state["evidence_kind"] == "measured_bench":
                earliest = timestamp(now) + timedelta(seconds=MINIMUM_FREEZE_LEAD_SECONDS)
                _require(all(timestamp(event["window"]["start_at"]) >= earliest for event in plan), "prospectivity", "Every measured assignment must begin at least 60 seconds after the final server freeze instant.")
            freeze = {"frozen_at": now, "model_spec": model, "model_sha256": selected_model_sha256, "recipe": recipe, "recipe_sha256": selected_recipe_sha256,
                      "site_package_sha256": state["site_package_sha256"], "lineage": lineage, "validation_plan": plan,
                      "validation_plan_sha256": plan_digest, "boundary_schema": BOUNDARY_SCHEMA, "response_schema": RESPONSE_SCHEMA,
                      "validation_plan_blob_sha256s": plan_blobs, "blob_sha256s": plan_blobs,
                      "response_grid_s": response_grid, "actual_validation_boundary_values_known": False,
                      "selected_calibration_receipt_ids": [r["receipt_id"] for r in complete],
                      "calibration_record_sha256s": [{"boundary": r["record_sha256"], "prediction": r["prediction_record_sha256"], "response": r["response_record_sha256"]} for r in state["calibrations"]],
                      "selected_prediction_seal_sha256s": [r["prediction_seal_sha256"] for r in complete], "rationale": rationale,
                      "scope": state["scope"], **_FLAGS}
            self._append(study_id, "freeze", freeze, now)
        state = self.get(study_id)
        return {"study": state, "freeze": state["freeze"]}

    def export_evidence(self, study_id):
        """Return a verified ZIP snapshot; historical artifact paths stay literal.

        This is an evidence export, not a portable database restore, rewritten
        result bundle, runtime copy, or independent authenticity attestation.
        """
        with self._transaction():
            state = self.get(study_id)
            current = _lineage()
            records = state["calibrations"] + state["validations"]
            _require(state["created_lineage"] == current and all(r["lineage"] == current for r in records) and
                     (state["freeze"] is None or state["freeze"]["lineage"] == current),
                     "lineage_changed", "Current replay/model/audit/runtime/protocol differs from this study's historical lineage; verified export is blocked.")
            _require(all(r["prediction_seal_sha256"] is not None for r in records), "unsealed_export", "Close interrupted pending predictions before exporting their complete retained evidence.")
            files, total = {}, 0

            def add(name, raw):
                nonlocal total
                path = PurePosixPath(name)
                _require(not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name and str(path) == name and name not in files,
                         "export_path", "Unsafe or duplicate ZIP evidence name.")
                total += len(raw)
                _require(total <= 512 * 1024 * 1024, "export_size", "Verified export exceeds the 512 MiB uncompressed bound.")
                files[name] = raw

            def encoded(value):
                return (canonical_json(value) + "\n").encode("utf-8")

            add("study.json", encoded(state))
            add("ledger/events.json", encoded({"schema_version": SCHEMA_VERSION, "events": self._events(study_id)}))
            add("site/site.json", self._read_blob(state["site_blob_sha256"]))
            if state["freeze"] is not None:
                add("freeze/freeze.json", encoded(state["freeze"]))
                for index, digest in enumerate(state["freeze"]["validation_plan_blob_sha256s"], 1):
                    add(f"freeze/validation-events/{index:02d}.json", self._read_blob(digest))
            for record in records:
                prefix = "records/" + record["receipt_id"]
                add(prefix + "/record.json", encoded(record))
                for name, digest in record["source_blobs"].items():
                    add(prefix + "/raw-contracts/" + name + ".json", self._read_blob(digest))
                for field, directory in (("boundary_attachments", "boundaries"), ("response_attachments", "responses")):
                    for item in record.get(field, []):
                        raw = self._read_blob(item["sha256"])
                        _require(len(raw) == item["size"], "blob_integrity", "Receipt attachment size changed.")
                        add(prefix + "/" + directory + "/" + item["name"], raw)
                for field, directory in (("prediction_artifacts", "prediction"), ("balance_audit_artifacts", "balance-audit")):
                    for item in record[field]:
                        add(prefix + "/" + directory + "/" + item["name"], self._artifact_bytes(item))
            _require(_lineage() == current, "lineage_changed", "Runtime/source changed while collecting export bytes.")
            manifest = {"schema_version": "monsoon.bench-replay-export/1", "study_id": study_id,
                        "version": state["version"], "head_sha256": state["head_sha256"], "evidence_kind": state["evidence_kind"],
                        "status": state["status"], "lineage": current,
                        "interpretation": "Exact local evidence snapshot. Original absolute paths inside retained records/results are unchanged; this ZIP is not a portable replay database or authenticity proof.",
                        "files": {name: {"sha256": _hash(raw), "size": len(raw)} for name, raw in sorted(files.items())}, **_FLAGS}
            files["manifest.json"] = encoded(manifest)
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, raw in sorted(files.items()):
                    archive.writestr(name, raw)
            return output.getvalue()
