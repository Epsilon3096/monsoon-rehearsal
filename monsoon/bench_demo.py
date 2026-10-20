"""Explicitly synthetic calibration/freeze/withheld-record software exercise.

Response values come from this same solver plus declared offsets. This is a
circular software test, never independent hydraulic or physical validation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile

from .bench_model import run_bench_model
from .bench_study import BenchStudyStore
from .site_data import canonical_json, content_sha256

ROOT = Path(__file__).resolve().parents[1]


def exercise_inputs():
    site, model, run = [json.loads((ROOT / f"data/templates/synthetic_bench_{name}_v1.json").read_text(encoding="utf-8"))
                        for name in ("site", "model", "run")]
    events = []
    for event_id, multiplier in (("SYN-CAL-ROUNDTRIP", 1.0), ("SYN-VAL-ROUNDTRIP", 0.8)):
        event_run = deepcopy(run)
        event_run["run_id"] = event_id
        for boundary in event_run["inflows"]:
            for point in boundary["points"]:
                point["value_m3_s"] *= multiplier
        events.append({"event_id": event_id, "run": event_run, "window": None,
                       "series": [{"id": "SYN-STAGE-A", "quantity": "stage_m", "location_id": "A", "unit": "m",
                                   "expanded_uncertainty_abs": 0.002, "source_id": "SYN-BENCH-SOURCE"}]})
    return site, model, events


def synthetic_responses(site, model, event, output_dir, *, offset_m):
    prediction = run_bench_model(site, model, event["run"], output_dir)
    if not prediction.get("valid"):
        raise ValueError("Synthetic generator is numerically unresolved: " + canonical_json(prediction.get("errors", [])))
    return {"schema_version": "monsoon.bench-observations/1", "event_id": event["event_id"],
            "evidence_kind": "synthetic_fixture", "start_at": None, "end_at": None,
            "source_id": "SYN-BENCH-SOURCE", "notes": f"SOFTWARE EXERCISE ONLY: same-solver response plus {offset_m:g} m constant offset. Circular synthetic values, not physical measurements or independent validation.",
            "samples": [{"elapsed_s": row["elapsed_s"], "observed": {"SYN-STAGE-A": row["stage_m"]["A"] + offset_m}}
                        for row in prediction["timeseries"]]}


def run_exercise(output_dir):
    base = Path(output_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="synthetic-study-", dir=base))
    site, model, events = exercise_inputs()
    for name, value in (("site", site), ("model", model), ("calibration-event", events[0]),
                        ("withheld-plan", {"events": [events[1]]})):
        (folder / (name + ".json")).write_text(canonical_json(value) + "\n", encoding="utf-8")
    with BenchStudyStore(folder / "exercise.sqlite3") as store:
        state = store.create_study(site, title="SYNTHETIC software roundtrip; no physical experiment")
        calibration = synthetic_responses(site, model, events[0], folder / "synthetic_generator", offset_m=0.001)
        recorded = store.record_calibration(state["study_id"], state["version"], model_spec=model,
                                            event=events[0], observations=calibration)
        state = recorded["study"]
        frozen = store.freeze_study(state["study_id"], state["version"], selected_model_sha256=content_sha256(model),
                                    validation_plan=[events[1]], rationale="Software-only exercise: preserve a model and a different pulse before generating the later synthetic response. No fit or physical acceptance claim.")
        state = frozen["study"]
        withheld = synthetic_responses(site, model, events[1], folder / "synthetic_generator", offset_m=0.01)
        final = store.record_validation(state["study_id"], state["version"], event_id=events[1]["event_id"], observations=withheld)
        state = final["study"]
        check = store.verify(state["study_id"])
    for name, value in (("calibration-observations", calibration), ("withheld-observations", withheld), ("study", state)):
        (folder / (name + ".json")).write_text(canonical_json(value) + "\n", encoding="utf-8")
    comparisons = [(recorded["record"]["comparison"], 0.001), (final["record"]["comparison"], 0.01)]
    arithmetic = all(report["status"] == "resolved_errors" and len(report["series"]) == 1 and
                     all(math.isclose(report["series"][0][metric], expected, rel_tol=0, abs_tol=1e-10)
                         for metric in ("rmse", "bias", "maximum_absolute_error"))
                     for report, expected in comparisons)
    result = {"kind": "synthetic_software_roundtrip", "physical_validation_established": False,
              "independent_hydraulic_validation": False, "operational_activation_allowed": False,
              "limitation": "Responses are generated from the same solver plus declared offsets. This only tests software lineage and error arithmetic.",
              "status": "passed" if check.get("valid") and arithmetic and not state["pending_validation_event_ids"] else "failed",
              "declared_error_arithmetic_verified": arithmetic,
              "study_id": state["study_id"], "folder": str(folder), "integrity_check": check,
              "calibration_comparison": recorded["record"]["comparison"], "withheld_comparison": final["record"]["comparison"],
              "declared_offsets_m": {"calibration": 0.001, "withheld": 0.01}, "study_file": str(folder / "study.json")}
    (folder / "exercise-result.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    result = run_exercise(parser.parse_args().output)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)
