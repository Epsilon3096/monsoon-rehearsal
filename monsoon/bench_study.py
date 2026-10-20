"""Local, immutable research calibration/freeze/withheld-run ledger.

Predictions are produced internally by the separate bench adapter. Supplied
observation files are unverified evidence; local receipt order is not proof of
witnessed physical prospectivity. No fitting or operational approval occurs.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from .measurements import PROTOCOL_PATH, PROTOCOL_SHA256, load_protocol
from .site_data import canonical_json, content_sha256, parse_json, timestamp, validate_site_package

SCHEMA_VERSION = "monsoon.bench-study/1"
OBSERVATION_SCHEMA = "monsoon.bench-observations/1"
MAX_CALIBRATIONS = 50
MAX_VALIDATIONS = 24
MAX_SAMPLES = 4001
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MINIMUM_FREEZE_LEAD_SECONDS = 60
_LOADED_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_UNITS = {"stage_m": "m", "outflow_m3_s": "m3/s", "spill_m3_s": "m3/s", "storage_m3": "m3"}
_FLAGS = {"operational_activation_allowed": False, "physical_validation_established": False,
          "full_protocol_completed": False, "external_prospectivity_verified": False,
          "evidence_authenticity_verified": False, "automatic_fit_performed": False}
_COMPARISON_LIMITS = [
    "Predictions use the predeclared inflow/receiving-stage forcing, not a replay or verification of measured boundary traces; actual forcing reproduction remains unassessed.",
    "These are response error summaries, not the frozen physical protocol's uncertainty-aware acceptance or complete water-balance assessment.",
    "Synthetic generated responses can check software plumbing only, including when numerical residuals are zero.",
]


class BenchStudyError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _require(condition, code, message):
    if not condition:
        raise BenchStudyError(code, message)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _keys(value, fields, name):
    _require(isinstance(value, dict) and set(value) == set(fields), "schema", f"{name} requires exactly its documented fields.")


def _text(value, name, *, identifier=False):
    _require(isinstance(value, str) and bool(value.strip()) and len(value) <= 4000, "text", f"{name} requires bounded nonempty text.")
    if identifier:
        _require(re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}", value) is not None, "id", f"{name} is not a supported identifier.")
    return value


def _number(value, name, *, minimum=None):
    _require(type(value) in (int, float), "number", f"{name} requires a finite number, not a boolean or string.")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise BenchStudyError("number", f"{name} exceeds numeric limits.") from exc
    _require(math.isfinite(value) and (minimum is None or value >= minimum), "number", f"{name} is outside its finite supported range.")
    return value


def _parsed(payload):
    try:
        return parse_json(payload)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise BenchStudyError("json", str(exc)) from exc


def _raw(payload):
    parsed = _parsed(payload)
    data = payload if isinstance(payload, bytes) else payload.encode("utf-8") if isinstance(payload, str) else canonical_json(parsed).encode("utf-8")
    return parsed, data


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _adapter():
    from . import bench_model
    return bench_model


def _lineage():
    _require(_hash(Path(__file__).read_bytes()) == _LOADED_SHA256, "source_changed", "The study source changed after import; start a fresh process before a new study revision.")
    load_protocol()
    return {"study_source_sha256": _LOADED_SHA256, "protocol_sha256": PROTOCOL_SHA256,
            "protocol_file_sha256": _hash(PROTOCOL_PATH.read_bytes()), "engine_identity": _adapter().bench_engine_identity()}


def _grid(model, run):
    step, duration = model["numerics"]["report_step_s"], run["duration_s"]
    count = round(duration / step)
    _require(1 <= count < MAX_SAMPLES and math.isclose(count * step, duration, abs_tol=1e-9), "sample_grid", "Use a bounded complete engine report grid.")
    return [i * step for i in range(count + 1)]


def _event(payload, site, model, evidence_kind, *, now=None, prospective=False):
    e = _parsed(payload)
    _keys(e, {"event_id", "run", "window", "series"}, "Event")
    _text(e["event_id"], "Event ID", identifier=True)
    check = _adapter().validate_bench_run(site, model, e["run"])
    _require(check.get("valid") is True, "run_contract", canonical_json(check.get("errors", [])))
    _require(e["run"]["run_id"] == e["event_id"], "event_id", "Run ID and event ID must match.")
    _require(e["run"]["model_sha256"] == content_sha256(model), "model_binding", "Run must identify the exact model candidate.")
    _grid(model, e["run"])
    if evidence_kind == "synthetic_fixture":
        _require(e["window"] is None, "synthetic_clock", "Synthetic exercise windows must be null, not counterfeit measured UTC collection times.")
    else:
        _keys(e["window"], {"start_at", "end_at"}, "Measured window")
        start, end = (timestamp(e["window"][k]) for k in ("start_at", "end_at"))
        _require(start is not None and end is not None and start < end, "window", "Measured window needs ordered timezone-aware timestamps.")
        _require(math.isclose((end - start).total_seconds(), e["run"]["duration_s"], rel_tol=0, abs_tol=1e-6), "window", "Declared physical window must equal the frozen run duration.")
        if now is not None:
            _require(start > timestamp(now) if prospective else end <= timestamp(now), "prospectivity", "Validation assignments must begin after server freeze; received observations must already have ended.")
    _require(isinstance(e["series"], list) and 1 <= len(e["series"]) <= 64, "series", "Declare 1–64 response series.")
    nodes = {n["id"] for n in site["nodes"]}
    outfalls, spills = set(site["boundaries"]["outfall_node_ids"]), set(site["boundaries"]["spill_node_ids"])
    ids, locations = set(), set()
    for series in e["series"]:
        _keys(series, {"id", "quantity", "location_id", "unit", "expanded_uncertainty_abs", "source_id"}, "Response series")
        sid = _text(series["id"], "Series ID", identifier=True)
        _require(sid not in ids, "series", "Series IDs cannot repeat.")
        ids.add(sid)
        quantity, location = series["quantity"], series["location_id"]
        _require(isinstance(quantity, str) and quantity in _UNITS and isinstance(location, str), "response", "Only documented independent response quantities are accepted; prescribed inflow and receiving stage cannot be scored.")
        allowed = nodes - outfalls if quantity == "stage_m" else outfalls if quantity == "outflow_m3_s" else spills if quantity == "spill_m3_s" else {"SYSTEM"}
        _require(location in allowed and series["unit"] == _UNITS[quantity], "response", "Response location/unit mismatches its model role; no conversion is inferred.")
        _require((quantity, location) not in locations, "series", "Duplicate quantity/location response series are not independent evidence.")
        locations.add((quantity, location))
        _require(_number(series["expanded_uncertainty_abs"], "Expanded uncertainty", minimum=0) > 0, "uncertainty", "Declare positive absolute expanded uncertainty; no zero-by-assumption.")
        _text(series["source_id"], "Uncertainty/instrument source ID")
    return e


def _observations(payload, event, model, kind, now):
    obs, raw = _raw(payload)
    _keys(obs, {"schema_version", "event_id", "evidence_kind", "start_at", "end_at", "source_id", "notes", "samples"}, "Observations")
    _require(obs["schema_version"] == OBSERVATION_SCHEMA and obs["event_id"] == event["event_id"] and obs["evidence_kind"] == kind, "observation_binding", "Observation schema/event/evidence kind must match the study assignment.")
    _text(obs["source_id"], "Observation source ID")
    _text(obs["notes"], "Observation notes")
    window = event["window"] or {"start_at": None, "end_at": None}
    _require(all(obs[key] == window[key] for key in window), "window_binding", "Observed timestamps must match the assigned window; deviations require a separately retained nonconforming development record.")
    if kind == "measured_bench":
        _require(timestamp(obs["end_at"]) <= timestamp(now), "future_observation", "Future physical observations cannot be supplied before the server receipt time.")
    times = _grid(model, event["run"])
    _require(isinstance(obs["samples"], list) and len(obs["samples"]) == len(times), "samples", "Observations must cover the entire declared report grid, with explicit nulls for missing values.")
    by_id = {s["id"]: s for s in event["series"]}
    for expected, sample in zip(times, obs["samples"]):
        _keys(sample, {"elapsed_s", "observed"}, "Sample")
        _require(_number(sample["elapsed_s"], "Sample elapsed seconds", minimum=0) == expected, "sample_grid", "Sample times must match the exact engine grid; no interpolation or extrapolation occurs.")
        _keys(sample["observed"], by_id, "Observed response values")
        for sid, value in sample["observed"].items():
            if value is not None:
                minimum = 0 if by_id[sid]["quantity"] in {"spill_m3_s", "storage_m3"} else None
                _number(value, "Observed value", minimum=minimum)
    # Ignore caller labels when detecting reuse across the local partitions.
    response = [{"quantity": s["quantity"], "location_id": s["location_id"], "unit": s["unit"],
                 "values": [[row["elapsed_s"], row["observed"][s["id"]]] for row in obs["samples"]]}
                for s in sorted(event["series"], key=lambda item: (item["quantity"], item["location_id"]))]
    return obs, raw, content_sha256(response)


def _comparison(observations, event, prediction):
    report = {"status": "unresolved", "summary": "Numerical comparison remains unresolved.", "errors": [], "series": [],
              "acceptance_assessed": False, "physical_validation_established": False, "limitations": list(_COMPARISON_LIMITS)}
    if prediction.get("valid") is not True:
        report["errors"] = ["The internal model run failed numerical/lineage checks; no response error is credited."]
        return report
    for series in event["series"]:
        sid, quantity, location = series["id"], series["quantity"], series["location_id"]
        values = [row["observed"][sid] for row in observations["samples"]]
        item = {"series_id": sid, "quantity": quantity, "location_id": location, "unit": series["unit"],
                "status": "unresolved", "sample_count": len(values), "missing_count": sum(v is None for v in values),
                "rmse": None, "bias": None, "maximum_absolute_error": None,
                "expanded_uncertainty_abs": series["expanded_uncertainty_abs"]}
        if item["missing_count"]:
            report["errors"].append(f"{sid}: missing observations are retained; no sample deletion or replacement.")
        else:
            try:
                predicted = [row[quantity] if quantity == "storage_m3" else row[quantity][location] for row in prediction["timeseries"]]
                errors = [float(observed) - _number(predicted_value, "Predicted response") for observed, predicted_value in zip(values, predicted)]
                rmse, bias, maximum = math.hypot(*errors) / math.sqrt(len(errors)), math.fsum(errors) / len(errors), max(abs(x) for x in errors)
                if not all(math.isfinite(x) for x in (rmse, bias, maximum)):
                    raise ValueError("Nonfinite error arithmetic")
                item.update(status="resolved_errors", rmse=rmse, bias=bias, maximum_absolute_error=maximum)
            except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
                report["errors"].append(f"{sid}: predicted response or finite error arithmetic is unresolved.")
        report["series"].append(item)
    if not report["errors"]:
        report.update(status="resolved_errors", summary=f"Numerical errors retained for {len(report['series'])} response series; no fit or physical acceptance is inferred.")
    return report


class BenchStudyStore:
    """A local research ledger, separate from authenticated operations records."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = self.path.with_name(self.path.name + ".artifacts")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=120, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, version INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS blobs (sha256 TEXT PRIMARY KEY, content BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS events (study_id TEXT NOT NULL REFERENCES studies(id), version INTEGER NOT NULL,
            kind TEXT NOT NULL, at TEXT NOT NULL, previous_sha256 TEXT, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
            PRIMARY KEY(study_id,version));
          CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'Immutable study event'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'Immutable study event'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_blobs_update BEFORE UPDATE ON blobs BEGIN SELECT RAISE(ABORT,'Immutable study blob'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_blobs_delete BEFORE DELETE ON blobs BEGIN SELECT RAISE(ABORT,'Immutable study blob'); END;
        """)

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
            raise BenchStudyError("busy", "The local study store is busy; read its current version and retry when the active run finishes.") from exc
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _blob(self, data):
        digest = _hash(data)
        self.db.execute("INSERT OR IGNORE INTO blobs VALUES (?,?)", (digest, data))
        _require(_hash(self.db.execute("SELECT content FROM blobs WHERE sha256=?", (digest,)).fetchone()[0]) == digest, "integrity", "Stored evidence bytes failed integrity.")
        return digest

    def _append(self, study_id, kind, payload, at):
        payload = _parsed(payload)  # Bound every persisted event, not only intake files.
        last = self.db.execute("SELECT * FROM events WHERE study_id=? ORDER BY version DESC LIMIT 1", (study_id,)).fetchone()
        version, previous = (last["version"] + 1, last["sha256"]) if last else (1, None)
        _require(last is None or timestamp(at) >= timestamp(last["at"]), "clock_rollback", "Server clock moved before the previous receipt; no retrospective ledger event is permitted.")
        envelope = {"study_id": study_id, "version": version, "kind": kind, "at": at, "previous_sha256": previous, "payload": payload}
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)", (study_id, version, kind, at, previous, canonical_json(payload), content_sha256(envelope)))
        self.db.execute("UPDATE studies SET version=? WHERE id=?", (version, study_id))

    def _artifact_bytes(self, item):
        path = (self.artifact_root / item["relative_path"]).resolve()
        _require(path.is_relative_to(self.artifact_root.resolve()) and path.is_file() and path.stat().st_size <= MAX_ARTIFACT_BYTES, "artifact_integrity", "Prediction artifact is missing, outside its store, or oversized.")
        data = path.read_bytes()
        _require(len(data) == item["size"] and _hash(data) == item["sha256"], "artifact_integrity", "Prediction artifact bytes changed after internal generation.")
        return data

    def _events(self, study_id):
        _text(study_id, "Study ID", identifier=True)
        head = self.db.execute("SELECT version FROM studies WHERE id=?", (study_id,)).fetchone()
        _require(head is not None, "unknown_study", "Study does not exist.")
        rows = self.db.execute("SELECT * FROM events WHERE study_id=? ORDER BY version", (study_id,)).fetchall()
        _require(len(rows) == head["version"] and rows, "integrity", "Study event count/head mismatch.")
        previous, result, prior_time = None, [], None
        for index, row in enumerate(rows, 1):
            payload = _parsed(row["payload"])
            envelope = {"study_id": study_id, "version": index, "kind": row["kind"], "at": row["at"], "previous_sha256": previous, "payload": payload}
            _require(row["version"] == index and row["previous_sha256"] == previous and row["sha256"] == content_sha256(envelope) and row["payload"] == canonical_json(payload), "integrity", "Study event hash chain changed.")
            when = timestamp(row["at"])
            _require(when is not None and (prior_time is None or when >= prior_time), "integrity", "Study receipt chronology changed.")
            for digest in payload.get("blob_sha256s", []):
                blob = self.db.execute("SELECT content FROM blobs WHERE sha256=?", (digest,)).fetchone()
                _require(blob is not None and _hash(blob[0]) == digest, "integrity", "Stored source/evidence bytes changed.")
            for artifact in payload.get("prediction_artifacts", []):
                self._artifact_bytes(artifact)
            result.append({**dict(row), "payload": payload})
            previous, prior_time = row["sha256"], when
        return result

    def get(self, study_id):
        rows = self._events(study_id)
        state = deepcopy(rows[0]["payload"])
        state.update(version=rows[-1]["version"], head_sha256=rows[-1]["sha256"], created_at=rows[0]["at"], calibrations=[], validations=[], freeze=None)
        for row in rows[1:]:
            item = {**deepcopy(row["payload"]), "record_sha256": row["sha256"], "recorded_at": row["at"]}
            if row["kind"] == "freeze":
                state["freeze"] = item
            else:
                state["calibrations" if row["kind"] == "calibration" else "validations"].append(item)
        completed = {r["event"]["event_id"] for r in state["validations"]}
        pending = [e["event_id"] for e in state["freeze"]["validation_plan"] if e["event_id"] not in completed] if state["freeze"] else []
        state.update(pending_validation_event_ids=pending,
                     status="calibration" if state["freeze"] is None else "withheld_pending" if pending else "withheld_records_complete", **_FLAGS)
        return state

    def list_studies(self):
        return [{k: state[k] for k in ("study_id", "title", "evidence_kind", "version", "status", "created_at")}
                for state in [self.get(row[0]) for row in self.db.execute("SELECT id FROM studies ORDER BY rowid")]]

    def verify(self, study_id):
        try:
            state = self.get(study_id)
            expected = state["freeze"]["lineage"] if state["freeze"] else None
            compatible = expected == _lineage() if expected is not None else None
            return {"valid": compatible is not False, "integrity_valid": True, "current_runtime_matches_freeze": compatible,
                    "study_id": study_id, "version": state["version"], "head_sha256": state["head_sha256"],
                    "errors": [] if compatible is not False else ["Current adapter/engine/source/protocol differs from the frozen lineage."], **_FLAGS}
        except (ValueError, TypeError, OSError, sqlite3.Error) as exc:
            return {"valid": False, "integrity_valid": False, "study_id": study_id, "errors": [str(exc)], **_FLAGS}

    def _checked(self, study_id, expected_version):
        state = self.get(study_id)
        _require(type(expected_version) is int and expected_version == state["version"], "stale_version", "Study changed; read its current version before writing.")
        _require(timestamp(_now()) >= timestamp(self.db.execute("SELECT at FROM events WHERE study_id=? ORDER BY version DESC LIMIT 1", (study_id,)).fetchone()[0]), "clock_rollback", "Server receipt clock moved backwards.")
        return state

    def create_study(self, site_package, *, title):
        site, raw = _raw(site_package)
        check = validate_site_package(site)
        _require(check["valid"], "site", canonical_json(check["errors"]))
        _text(title, "Study title")
        protocol = load_protocol()
        with self._transaction():
            sid, at = "STUDY-" + uuid.uuid4().hex, _now()
            self.db.execute("INSERT INTO studies VALUES (?,0)", (sid,))
            blob = self._blob(raw)
            payload = {"schema_version": SCHEMA_VERSION, "study_id": sid, "title": title,
                       "evidence_kind": "synthetic_fixture" if site["evidence_kind"] == "synthetic_fixture" else "measured_bench",
                       "site_package": site, "site_package_sha256": check["package_sha256"], "site_blob_sha256": blob,
                       "protocol": protocol, "protocol_sha256": PROTOCOL_SHA256, "blob_sha256s": [blob],
                       "scope": "Separate dry-zero-flow research slice; not completion of the 24-event physical protocol.", **_FLAGS}
            self._append(sid, "created", payload, at)
        return self.get(sid)

    def _attachments(self, raw, raw_files):
        files = {} if raw_files is None else raw_files
        _require(isinstance(files, dict) and len(files) <= 8, "attachments", "Supply at most eight basename-to-bytes evidence attachments.")
        attachments = [{"name": "observations.json", "sha256": self._blob(raw), "size": len(raw)}]
        total = 0
        for name, data in files.items():
            _require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}", name) is not None and ".." not in name and name.lower() != "observations.json", "attachment_path", "Attachment names must be plain safe basenames; observations.json is reserved.")
            _require(isinstance(data, bytes) and 0 < len(data) <= MAX_ATTACHMENT_BYTES, "attachments", "Attachment content must be nonempty bounded bytes.")
            total += len(data)
            _require(total <= 2 * MAX_ATTACHMENT_BYTES, "attachments", "Evidence attachments exceed 16 MiB total.")
            attachments.append({"name": name, "sha256": self._blob(data), "size": len(data)})
        return attachments

    def _partition_check(self, response_sha256, partition):
        rows = self.db.execute("SELECT study_id,payload,kind FROM events WHERE kind IN ('calibration','validation')").fetchall()
        for study_id in {row["study_id"] for row in rows}:
            self._events(study_id)
        matches = []
        for row in rows:
            old = _parsed(row["payload"])
            if old["observation_response_sha256"] == response_sha256 and not row["kind"] == partition == "calibration":
                matches.append({"study_id": row["study_id"], "record_id": old["record_id"], "partition": row["kind"]})
        return matches

    def _predict(self, study, model, event, lineage):
        folder = self.artifact_root / uuid.uuid4().hex
        folder.mkdir()
        artifacts = []
        result = None
        try:
            result = _adapter().run_bench_model(study["site_package"], model, event["run"], folder)
            _require(isinstance(result, dict), "prediction", "Internal adapter returned no result object.")
            identity = result.get("engine_identity", result.get("engine"))
            _require(identity == lineage["engine_identity"] and _lineage() == lineage, "lineage", "Adapter/engine/source identity changed during prediction generation.")
            _require(result.get("site_package_sha256") == study["site_package_sha256"] and result.get("model_sha256") == content_sha256(model) and result.get("run_sha256") == content_sha256(event["run"]), "lineage", "Internal prediction is bound to a different site/model/run.")
            if result.get("valid") is True:
                verified = _adapter().verify_bench_result(result)
                _require(verified.get("valid") is True, "artifact_integrity", "Internal paired prediction verification failed: " + canonical_json(verified.get("errors", [])))
                _require(result.get("status") == "succeeded" and result.get("step_halving", {}).get("passed") is True, "numerics", "A usable prediction requires the adapter's paired numerical step check, not only one successful run.")
                times = _grid(model, event["run"])
                _require(isinstance(result.get("timeseries"), list) and len(result["timeseries"]) == len(times), "prediction_grid", "Internal prediction grid is incomplete.")
                for row in result["timeseries"]:
                    _number(row.get("elapsed_s"), "Prediction report time", minimum=0)
                _require([row.get("elapsed_s") for row in result["timeseries"]] == times, "prediction_grid", "Internal prediction grid is misaligned.")
            # Seal actual artifact bytes, including the adapter result, before joining observations.
            paths = result.get("files", {})
            _require(isinstance(paths, dict) and len(paths) <= 24, "artifact_integrity", "Internal prediction files are missing or excessive.")
            pair_root = Path(paths.get("result.json", folder / "result.json")).resolve().parent
            _require(pair_root.is_relative_to(folder.resolve()), "artifact_integrity", "Prediction pair folder is outside this private attempt.")
            for name, supplied in paths.items():
                path = Path(supplied).resolve()
                _require(isinstance(name, str) and re.fullmatch(r"(?:(?:base|half)/)?[A-Za-z][A-Za-z0-9_.-]{0,100}", name) is not None
                         and path == (pair_root / name).resolve() and path.is_relative_to(folder.resolve())
                         and path.is_file() and path.stat().st_size <= MAX_ARTIFACT_BYTES, "artifact_integrity", "Internal adapter artifact path is invalid.")
                data = path.read_bytes()
                artifacts.append({"name": name, "relative_path": path.relative_to(self.artifact_root).as_posix(), "size": len(data), "sha256": self._blob(data)})
            required_files = {"result.json", "manifest.json"} | {f"{prefix}/model.{suffix}" for prefix in ("base", "half") for suffix in ("inp", "rpt", "out")}
            _require(result.get("valid") is not True or required_files <= set(paths), "artifact_integrity", "A successful prediction requires both numerical attempts' retained native input/output/report artifacts.")
            saved = next((item for item in artifacts if item["name"] == "result.json"), None)
            _require(saved is None or _parsed(self._artifact_bytes(saved)) == result, "artifact_integrity", "Adapter result object differs from its saved result artifact.")
            manifest = next((item for item in artifacts if item["name"] == "manifest.json"), None)
            if manifest is not None:
                expected_files = {item["name"]: item["sha256"] for item in artifacts if item["name"] != "manifest.json"}
                _require(_parsed(self._artifact_bytes(manifest)).get("file_sha256") == expected_files, "artifact_integrity", "The adapter manifest does not match the prediction artifact bytes.")
            for item in artifacts:
                self._artifact_bytes(item)
        except Exception as exc:
            adapter_errors = result.get("errors", []) if isinstance(result, dict) else []
            result = {"valid": False, "status": "failed", "timeseries": [], "errors": [f"{type(exc).__name__}: {exc}"],
                      "retained_adapter_errors": adapter_errors}
            # An unsuccessful numerical or integrity attempt is still evidence.
            # Retain the current bounded local files as failed-attempt bytes;
            # none of their predictions are used in the comparison.
            artifacts = []
            for path in sorted(folder.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(folder.resolve()) and path.stat().st_size <= MAX_ARTIFACT_BYTES:
                    _require(len(artifacts) < 24, "artifact_limit", "Failed attempt exceeds the bounded artifact inventory.")
                    data = path.read_bytes()
                    artifacts.append({"name": path.relative_to(folder).as_posix(), "relative_path": path.relative_to(self.artifact_root).as_posix(),
                                      "size": len(data), "sha256": self._blob(data)})
        seal = {"schema_version": "monsoon.bench-study-prediction/1", "generated_at": _now(), "lineage": lineage,
                "site_package_sha256": study["site_package_sha256"], "model_sha256": content_sha256(model),
                "run_sha256": content_sha256(event["run"]), "result": result}
        data = (canonical_json(seal) + "\n").encode("utf-8")
        path = folder / "study-prediction.json"
        with path.open("xb") as stream:
            stream.write(data)
        item = {"name": path.name, "relative_path": path.relative_to(self.artifact_root).as_posix(), "size": len(data), "sha256": self._blob(data)}
        artifacts.append(item)
        reread = _parsed(self._artifact_bytes(item))
        return reread["result"], artifacts, item["sha256"]

    def _record(self, state, model, event, observations, raw_files, partition):
        now, lineage = _now(), _lineage()
        obs, raw, response_hash = _observations(observations, event, model, state["evidence_kind"], now)
        reuse_matches = self._partition_check(response_hash, partition)
        attachments = self._attachments(raw, raw_files)
        prediction, artifacts, seal = self._predict(state, model, event, lineage)
        comparison = (_comparison(obs, event, prediction) if not reuse_matches else
                      {"status": "unresolved", "summary": "Suspected response reuse across withheld partitions; no numeric comparison released.",
                       "errors": ["Semantic response content matches an earlier calibration/validation receipt. Identical values alone do not prove reuse; this unresolved receipt is retained and cannot qualify calibration or be silently replaced."],
                       "series": [], "acceptance_assessed": False, "physical_validation_established": False,
                       "limitations": list(_COMPARISON_LIMITS)})
        record = {"record_id": "RECORD-" + uuid.uuid4().hex, "partition": partition, "evidence_kind": state["evidence_kind"],
                  "model_spec": model, "model_sha256": content_sha256(model), "event": event, "observations": obs,
                  "received_at": now, "lineage": lineage, "prediction_origin": "internally_run_research_swmm",
                  "prediction": prediction, "prediction_artifacts": artifacts, "prediction_seal_sha256": seal,
                  "observation_response_sha256": response_hash, "suspected_reuse_matches": reuse_matches,
                  "attachments": attachments, "comparison": comparison,
                  "blob_sha256s": [i["sha256"] for i in attachments + artifacts], **_FLAGS}
        self._append(state["study_id"], partition, record, _now())
        return record

    def record_calibration(self, study_id, expected_version, *, model_spec, event, observations, raw_files=None):
        with self._transaction():
            state = self._checked(study_id, expected_version)
            _require(state["freeze"] is None and len(state["calibrations"]) < MAX_CALIBRATIONS, "calibration_closed", "Calibration is closed after freeze or after the bounded candidate limit.")
            model = _parsed(model_spec)
            parsed_event = _event(event, state["site_package"], model, state["evidence_kind"], now=_now())
            record = self._record(state, model, parsed_event, observations, raw_files, "calibration")
        return {"study": self.get(study_id), "record": record}

    def freeze_study(self, study_id, expected_version, *, selected_model_sha256, validation_plan, rationale):
        with self._transaction():
            state, now = self._checked(study_id, expected_version), _now()
            _require(state["freeze"] is None, "already_frozen", "A study can be frozen only once; start a new prospective study for changes.")
            _text(rationale, "Manual model selection rationale")
            selected = [r for r in state["calibrations"] if r["model_sha256"] == selected_model_sha256]
            _require(selected and any(r["prediction"].get("valid") is True and r["comparison"]["status"] == "resolved_errors" for r in selected), "calibration_required", "Freeze requires a model with an internally reproduced run and a complete nonempty calibration error record.")
            lineage = _lineage()
            _require(all(r["lineage"] == lineage for r in selected), "lineage_changed", "Selected calibration records do not match the current exact source/engine/protocol lineage.")
            _require(isinstance(validation_plan, list) and 1 <= len(validation_plan) <= MAX_VALIDATIONS, "validation_plan", "Predeclare 1–24 withheld assignments for this limited dry-start research slice.")
            model = selected[0]["model_spec"]
            plan = [_event(e, state["site_package"], model, state["evidence_kind"], now=now, prospective=True) for e in validation_plan]
            identifiers = [e["event_id"] for e in plan]
            calibration_ids = {r["event"]["event_id"] for r in state["calibrations"]}
            _require(len(set(identifiers)) == len(identifiers) and not set(identifiers) & calibration_ids, "partition_ids", "Validation event IDs must be distinct and cannot reuse any calibration ID.")
            if state["evidence_kind"] == "measured_bench":
                for left, right in zip(plan, plan[1:]):
                    _require(timestamp(left["window"]["end_at"]) <= timestamp(right["window"]["start_at"]), "window_order", "Validation windows must follow the predeclared non-overlapping order.")
            # Source hashing and contract checks may take time. The recorded
            # freeze instant is read after them, never backdated to entry time.
            now = _now()
            if state["evidence_kind"] == "measured_bench":
                earliest = timestamp(now) + timedelta(seconds=MINIMUM_FREEZE_LEAD_SECONDS)
                _require(all(timestamp(e["window"]["start_at"]) >= earliest for e in plan), "prospectivity", "Every measured assignment must start at least 60 seconds after the final server freeze time.")
            freeze = {"frozen_at": now, "model_spec": model, "model_sha256": selected_model_sha256,
                      "site_package_sha256": state["site_package_sha256"], "lineage": lineage,
                      "selected_calibration_record_ids": [r["record_id"] for r in selected],
                      "calibration_record_sha256s": [r["record_sha256"] for r in state["calibrations"]],
                      "selected_prediction_seal_sha256s": [r["prediction_seal_sha256"] for r in selected],
                      "validation_plan": plan, "validation_plan_sha256": content_sha256(plan), "rationale": rationale,
                      "scope": state["scope"], **_FLAGS}
            self._append(study_id, "freeze", freeze, now)
        return {"study": self.get(study_id), "freeze": freeze}

    def record_validation(self, study_id, expected_version, *, event_id, observations, raw_files=None):
        with self._transaction():
            state = self._checked(study_id, expected_version)
            frozen = state["freeze"]
            _require(frozen is not None, "freeze_required", "Freeze model and future assignments before validation receipt.")
            _require(frozen["lineage"] == _lineage(), "lineage_changed", "Current source/engine/protocol differs from the immutable freeze; validation is blocked.")
            _require(state["pending_validation_event_ids"] and event_id == state["pending_validation_event_ids"][0], "validation_order", "Record the next frozen assignment once, in order; unsuccessful runs cannot be overwritten or silently skipped.")
            event = next(e for e in frozen["validation_plan"] if e["event_id"] == event_id)
            _event(event, state["site_package"], frozen["model_spec"], state["evidence_kind"], now=_now())
            record = self._record(state, frozen["model_spec"], event, observations, raw_files, "validation")
        return {"study": self.get(study_id), "record": record}
