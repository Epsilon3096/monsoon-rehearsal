"""Prepare unfilled bench run sheets; never certify readiness or invent readings.

The existing physical protocol is read and verified, never changed. Missing
participants/evidence still produce a useful draft. Only documentary declarations
are inspected; facility permission, engineering approval and physical validation
must not be inferred from this checklist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .measurements import PROTOCOL_SHA256, load_protocol
from .site_data import _Checks, content_sha256, parse_json

VERSION = "monsoon.bench-preparation/1"
ROLES = ("build_lead", "facility_custodian", "scientific_reviewer", "data_custodian")
CHECKS = {
    "facility_setup_authority": ("facility_custodian", "Document the permitted bench location, water/electrical setup and disposal arrangements."),
    "apparatus_section_match": ("build_lead", "Record actual channel/pipe section and its matching hydraulic representation."),
    "asset_survey_and_datum": ("scientific_reviewer", "Retain as-built geometry, datum, fixed outlet and before/after insert records."),
    "control_volume_inventory": ("scientific_reviewer", "Account for all retained water, inflows, signed receiving exchange and separate spill collectors."),
    "leak_and_loss_bound": ("build_lead", "Document leak checks and a measured or justified upper loss bound."),
    "flow_calibration_and_control": ("scientific_reviewer", "Document branch-flow and signed-boundary calibrations plus stable prescribed forcing."),
    "stage_storage_calibration": ("scientific_reviewer", "Document stage datum/calibration and complete retained-volume calibration."),
    "clock_sampling_and_coverage": ("data_custodian", "Document synchronisation, uncertainty, sample interval and complete sensor coverage."),
    "calibration_partition_and_model_freeze": ("scientific_reviewer", "Keep calibration events separate and freeze the model before validation collection."),
    "paired_reset_and_forcing_sheet": ("scientific_reviewer", "Freeze paired forcing, reset recipe, intervention subset, windows and this run order."),
    "retention_and_stopping_rules": ("data_custodian", "Retain raw data and failures; document instrument, overflow and apparatus stop rules."),
    "protocol_review_before_collection": ("scientific_reviewer", "Review the unchanged protocol before collection; register a new version first if changes are needed."),
}


def blank_bench_readiness() -> dict:
    protocol = load_protocol()
    return {"schema_version": VERSION, "preparation_id": "BENCH-PREP-DRAFT", "mode": "prospective_unfilled",
            "protocol_id": protocol["protocol_id"], "protocol_sha256": PROTOCOL_SHA256,
            "prepared_at": None, "site_package_sha256": None, "model_freeze_sha256": None,
            "roles": {role: None for role in ROLES},
            "checklist": {key: {"status": "missing", "evidence_reference": None, "notes": ""} for key in CHECKS},
            "notes": "Unfilled preparation draft. No participant, permission, dimension or observation is asserted."}


def validate_bench_readiness(payload: dict | str | bytes) -> dict:
    c = _Checks()
    report = {"schema_version": VERSION, "valid": False, "status": "invalid_preparation", "payload_sha256": None,
              "protocol_sha256": PROTOCOL_SHA256, "documentary_requirements_complete": False,
              "physical_validation_established": False, "engineering_approval_established": False,
              "facility_permission_established": False, "operational_activation_allowed": False,
              "errors": [], "warnings": [], "missing_items": []}
    try:
        p = parse_json(payload)
        protocol = load_protocol()
        report["payload_sha256"] = content_sha256(p)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        report["errors"] = [{"path": "$", "code": "invalid_json_or_protocol", "message": str(exc)}]
        return report
    c.obj(p, "$", {"schema_version", "preparation_id", "mode", "protocol_id", "protocol_sha256", "prepared_at", "site_package_sha256", "model_freeze_sha256", "roles", "checklist", "notes"})
    c.choice(p.get("schema_version"), {VERSION}, "$.schema_version")
    c.ident(p.get("preparation_id"), "$.preparation_id")
    c.choice(p.get("mode"), {"prospective_unfilled"}, "$.mode")
    if p.get("protocol_id") != protocol["protocol_id"] or p.get("protocol_sha256") != PROTOCOL_SHA256:
        c.error("$.protocol_sha256", "protocol_mismatch", "Preparation must bind the unchanged frozen bench protocol.")
    if not isinstance(p.get("notes"), str):
        c.error("$.notes", "text_required", "Notes must be text; observation arrays or result objects are not accepted.")
    if p.get("prepared_at") is None:
        report["missing_items"].append("prepared_at")
    else:
        c.when(p.get("prepared_at"), "$.prepared_at")
    for field in ("site_package_sha256", "model_freeze_sha256"):
        if p.get(field) is None:
            report["missing_items"].append(field)
        else:
            c.sha(p.get(field), f"$.{field}")
    roles = c.obj(p.get("roles"), "$.roles", set(ROLES))
    for role in ROLES:
        if roles.get(role) is None:
            report["missing_items"].append(f"roles.{role}")
        else:
            c.text(roles.get(role), f"$.roles.{role}")
    checklist = c.obj(p.get("checklist"), "$.checklist", set(CHECKS))
    rows = []
    for key, (role, description) in CHECKS.items():
        path = f"$.checklist.{key}"
        item = c.obj(checklist.get(key), path, {"status", "evidence_reference", "notes"})
        c.choice(item.get("status"), {"missing", "draft", "documented"}, f"{path}.status")
        if not isinstance(item.get("notes"), str):
            c.error(f"{path}.notes", "text_required", "Checklist notes must be text.")
        reference = item.get("evidence_reference")
        if reference is not None:
            reference = c.obj(reference, f"{path}.evidence_reference", {"uri", "sha256", "description"})
            c.text(reference.get("uri"), f"{path}.evidence_reference.uri")
            c.sha(reference.get("sha256"), f"{path}.evidence_reference.sha256")
            c.text(reference.get("description"), f"{path}.evidence_reference.description")
        if item.get("status") == "documented" and reference is None:
            c.error(path, "document_reference_required", "A documented declaration needs a retained evidence reference and hash.")
        if item.get("status") != "documented":
            report["missing_items"].append(f"checklist.{key}")
        rows.append({"item": key, "responsible_role": role, "description": description,
                     "declared_status": item.get("status"), "evidence_verified": False})
    c.warn("$", "documentary_only", "Checklist statuses and hashes are supplied declarations; this tool verifies neither evidence bytes nor authority, calibration, readiness or physical validation.")
    c.warn("$", "draft_can_proceed", "Missing people or evidence do not prevent draft preparation. Actual laboratory use follows the facility's procedures and responsible review.")
    c.warn("$", "no_observations", "Use this tool before collection for unfilled planning only. Measurements belong in the separate measurement importer.")
    complete = not c.errors and not report["missing_items"]
    report.update(valid=not c.errors, status="documented_claims_pending_review" if complete else "draft_missing_evidence" if not c.errors else "invalid_preparation",
                  documentary_requirements_complete=complete, errors=c.errors, warnings=c.warnings, checklist=rows)
    return report


def _run_sheets(payload, protocol):
    ids = protocol["event_plan"]["validation_ids"]
    if len(ids) != 4 * len(protocol["mechanisms"]) or len(set(ids)) != len(ids):
        raise ValueError("Frozen protocol event layout is incompatible with this preparation tool.")
    sheets = []
    for block_index, mechanism in enumerate(protocol["mechanisms"]):
        block = ids[4 * block_index:4 * block_index + 4]
        # Keep pair 01/02 current-first, pair 03/04 restored-first. This order is
        # fixed before outcomes, not selected from favorable observed responses.
        for index in (0, 1, 3, 2):
            eid = block[index]
            sheets.append({"event_id": eid, "partition": "validation", "mechanism": mechanism,
                           "state": "current" if index % 2 == 0 else "restored", "paired_event_id": block[index ^ 1],
                           "run_order": len(sheets) + 1, "block_order": block_index + 1, "pair_in_block": index // 2 + 1,
                           "sheet_status": "unfilled_prospective", "independent_reset_required": True,
                           "site_package_sha256": payload["site_package_sha256"], "model_freeze_sha256": payload["model_freeze_sha256"],
                           "plan_before_collection": {"forcing_sha256": None, "configuration_evidence_sha256": None,
                               "reset_recipe_reference": None, "intended_window_seconds": None,
                               "completed_job_ids": [] if index % 2 == 0 else None,
                               "initialisation": "observed_cold_start" if mechanism == "cold_start" else "observed_equilibrated" if mechanism == "equilibrated_control" else None,
                               "instrument_inventory_reference": None, "witness": None},
                           "record_after_event": {"reset_checked_at": None, "start_at": None, "end_at": None,
                               "actual_configuration_reference": None, "raw_data_sha256": None,
                               "instrument_exceptions": None, "stopping_event": None, "record_custodian": None},
                           "readings": [], "predictions": [], "physical_validation_established": False})
    return sheets


def _printable_sheets(pack, sheets=None):
    lines = ["# Unfilled prospective bench run sheets", "", f"Preparation identity: `{pack['pack_sha256']}`.",
             f"Protocol: `{pack['protocol_sha256']}`. Fixed order: current/restored, then restored/current in each mechanism block.",
             "", "All dimensions, initial values, forcing references, witnesses, timestamps and readings require actual records. No measurement or approval is asserted.", ""]
    for sheet in pack["run_sheets"] if sheets is None else sheets:
        lines += [f"## Run {sheet['run_order']}: {sheet['event_id']}", "",
                  f"Mechanism: {sheet['mechanism']} | State: {sheet['state']} | Pair: {sheet['paired_event_id']}", "",
                  "Before collection: site/model identity __________; installed insert/job IDs __________; forcing/window reference __________; reset recipe __________; instruments/calibration __________; witness __________.", "",
                  "After event: reset check/time __________; start/end with timezone __________; raw-file hash __________; actual configuration __________; exceptions/stopping reason __________; custodian __________.", "",
                  "| Actual timestamp with timezone | Sensor ID and unit | Observed value | Locked-model predicted value | Quality/exception |", "|---|---|---|---|---|",
                  "| | | | | |", "| | | | | |", "", "Use the full unedited instrument record; this space is not a substitute for required samples or total-water accounting.", ""]
    return "\n".join(lines)


def prepare_bench_pack(payload: dict | str | bytes | None = None, output_dir: str | Path | None = None) -> dict:
    """Generate a deterministic blank plan; optional output never overwrites."""
    try:
        snapshot = blank_bench_readiness() if payload is None else parse_json(payload)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return validate_bench_readiness(payload)
    report = validate_bench_readiness(snapshot)
    if not report["valid"]:
        return report
    protocol = load_protocol()
    pack = {"schema_version": VERSION, "kind": "unfilled_prospective_bench_pack", "preparation_id": snapshot["preparation_id"],
            "payload_sha256": report["payload_sha256"], "protocol_id": protocol["protocol_id"],
            "protocol_version": protocol["protocol_version"], "protocol_sha256": PROTOCOL_SHA256,
            "readiness_declarations": snapshot, "readiness_report": report, "run_sheets": _run_sheets(snapshot, protocol),
            "order_rule": "Protocol mechanism blocks in listed order; within each block 01,02,04,03. Pair 01/02 current-first; pair 03/04 restored-first. Freeze before collection; no outcome-based reshuffling.",
            "interpretation": "Counterbalanced ordering reduces a simple order imbalance; two pairs do not establish population inference, statistical independence, physical validity or engineering permission.",
            "physical_validation_established": False, "engineering_approval_established": False, "operational_activation_allowed": False}
    pack["pack_sha256"] = content_sha256(pack)
    json_files = {"readiness.json": snapshot, "readiness-checks.json": report, "bench-pack.json": pack,
                  "frozen-bench-protocol-copy.json": protocol}
    files = {name: json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n" for name, value in json_files.items()}
    files["README.md"] = "\n".join(["# Prospective bench preparation pack", "", "All run sheets are unfilled. No participant, permission, dimension, measurement, prediction or physical validation is asserted.", "", f"Pack identity: `{pack['pack_sha256']}`.", f"Protocol identity: `{PROTOCOL_SHA256}`.", "", "Complete documentary references in readiness.json, retain their real source bytes, and generate a new pack when the declarations change. The checklist is not independent verification or laboratory permission.", "", "The fixed run order is 01,02,04,03 in each listed mechanism block. Retain exact event IDs/pairs and reset independently. Freeze forcing, geometry, clock, windows and model lineage before collecting validation. Do not reorder after observing results.", "", "bench-pack.json contains the full plan and blank fields. unfilled-run-sheets.md combines all sheets; run-sheets/ contains one printable Markdown sheet per event. Measurements belong in the separate measurement importer after actual collection.", "", "manifest.json hashes every other packaged file's UTF-8 bytes. See the project's BENCH_BUILD.md and PHYSICAL_VALIDATION.md for apparatus, commissioning, calibration and evidence limits.", ""])
    files["unfilled-run-sheets.md"] = _printable_sheets(pack)
    for sheet in pack["run_sheets"]:
        files[f"run-sheets/{sheet['run_order']:02}-{sheet['event_id']}.md"] = _printable_sheets(pack, [sheet])
    hashes = {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in files.items()}
    manifest = {"pack_sha256": pack["pack_sha256"], "payload_sha256": report["payload_sha256"], "protocol_sha256": PROTOCOL_SHA256, "files": hashes}
    files["manifest.json"] = json.dumps(manifest, indent=2, allow_nan=False) + "\n"
    result = {**report, "pack_sha256": pack["pack_sha256"], "pack": pack, "files": files}
    if output_dir is not None:
        destination = Path(output_dir).resolve() / ("bench-preparation-" + pack["pack_sha256"])
        destination.mkdir(parents=True, exist_ok=False)
        for name, value in files.items():
            raw = value.encode("utf-8")
            (destination / name).parent.mkdir(parents=True, exist_ok=True)
            with (destination / name).open("xb") as stream:
                stream.write(raw)
        result["saved_directory"] = str(destination)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional documentary readiness JSON; omission creates an unfilled draft.")
    parser.add_argument("--output", type=Path, help="Optional parent folder for a new hash-addressed pack; existing packs are never overwritten.")
    args = parser.parse_args()
    result = prepare_bench_pack(args.input.read_bytes() if args.input else None, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    raise SystemExit(0 if result["valid"] else 2)
