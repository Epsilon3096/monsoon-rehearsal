"""Plan-specific, fail-closed development evidence for a frozen priority queue.

This is deliberately not another planner. Scheduling and protected-location
gates are delegated to planning._Evaluator/replay; no queue is ranked or changed
after stress outcomes become available. Checksums provide local integrity, not
authentication or a claim of independent scientific validation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Callable

from . import planning
from .case import load_case
from .hydraulics import engine_info

VERSION = "0.2.0"
SCHEMA_VERSION = 1
PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "data" / "assurance_protocol.json"
_LOADED_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()
_RAW_FIELDS = ("run_id", "status", "valid", "engine_version", "total_spill_m3",
               "nodes", "diagnostics", "files", "errors")
_PLAN_FIELDS = ("id", "queue", "admissible", "status", "worst_spill_m3", "mean_spill_m3",
                "worst_crew_minutes", "worst_cost_rm", "scenario_results", "reasons")
_NUMERIC_CONFIGS = (("default", .5, 180), ("half step", .25, 180),
                    ("extended horizon", .5, 360))


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, name):
    return planning._number(value, name)


def _planning_evaluation(value):
    """The complete raw scientific plan, excluding later workflow metadata."""
    _require(isinstance(value, dict) and all(key in value for key in _PLAN_FIELDS),
             "The complete evaluated planning result is required for assurance.")
    return {key: deepcopy(value[key]) for key in _PLAN_FIELDS}


def load_protocol(case=None) -> dict:
    """Read the pre-evaluation development protocol and check its content seal."""
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    _validate_protocol(protocol, case)
    return protocol


def _validate_protocol(protocol, case=None):
    _require(isinstance(protocol, dict), "Assurance protocol must be an object.")
    payload = {key: value for key, value in protocol.items() if key != "protocol_sha256"}
    _require(protocol.get("protocol_sha256") == _hash(payload), "Assurance protocol seal does not match its contents.")
    _require(protocol.get("schema_version") == SCHEMA_VERSION, "Unsupported assurance protocol schema.")
    _require(protocol.get("evidence_class") == "development_only_not_independent_validation",
             "This implementation accepts only explicitly labelled development evidence.")
    entries = protocol.get("scenarios")
    _require(isinstance(entries, list) and entries, "Required stress scenarios are missing.")
    ids = []
    for entry in entries:
        scenario = entry["scenario"]
        _require(scenario.get("phase") == "development_stress", "Stress scenarios must be labelled development_stress.")
        _require(isinstance(scenario.get("id"), str) and scenario["id"], "Stress scenarios require identifiers.")
        _require(isinstance(entry.get("rationale"), str) and entry["rationale"], "Each stress requires a prespecified rationale.")
        ids.append(scenario["id"])
    _require(len(ids) == len(set(ids)), "Duplicate required stress identifiers.")
    numeric = protocol["numerical_settings"]
    for key, value in {"routing_step_s": .5, "half_step_s": .25, "horizon_minutes": 180,
                       "extended_horizon_minutes": 360, "node_spill_convergence_absolute_m3": .05,
                       "node_spill_convergence_relative": .02, "horizon_extra_spill_tolerance_m3": .05}.items():
        _require(numeric.get(key) == value, f"Unsupported numerical protocol: {key}.")
    _require(numeric.get("engine_validity_required") is True and
             numeric.get("protected_decision_must_agree_at_both_steps") is True,
             "Engine validity and step-stable protected-location decisions are mandatory.")
    if case is not None:
        _require(case.get("case_sha256") == protocol.get("source_case_sha256"), "Protocol belongs to a different frozen case.")
        _require(case.get("model_version") == protocol.get("source_model_version"), "Protocol belongs to a different model version.")


def assurance_requirement(protocol=None) -> dict:
    protocol = load_protocol() if protocol is None else deepcopy(protocol)
    _validate_protocol(protocol)
    return {"schema_version": SCHEMA_VERSION, "protocol_id": protocol["id"],
            "protocol_sha256": protocol["protocol_sha256"]}


def _runtime_identity(hydraulic_identity=None):
    _require(sha256(Path(planning.__file__).read_bytes()).hexdigest() == planning._planner_source_fingerprint(),
             "Planner source changed in this process; restart before auditing.")
    _require(sha256(Path(__file__).read_bytes()).hexdigest() == _LOADED_SOURCE_SHA256,
             "Assurance source changed in this process; restart before auditing.")
    numeric_path = Path(__file__).with_name("assurance_hydraulics.py")
    return {"assurance_version": VERSION, "assurance_source_sha256": _LOADED_SOURCE_SHA256,
            "planner_version": planning.VERSION,
            "planner_source_sha256": planning._planner_source_fingerprint(),
            "numerical_adapter_sha256": sha256(numeric_path.read_bytes()).hexdigest(),
            "hydraulic": deepcopy(engine_info() if hydraulic_identity is None else hydraulic_identity)}


def _settings_from_inputs(inputs, snapshot):
    return {"deadline_minutes": _number(snapshot["deadline_minutes"], "deadline"),
            "travel_minutes": _number(snapshot["travel_minutes"], "travel time"),
            "already_completed": sorted(inputs["already_completed"]),
            "start_minute": _number(inputs["start_minute"], "observed time"),
            "start_location": inputs["start_location"]}


def snapshot_subject(snapshot, *, protocol=None, hydraulic_identity=None) -> dict:
    """Canonical queue/input identity before or after TicketStore stamps a plan.

    Required additions to the existing service snapshot are decision_manifest,
    frozen_fingerprint and assurance_requirement. TicketStore's observed_state
    and context_inputs must agree exactly with the original provenance; before
    saving, those two fields are derived from provenance instead.
    """
    protocol = load_protocol() if protocol is None else deepcopy(protocol)
    _validate_protocol(protocol)
    _require(isinstance(snapshot, dict), "Plan snapshot must be an object.")
    required = assurance_requirement(protocol)
    _require(snapshot.get("assurance_requirement") == required, "Missing, stale or mismatched assurance requirement.")
    inputs = deepcopy(snapshot["provenance"])
    _require(isinstance(inputs, dict), "Decision provenance is missing.")
    _require(_hash(snapshot.get("context_inputs", inputs)) == _hash(inputs), "Stamped context inputs differ from decision provenance.")
    if "assurance_requirement" in inputs:
        _require(inputs["assurance_requirement"] == required, "Context requires a different assurance protocol.")
    _require(snapshot.get("context_fingerprint") == _hash(inputs), "Decision input fingerprint is stale or altered.")
    case = inputs["case"]
    _require(case.get("case_sha256") == protocol["source_case_sha256"], "Decision case does not match the frozen stress protocol.")
    _require(case.get("model_version") == protocol["source_model_version"], "Decision model differs from the protocol model.")
    _require(_hash(snapshot["jobs"]) == _hash(case["jobs"]), "Snapshot jobs differ from its decision model.")
    _require(snapshot.get("model_version") == case["model_version"], "Snapshot model version differs from its decision model.")
    queue = snapshot["queue"]
    _require(isinstance(queue, list) and all(isinstance(job, str) for job in queue) and
             len(queue) == len(set(queue)), "Audit queue must contain unique job IDs.")
    settings = _settings_from_inputs(inputs, snapshot)
    _require(settings["deadline_minutes"] == _number(inputs["deadline_minutes"], "decision deadline"), "Snapshot deadline differs from decision input.")
    _require(settings["travel_minutes"] == _number(case.get("travel_minutes", 10), "model travel"), "Snapshot travel differs from its model.")
    observed = {"completed_jobs": settings["already_completed"], "elapsed_minutes": settings["start_minute"],
                "crew_location": settings["start_location"]}
    if "observed_state" in snapshot:
        stamped = snapshot["observed_state"]
        _require(sorted(stamped["completed_jobs"]) == observed["completed_jobs"] and
                 _number(stamped["elapsed_minutes"], "stamped observed time") == observed["elapsed_minutes"] and
                 stamped["crew_location"] == observed["crew_location"], "Observed work state differs from the audited starting state.")
    _require(not set(queue) & set(observed["completed_jobs"]), "Audit queue contains already verified jobs.")
    planning.replay(queue, case["jobs"], **settings)  # Use the common domain validator.
    manifest = deepcopy(snapshot["decision_manifest"])
    _require(manifest.get("case_fingerprint") == planning._fingerprint(planning._case_snapshot(case)),
             "Planning manifest belongs to a different model or job definition.")
    _require(manifest.get("planner_source_sha256") == planning._planner_source_fingerprint(), "Planning manifest belongs to a stale planner.")
    _require(_hash(manifest["settings"]) == _hash(settings), "Planning settings differ from the audited plan settings.")
    _require(_hash(manifest["planning_scenarios"]) == _hash(inputs["scenarios"]), "Planning scenarios differ from the decision inputs.")
    _require(manifest.get("protected_nodes") == case.get("protected_nodes", []) and
             manifest.get("epsilon_m3") == case.get("epsilon_m3", .05), "Protected-node contract differs from the model.")
    _require(all(s.get("phase") == "planning" for s in inputs["scenarios"]) and inputs["scenarios"], "Decision scenarios must be planning-only.")
    ids = [scenario["id"] for scenario in inputs["scenarios"]]
    _require(len(ids) == len(set(ids)), "Repeated planning scenario IDs.")
    _require(not set(ids) & {entry["scenario"]["id"] for entry in protocol["scenarios"]}, "Planning and stress identifiers overlap.")
    identity = _runtime_identity(hydraulic_identity)
    _require(_hash(inputs["engine"]) == _hash(identity["hydraulic"]), "Hydraulic engine or adapter changed since planning.")
    fingerprint = snapshot.get("frozen_fingerprint")
    _require(isinstance(fingerprint, str) and len(fingerprint) == 64, "Frozen planning fingerprint is missing.")
    version = snapshot.get("state_version")
    _require(isinstance(version, int) and not isinstance(version, bool) and version >= 0, "Observed-state version is missing.")
    return {"queue": deepcopy(queue), "case": deepcopy(case), "model_version": case["model_version"],
            "planning_evaluation_sha256": _hash(_planning_evaluation(snapshot)),
            "jobs_sha256": _hash(snapshot["jobs"]), "settings": settings, "observed_state": observed,
            "state_version": version, "context_fingerprint": snapshot["context_fingerprint"],
            "context_inputs_sha256": _hash(inputs), "decision_manifest": manifest,
            "frozen_fingerprint": fingerprint, "assurance_requirement": required,
            "implementation": identity}


def subject_hash(snapshot, *, protocol=None, hydraulic_identity=None) -> str:
    return _hash(snapshot_subject(snapshot, protocol=protocol, hydraulic_identity=hydraulic_identity))


def _snapshot_for_audit(case, episode, plan, protocol, hydraulic_identity):
    manifest = episode["decision_manifest"]
    _require(manifest["case_fingerprint"] == planning._fingerprint(planning._case_snapshot(case)),
             "Case changed after the planning episode was frozen.")
    expected = planning._fingerprint({"manifest": manifest, "policies": episode["policies"],
                                      "marginal_policy_table": episode["marginal_policy_table"],
                                      "baseline_definitions": episode["baseline_definitions"]})
    _require(expected == episode["frozen_fingerprint"], "Frozen decision episode was modified.")
    candidates = list(episode.get("plans", [])) + list(episode.get("baseline_plans", {}).values())
    matches = [candidate for candidate in candidates if candidate.get("queue") == plan.get("queue") and
               candidate.get("admissible") is True and candidate.get("status") == "supported"]
    _require(matches, "Select a planning-admissible frozen queue before auditing it.")
    _require(any(_hash(_planning_evaluation(candidate)) == _hash(_planning_evaluation(plan)) for candidate in matches),
             "Selected planning scores or scenario results differ from the frozen candidate.")
    _require(plan.get("admissible") is True and plan.get("status") == "supported", "Selected planning result is not supported and admissible.")
    settings = manifest["settings"]
    inputs = deepcopy(episode.get("inputs"))
    if inputs is None:
        inputs = {"case": planning._case_snapshot(case), "scenarios": manifest["planning_scenarios"],
                  "deadline_minutes": settings["deadline_minutes"], "already_completed": settings["already_completed"],
                  "start_minute": settings["start_minute"], "start_location": settings["start_location"],
                  "engine": deepcopy(engine_info() if hydraulic_identity is None else hydraulic_identity)}
    return {**_planning_evaluation(plan), "jobs": deepcopy(case["jobs"]),
            "deadline_minutes": settings["deadline_minutes"], "travel_minutes": settings["travel_minutes"],
            "model_version": case["model_version"], "provenance": inputs,
            "context_fingerprint": episode.get("context_fingerprint", _hash(inputs)),
            "state_version": episode.get("state_version", 0), "decision_manifest": deepcopy(manifest),
            "frozen_fingerprint": episode["frozen_fingerprint"],
            "assurance_requirement": assurance_requirement(protocol)}


def _raw_provenance(run, state, scenario, configuration, subject, *, verify_files=True):
    """Pin raw artefacts and verify they describe the requested physical run."""
    errors = []
    proof = {"run_id": run.get("run_id"), "configuration": configuration[0],
             "files": deepcopy(run.get("files", {})), "file_sha256": {}}
    try:
        files = run["files"]
        required_files = {"input": "model.inp", "report": "model.rpt", "output": "model.out",
                          "manifest": "manifest.json", "result": "result.json", "log": "worker.log"}
        _require(isinstance(files, dict) and all(isinstance(files.get(key), str) for key in required_files),
                 "Raw hydraulic evidence files are missing.")
        folder = Path(files["manifest"]).resolve().parent
        _require(all(Path(files[key]).resolve() == folder / filename for key, filename in required_files.items()),
                 "Raw hydraulic evidence paths do not form one immutable run folder.")
        manifest_bytes = Path(files["manifest"]).read_bytes()
        manifest = json.loads(manifest_bytes)
        saved_bytes = Path(files["result"]).read_bytes()
        saved = json.loads(saved_bytes)
        _require(manifest["run_id"] == run["run_id"] == saved["run_id"], "Raw run identities disagree.")
        _require(sorted(manifest["completed_jobs"]) == sorted(state), "Raw run describes a different restored state.")
        _require(_hash(manifest["hydraulic"]) == _hash(scenario["hydraulic"]), "Raw run describes a different hydraulic forcing.")
        _require(_hash(planning._case_snapshot(manifest["case"])) == _hash(subject["case"]), "Raw run describes a different hydraulic model.")
        _require(_hash(manifest["engine"]) == _hash(subject["implementation"]["hydraulic"]), "Raw run describes a different engine or adapter.")
        _require(manifest["routing_step"] == configuration[1] and manifest["horizon_minutes"] == configuration[2],
                 "Raw numerical configuration differs from the frozen protocol.")
        for key in ("run_id", "status", "valid", "engine_version", "nodes", "total_spill_m3", "diagnostics"):
            _require(_hash(run.get(key)) == _hash(saved.get(key)), f"Returned {key} differs from the saved raw result.")
        _require(_hash(saved) == manifest.get("result_sha256"), "Saved hydraulic result checksum does not match its manifest.")
        request = manifest["request_fingerprint"]
        _require(_hash(request) == run["run_id"], "Hydraulic request hash does not match the run identity.")
        _require(_hash(request["engine"]) == _hash(manifest["engine"]), "Request and run engine identities differ.")
        _require(request["case_snapshot_sha256"] == _hash(manifest["case"]), "Raw case identity does not match its request.")
        _require(request["adapter_sha256"] == subject["implementation"]["hydraulic"]["adapter_sha256"], "Raw adapter source identity is stale.")
        checksums = manifest["file_sha256"]
        _require({"model.inp", "model.rpt", "model.out", "request.json", "worker.log"} <= set(checksums),
                 "Raw run manifest is missing required artefact checksums.")
        _require(all(Path(name).name == name for name in checksums), "Raw evidence contains an invalid relative filename.")
        if verify_files:
            _require(all(sha256((folder / name).read_bytes()).hexdigest() == digest for name, digest in checksums.items()),
                     "Raw hydraulic artefact checksum changed or a file is missing.")
        _require(request["input_sha256"] == checksums["model.inp"], "Hydraulic input checksum differs from its request.")
        proof.update(manifest_sha256=sha256(manifest_bytes).hexdigest(), result_file_sha256=sha256(saved_bytes).hexdigest(),
                     result_sha256=manifest["result_sha256"], request_fingerprint=deepcopy(request),
                     file_sha256=deepcopy(checksums))
    except (KeyError, ValueError, TypeError, OSError, AttributeError) as exc:
        errors.append(f"{configuration[0]} raw provenance unresolved: {exc}")
    return proof, errors


def _prepare_hydraulic(raw, state, scenario, subject, *, verify_files=True):
    errors = []
    if not isinstance(raw, dict):
        raw = {"valid": False, "status": "invalid", "errors": ["Hydraulic callback returned no result object."]}
    try:
        # A failed numerical result must still be exportable as strict JSON.
        # Never turn NaN/Infinity into a zero spill or an apparently valid score.
        json.dumps(raw, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raw = {"valid": False, "status": "invalid",
               "run_id": raw.get("run_id") if isinstance(raw.get("run_id"), str) else None,
               "errors": [f"Nonfinite or non-JSON hydraulic evidence is unresolved: {exc}"]}
    clean = {key: deepcopy(raw.get(key)) for key in _RAW_FIELDS}
    raw_errors = clean.get("errors")
    if raw_errors is not None and not isinstance(raw_errors, list):
        errors.append("Hydraulic errors must be a list of messages.")
        raw_errors = [str(raw_errors)]
    clean["errors"] = [str(error) for error in (raw_errors or [])]
    numeric = raw.get("assurance_numerics")
    clean["assurance_numerics"] = deepcopy(numeric) if isinstance(numeric, dict) else {}
    proofs = []
    evaluator = planning._Evaluator(subject["case"], None, subject["settings"])
    base = evaluator._compact_hydraulic(clean)
    if not base["valid"]:
        errors.extend(base["errors"])
    try:
        _require(isinstance(numeric, dict), "Step-halving and horizon evidence is missing.")
        if not (numeric.get("valid") is True and numeric.get("status") == "passed" and
                numeric.get("all_engine_runs_valid") is True):
            errors.append("Required numerical evidence did not pass.")
        errors.extend(numeric.get("errors") or [])
        for key, value in (("routing_step_s", .5), ("half_step_s", .25), ("horizon_minutes", 180), ("extended_horizon_minutes", 360)):
            _require(numeric.get(key) == value, f"Numerical attestation differs from the frozen {key}.")
        runs = numeric["runs"]
        _require(isinstance(runs, list) and len(runs) == 3, "All three raw numerical runs are required.")
        compact = []
        for run, configuration in zip(runs, _NUMERIC_CONFIGS):
            _require(run.get("configuration") == configuration[0], "Numerical runs are missing or out of order.")
            value = evaluator._compact_hydraulic(run)
            if not value["valid"]:
                errors.extend(value["errors"])
            proof, provenance_errors = _raw_provenance(run, state, scenario, configuration, subject, verify_files=verify_files)
            proofs.append(proof)
            errors.extend(provenance_errors)
            compact.append(value)
        _require([run["run_id"] for run in runs] == [numeric["default_run_id"], numeric["half_step_run_id"], numeric["extended_run_id"]],
                 "Numerical run IDs differ from the attestation.")
        _require(_hash(compact[0]) == _hash(base), "The numerical default run differs from the scored hydraulic result.")
        _require(_hash(numeric["half_step_nodes"]) == _hash(runs[1]["nodes"]) and
                 numeric["half_step_total_spill_m3"] == runs[1]["total_spill_m3"], "Half-step metrics differ from the raw result.")
        if all(item["valid"] for item in compact):
            for node in evaluator.required_nodes:
                a, b, c = [run["nodes"][node]["spill_m3"] for run in compact]
                tolerance = max(.05, .02 * max(abs(a), abs(b)))
                if abs(a - b) > tolerance:
                    errors.append(f"{node}: spill fails the prespecified step-halving convergence tolerance.")
                if abs(c - a) > .05:
                    errors.append(f"{node}: spill changes beyond 0.05 m3 at the extended horizon.")
            a, b, c = [run["total_spill_m3"] for run in compact]
            if abs(a - b) > max(.05, .02 * max(abs(a), abs(b))):
                errors.append("Total spill fails step-halving convergence.")
            if abs(c - a) > .05:
                errors.append("Total spill changes beyond 0.05 m3 at the extended horizon.")
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        errors.append(f"Numerical evidence unresolved: {exc}")
    entry = {"scenario_id": scenario["id"], "scenario_sha256": _hash(scenario), "completed_jobs": sorted(state),
             "raw": clean, "raw_provenance": proofs, "errors": sorted(set(str(error) for error in errors))}
    gate_run = deepcopy(clean)
    if errors:
        gate_run.update(valid=False, status="failed", errors=entry["errors"])
    return entry, gate_run


def _evidence_key(state, scenario):
    return _hash({"completed_jobs": sorted(state), "scenario": scenario})


def _protocol_summary(protocol):
    return {"id": protocol["id"], "sha256": protocol["protocol_sha256"], "label": protocol["label"],
            "evidence_class": protocol["evidence_class"], "frozen_utc": protocol["frozen_utc"],
            "scenario_ids": [entry["scenario"]["id"] for entry in protocol["scenarios"]],
            "numerical_settings": deepcopy(protocol["numerical_settings"]),
            "limitations": deepcopy(protocol["limitations"])}


def _reports(subject, protocol, callback, entries):
    evaluator = planning._Evaluator(subject["case"], callback, subject["settings"])
    scenarios = [{"scenario": scenario, "kind": "selected_planning_case", "rationale": "Recheck the selected frozen queue under its original planning input."}
                 for scenario in subject["decision_manifest"]["planning_scenarios"]] + protocol["scenarios"]
    cases = []
    for item in scenarios:
        scenario = item["scenario"]
        result = evaluator.scenario_result(subject["queue"], scenario)
        reference_result = evaluator.scenario_result([], scenario)
        initial = set(subject["settings"]["already_completed"])
        reference = evaluator.hydraulic(initial, scenario)
        baseline_entry = entries[_evidence_key(initial, scenario)]
        replay = result["replay"]
        prefixes = []
        prefix = set(initial)
        for identifier in replay["completed_jobs"]:
            prefix.add(identifier)
            prefixes.append(set(prefix))
        if not prefixes:
            prefixes = [set(initial)]
        reasons = list(result["reasons"]) + list(reference_result["reasons"])
        states = []
        unresolved = result["status"] == "unresolved" or reference_result["status"] == "unresolved"
        for index, state in enumerate(prefixes, start=1):
            run = evaluator.hydraulic(state, scenario)
            entry = entries[_evidence_key(state, scenario)]
            stage = "final" if index == len(prefixes) and replay["status"] == "supported" else "prefix"
            comparisons, violations = [], []
            errors = list(entry["errors"]) + list(baseline_entry["errors"])
            if run["valid"] and reference["valid"]:
                raw_half = entry["raw"]["assurance_numerics"]["runs"][1]
                ref_half = baseline_entry["raw"]["assurance_numerics"]["runs"][1]
                half = evaluator._compact_hydraulic(raw_half)
                half_reference = evaluator._compact_hydraulic(ref_half)
                default_violations = evaluator.violations(run, reference, state, scenario["id"])
                half_violations = evaluator.violations(half, half_reference, state, scenario["id"])
                default_nodes = {row["node_id"] for row in default_violations}
                half_nodes = {row["node_id"] for row in half_violations}
                if default_nodes != half_nodes:
                    errors.append("Protected-location pass/fail changes under step halving; the decision is numerically unresolved.")
                for node in evaluator.protected:
                    increase = run["nodes"][node]["spill_m3"] - reference["nodes"][node]["spill_m3"]
                    half_increase = half["nodes"][node]["spill_m3"] - half_reference["nodes"][node]["spill_m3"]
                    comparisons.append({"node_id": node, "reference_spill_m3": reference["nodes"][node]["spill_m3"],
                                        "spill_m3": run["nodes"][node]["spill_m3"], "increase_m3": increase,
                                        "tolerance_m3": evaluator.epsilon, "excess_over_tolerance_m3": increase - evaluator.epsilon,
                                        "passes": node not in default_nodes, "half_step_increase_m3": half_increase,
                                        "half_step_passes": node not in half_nodes, "gate_stable": (node in default_nodes) == (node in half_nodes)})
                violations = [{**row, "prefix_index": index, "stage": stage,
                               "run_id": run["run_id"], "reference_run_id": reference["run_id"],
                               "excess_over_tolerance_m3": row["increase_m3"] - row["tolerance_m3"]}
                              for row in default_violations]
            else:
                errors.extend(run["errors"] + reference["errors"])
            state_status = "unresolved" if errors or not (run["valid"] and reference["valid"]) else "failed" if violations else "passed"
            unresolved = unresolved or state_status == "unresolved"
            reasons.extend(errors)
            states.append({"prefix_index": index, "stage": stage, "completed_jobs": sorted(state),
                           "status": state_status, "run_id": run["run_id"], "reference_run_id": reference["run_id"],
                           "total_spill_m3": run["total_spill_m3"], "node_comparisons": comparisons,
                           "violations": violations, "reasons": sorted(set(errors)),
                           "evidence_key": _evidence_key(state, scenario)})
        violations = [violation for state in states for violation in state["violations"]]
        status = "unresolved" if unresolved else "failed" if violations else "passed"
        cases.append({"scenario_id": scenario["id"], "title": scenario.get("title", scenario["id"]),
                      "kind": item["kind"], "rationale": item["rationale"], "scenario_sha256": _hash(scenario),
                      "status": status, "replay": deepcopy(replay), "completed_jobs": result["completed_jobs"],
                      "baseline": {"run_id": reference["run_id"], "total_spill_m3": reference["total_spill_m3"],
                                   "nodes": reference["nodes"], "evidence_key": _evidence_key(initial, scenario)},
                      "run_id": result["run_id"], "total_spill_m3": result["total_spill_m3"],
                      "states": states, "violations": violations, "reasons": sorted(set(reasons))})
    return cases


def _summary(cases):
    counts = {status: sum(case["status"] == status for case in cases) for status in ("passed", "failed", "unresolved")}
    status = "unresolved" if counts["unresolved"] else "failed" if counts["failed"] else "passed"
    violations = [violation for case in cases for violation in case["violations"]]
    return status, counts, violations


def audit_plan(case, episode, plan, hydraulic_fn: Callable, *, protocol=None,
               hydraulic_identity=None) -> dict:
    """Audit one already selected queue without optimisation or oracle access.

    The callback has the usual (completed_jobs, scenario) signature and must
    return the real default hydraulic run plus assurance_numerics as produced by
    assurance_hydraulics.checked_state. Missing evidence remains unresolved.
    Invalid selection/provenance raises ValueError before hydraulic work begins.
    """
    case, episode, plan = deepcopy(case), deepcopy(episode), deepcopy(plan)
    protocol = load_protocol(case) if protocol is None else deepcopy(protocol)
    _validate_protocol(protocol, case)
    snapshot = _snapshot_for_audit(case, episode, plan, protocol, hydraulic_identity)
    subject = snapshot_subject(snapshot, protocol=protocol, hydraulic_identity=hydraulic_identity)
    selected_at = datetime.now(timezone.utc).isoformat()
    # The queue/input seal is created before the first callback can reveal a stress.
    selection = {"subject_sha256": _hash(subject), "selected_utc": selected_at,
                 "queue": deepcopy(subject["queue"]), "protocol_sha256": protocol["protocol_sha256"]}
    entries = {}

    def collect(state, scenario):
        try:
            raw = hydraulic_fn(tuple(state), deepcopy(scenario))
        except Exception as exc:
            raw = {"valid": False, "status": "failed", "run_id": None,
                   "errors": [f"Hydraulic evaluation failed: {type(exc).__name__}: {exc}"]}
        entry, gate = _prepare_hydraulic(raw, state, scenario, subject)
        entries[_evidence_key(state, scenario)] = entry
        return gate

    cases = _reports(subject, protocol, collect, entries)
    status, counts, violations = _summary(cases)
    audit = {"schema_version": SCHEMA_VERSION, "status": status, "approval_allowed": status == "passed",
             "created_utc": datetime.now(timezone.utc).isoformat(), "protocol": _protocol_summary(protocol),
             "subject": subject, "subject_sha256": _hash(subject), "selection_freeze": selection,
             "cases": cases, "counts": counts, "violations": violations,
             "hydraulic_evidence": entries,
             "limitations": deepcopy(protocol["limitations"]),
             "selection_statement": "A single planning-admissible priority queue was fixed before these callbacks. No ranking, oracle, alternative selection or queue repair used stress outcomes."}
    audit["audit_sha256"] = _hash(audit)
    return audit


def validate_audit(snapshot, *, protocol=None, hydraulic_identity=None, verify_files=True) -> dict:
    """Fail-closed workflow gate; malformed/stale/missing evidence never throws.

    Rebuilds the scientific report with the same planner from saved raw metrics,
    checks raw artefact identities/checksums, and compares the entire rebuilt
    report. A passed string alone is never sufficient. Optional verify_files=False
    is for an explicitly labelled offline inspection; it cannot authorise work.
    """
    result = {"required": True, "valid": False, "approval_allowed": False,
              "status": "invalid", "reasons": [], "scope": "frozen finite development envelope"}
    if isinstance(snapshot, dict) and "assurance_requirement" not in snapshot and "assurance" not in snapshot:
        return {**result, "required": False, "status": "legacy_not_required", "reasons": ["Legacy snapshot has no development assurance requirement."]}
    try:
        protocol = load_protocol() if protocol is None else deepcopy(protocol)
        subject = snapshot_subject(snapshot, protocol=protocol, hydraulic_identity=hydraulic_identity)
        audit = snapshot.get("assurance")
        _require(isinstance(audit, dict), "Required plan-specific assurance evidence is missing.")
        _require(audit.get("schema_version") == SCHEMA_VERSION, "Unsupported assurance evidence schema.")
        _require(audit.get("audit_sha256") == _hash({key: value for key, value in audit.items() if key != "audit_sha256"}),
                 "Assurance evidence checksum changed.")
        _require(audit.get("subject_sha256") == _hash(subject) and _hash(audit.get("subject")) == _hash(subject),
                 "Assurance evidence belongs to a different queue, model, protocol, input or observed state.")
        _require(audit.get("protocol") == _protocol_summary(protocol), "Assurance protocol metadata is stale or altered.")
        selection = audit["selection_freeze"]
        _require(selection["subject_sha256"] == _hash(subject) and selection["queue"] == subject["queue"] and
                 selection["protocol_sha256"] == protocol["protocol_sha256"], "Selected queue was not sealed against this audit subject.")
        stored = audit["hydraulic_evidence"]
        _require(isinstance(stored, dict), "Hydraulic evidence index is missing.")
        rebuilt_entries = {}

        def replay_evidence(state, scenario):
            key = _evidence_key(state, scenario)
            record = stored.get(key)
            raw = record.get("raw") if isinstance(record, dict) else None
            entry, gate = _prepare_hydraulic(raw, state, scenario, subject, verify_files=verify_files)
            rebuilt_entries[key] = entry
            return gate

        rebuilt_cases = _reports(subject, protocol, replay_evidence, rebuilt_entries)
        _require(_hash(rebuilt_entries) == _hash(stored), "Required hydraulic evidence is missing, changed or no longer verifiable.")
        _require(_hash(rebuilt_cases) == _hash(audit["cases"]), "Scenario or reachable-prefix results are incomplete or inconsistent with the raw evidence.")
        status, counts, violations = _summary(rebuilt_cases)
        _require(audit.get("status") == status and audit.get("counts") == counts and
                 audit.get("violations") == violations and audit.get("approval_allowed") is (status == "passed"),
                 "Assurance conclusion differs from its scenario evidence.")
        result.update(valid=True, status=status,
                      approval_allowed=status == "passed" and verify_files,
                      audit_sha256=audit["audit_sha256"], subject_sha256=audit["subject_sha256"])
        if status != "passed":
            result["reasons"] = [f"Development assurance is {status}: {counts['failed']} failed and {counts['unresolved']} unresolved required cases. Approval for this envelope is blocked."]
        if not verify_files:
            result["reasons"].append("Offline inspection did not verify every raw file checksum and cannot approve work.")
    except Exception as exc:
        result["reasons"] = [f"Assurance evidence is invalid or stale: {type(exc).__name__}: {exc}"]
    return result
