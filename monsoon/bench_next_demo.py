"""Explicitly circular software exercise for separate boundary/response receipts."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import tempfile

from .bench_replay import BenchReplayStore
from .service import ROOT
from .site_data import canonical_json, content_sha256


def replay_inputs():
    """Read invented fixtures, never substitute them in the supplied-data forms."""
    folder = ROOT / "data/templates"
    names = {
        "site": "synthetic_bench_replay_site_v1.json", "model": "synthetic_bench_replay_model_v1.json",
        "recipe": "synthetic_bench_replay_recipe_v1.json",
        "calibration_event": "synthetic_bench_replay_calibration_event_v1.json",
        "calibration_boundaries": "synthetic_bench_replay_calibration_boundaries_v1.json",
        "validation_event": "synthetic_bench_replay_validation_event_v1.json",
        "validation_boundaries": "synthetic_bench_replay_validation_boundaries_v1.json",
    }
    return {key: json.loads((folder / name).read_text(encoding="utf-8")) for key, name in names.items()}


def circular_responses(record, boundaries, *, multiplier):
    """Known offsets from the already sealed prediction; NOT independent evidence."""
    prediction, recipe = record["prediction"], record["recipe"]
    if not prediction.get("valid") or not record.get("prediction_qualified") or not record.get("prediction_seal_sha256"):
        raise ValueError("The software generator requires a numerically supported sealed prediction.")
    offsets = {"m": 0.001 * multiplier, "m3/s": 1e-7 * multiplier, "m3": 1e-6 * multiplier}
    samples = []
    for row in prediction["timeseries"]:
        observed = {}
        for series in recipe["response_series"]:
            quantity, location = series["quantity"], series["location_id"]
            value = row[quantity] if quantity == "storage_m3" else row[quantity][location]
            observed[series["id"]] = value + offsets[series["unit"]]
        samples.append({"elapsed_s": row["elapsed_s"], "observed": observed})
    return {"schema_version": "monsoon.bench-replay-responses/1", "event_id": record["event"]["event_id"],
            "evidence_kind": "synthetic_fixture", "start_at": None, "end_at": None,
            "clock": deepcopy(boundaries["clock"]), "vertical_datum": deepcopy(recipe["vertical_datum"]),
            "source_id": "SYN-BENCH-SOURCE",
            "notes": "CIRCULAR SOFTWARE EXERCISE ONLY. Same sealed solver output plus declared offsets: " + canonical_json(offsets) + ". No apparatus, physical readings or independent validation.",
            "series": deepcopy(recipe["response_series"]), "samples": samples}


def _write(path, value):
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def run_replay_exercise(output_dir):
    parent = Path(output_dir).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="synthetic-boundary-study-", dir=parent))
    inputs = replay_inputs()
    for name, value in inputs.items():
        _write(folder / (name + ".json"), value)
    database = folder / "exercise.sqlite3"
    with BenchReplayStore(database) as store:
        state = store.create_study(inputs["site"], title="SYNTHETIC boundary replay software exercise")
        cal = store.record_calibration_boundaries(state["study_id"], state["version"], model_spec=inputs["model"],
                                                  recipe=inputs["recipe"], event=inputs["calibration_event"],
                                                  boundaries=inputs["calibration_boundaries"])
        state, receipt = cal["study"], cal["record"]
        cal_responses = circular_responses(receipt, inputs["calibration_boundaries"], multiplier=1)
        calibrated = store.record_responses(state["study_id"], state["version"], receipt_id=receipt["receipt_id"], responses=cal_responses)
        state = calibrated["study"]
        frozen = store.freeze_study(state["study_id"], state["version"], selected_model_sha256=content_sha256(inputs["model"]),
                                    selected_recipe_sha256=content_sha256(inputs["recipe"]),
                                    validation_plan=[inputs["validation_event"]],
                                    rationale="Software exercise: freeze the model and recipe before the later boundary receipt and generated response; no parameter fitting or physical acceptance.")
        state = frozen["study"]
        val = store.record_validation_boundaries(state["study_id"], state["version"],
                                                 event_id=inputs["validation_event"]["event_id"], boundaries=inputs["validation_boundaries"])
        state, receipt = val["study"], val["record"]
        val_responses = circular_responses(receipt, inputs["validation_boundaries"], multiplier=10)
        validated = store.record_responses(state["study_id"], state["version"], receipt_id=receipt["receipt_id"], responses=val_responses)
        state = validated["study"]
        integrity = store.verify(state["study_id"])
        evidence = store.export_evidence(state["study_id"])
    for name, value in (("calibration_responses", cal_responses), ("validation_responses", val_responses), ("study", state)):
        _write(folder / (name + ".json"), value)
    (folder / "synthetic-replay-evidence.zip").write_bytes(evidence)
    rows, arithmetic = [], True
    for partition, multiplier in (("calibrations", 1), ("validations", 10)):
        for record in state[partition]:
            report = record["comparison"]
            arithmetic &= report["status"] == "resolved_errors" and len(report["series"]) == len(inputs["recipe"]["response_series"])
            for series in report["series"]:
                expected = {"m": 0.001, "m3/s": 1e-7, "m3": 1e-6}[series["unit"]] * multiplier
                arithmetic &= all(math.isclose(series[metric], expected, rel_tol=0, abs_tol=1e-12)
                                  for metric in ("rmse", "bias", "maximum_absolute_error"))
                rows.append({"Partition": "Calibration" if partition == "calibrations" else "Withheld",
                             "Response": series["series_id"], "Unit": series["unit"],
                             "Declared offset": expected, "Calculated RMSE": series["rmse"], "Status": series["status"]})
    result = {"kind": "synthetic_boundary_replay_software_exercise",
              "status": "passed" if integrity.get("valid") and arithmetic and state["status"] == "withheld_records_complete" else "failed",
              "limitation": "Circular same-solver responses with known offsets test sequence, lineage and arithmetic only. Boundary values are invented. No physical validation or independent hydraulic accuracy is established.",
              "physical_validation_established": False, "independent_hydraulic_validation": False,
              "operational_activation_allowed": False, "declared_error_arithmetic_verified": bool(arithmetic),
              "study_id": state["study_id"], "folder": str(folder), "database": str(database),
              "study_file": str(folder / "study.json"), "result_file": str(folder / "exercise-result.json"),
              "evidence_zip": str(folder / "synthetic-replay-evidence.zip"),
              "summary_rows": rows, "integrity_check": integrity,
              "file_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted([*folder.glob("*.json"), folder / "synthetic-replay-evidence.zip"])}}
    _write(folder / "exercise-result.json", result)
    return result


def verify_replay_exercise(result, output_dir):
    errors = []
    try:
        parent, folder = Path(output_dir).resolve(), Path(result["folder"]).resolve()
        if not folder.is_relative_to(parent) or folder == parent:
            raise ValueError("The exercise is outside this research workspace.")
        if Path(result["result_file"]).resolve() != folder / "exercise-result.json":
            raise ValueError("Exercise result path changed.")
        if (Path(result["study_file"]).resolve() != folder / "study.json" or
                Path(result["evidence_zip"]).resolve() != folder / "synthetic-replay-evidence.zip"):
            raise ValueError("Exercise export paths changed.")
        if json.loads((folder / "exercise-result.json").read_text(encoding="utf-8")) != result:
            raise ValueError("Stored exercise result changed.")
        for name, expected in result["file_sha256"].items():
            path = (folder / name).resolve()
            if path.parent != folder or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Exercise evidence is missing or changed: " + name)
        database = Path(result["database"]).resolve()
        if database != folder / "exercise.sqlite3" or not database.is_file():
            raise ValueError("The exercise ledger is missing or changed.")
        with BenchReplayStore(database) as store:
            checked = store.verify(result["study_id"])
            if not checked.get("valid"):
                raise ValueError("The exercise ledger failed verification: " + canonical_json(checked.get("errors", [])))
            if store.get(result["study_id"]) != json.loads((folder / "study.json").read_text(encoding="utf-8")):
                raise ValueError("The exercise export differs from its verified ledger.")
        if any(result[key] is not False for key in ("physical_validation_established", "independent_hydraulic_validation", "operational_activation_allowed")):
            raise ValueError("The software exercise cannot establish physical or operational claims.")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = run_replay_exercise(parser.parse_args().output)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)
