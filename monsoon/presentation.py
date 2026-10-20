"""Pure views of planning and audit records; never an approval validator.

Callers must obtain ``gate`` from assurance.validate_audit for the current
snapshot. These helpers perform no I/O, simulation, selection or workflow write.
They bind the displayed record to that supplied validator result, but do not
replace its raw-file, runtime or current-state checks.
"""
from copy import deepcopy
from hashlib import sha256
import json
import math


_PLAN_FIELDS = ("id", "queue", "admissible", "status", "worst_spill_m3", "mean_spill_m3",
                "worst_crew_minutes", "worst_cost_rm", "scenario_results", "reasons")


def _view(status, title, explanation, level):
    return {"status": status, "title": title, "explanation": explanation, "level": level}


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _cases(audit):
    rows = audit.get("cases") if isinstance(audit, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _gate_reasons(gate):
    reasons = gate.get("reasons") if isinstance(gate, dict) else None
    if not isinstance(reasons, list):
        return ""
    return " ".join(reason for reason in reasons if isinstance(reason, str) and reason)


def _bound_audit(plan, audit, gate):
    """Reject detached, changed or contradictory display records, not revalidate them."""
    try:
        if not isinstance(gate, dict) or gate.get("valid") is not True:
            return False
        if not isinstance(audit, dict) or not isinstance(audit.get("subject"), dict):
            return False
        if audit["subject"].get("queue") != plan["queue"]:
            return False
        subject = audit["subject"]
        if "planning_evaluation_sha256" in subject:
            if any(key not in plan for key in _PLAN_FIELDS):
                return False
            if _digest({key: plan[key] for key in _PLAN_FIELDS}) != subject["planning_evaluation_sha256"]:
                return False
        for key in ("state_version", "context_fingerprint", "model_version", "frozen_fingerprint",
                    "assurance_requirement", "decision_manifest", "observed_state"):
            if key in plan and plan[key] != subject.get(key):
                return False
        for key in ("deadline_minutes", "travel_minutes"):
            if key in plan and plan[key] != subject.get("settings", {}).get(key):
                return False
        if audit.get("audit_sha256") != _digest({k: v for k, v in audit.items() if k != "audit_sha256"}):
            return False
        if audit.get("subject_sha256") != _digest(audit["subject"]):
            return False
        if any(gate.get(key) != audit.get(key) for key in ("audit_sha256", "subject_sha256", "status")):
            return False
        cases = _cases(audit)
        if not cases or len(cases) != len(audit["cases"]):
            return False
        if any(row.get("status") not in {"passed", "failed", "unresolved"} for row in cases):
            return False
        counts = {status: sum(row["status"] == status for row in cases)
                  for status in ("passed", "failed", "unresolved")}
        status = "unresolved" if counts["unresolved"] else "failed" if counts["failed"] else "passed"
        return (audit.get("counts") == counts and audit.get("status") == status
                and audit.get("approval_allowed") is (status == "passed"))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def decision_verdict(plan, audit=None, gate=None, stale=False, condition_unknown=False):
    """Summarize this selected queue and its exact audit, without authorizing it.

    ``plan`` is a planning-result or snapshot dictionary with its actual queue.
    Unknown condition and stale context take precedence over historical passes.
    A missing validator result, offline-only pass or failed integrity check can
    never produce a success view. No statement about other queues is inferred.
    """
    if condition_unknown:
        return _view("condition_unknown", "Condition unresolved · planning blocked",
                     "Restoration is not credited. Affected asset condition is unverified; "
                     "further supported planning is blocked pending verification. Previous results are historical.", "warning")
    if stale:
        return _view("stale", "Stale record · fresh rehearsal required",
                     "Inputs or observed work changed. Rehearse and audit the current context before review or approval.", "warning")
    if not isinstance(plan, dict):
        return _view("not_rehearsed", "Not rehearsed · select a current plan",
                     "Run a rehearsal to inspect achievable work and its modelled consequences.", "info")
    queue = plan.get("queue")
    if not isinstance(queue, list) or any(not isinstance(job, str) or not job for job in queue):
        return _view("invalid_evidence", "Approval blocked · selected queue unavailable",
                     "The selected plan has no usable queue identity. Select a current rehearsal record.", "error")
    if audit is None:
        audit = plan.get("assurance")
    if audit is None:
        if plan.get("status") == "unresolved":
            return _view("unresolved", "Approval blocked · planning evidence unresolved",
                         "Required planning evidence is unresolved. Inspect the recorded reasons before a new review.", "error")
        if plan.get("status") == "inadmissible" or plan.get("admissible") is False:
            return _view("blocked", "Approval blocked · planning checks failed",
                         "This queue does not pass its selected planning checks. A lower total spill does not waive a protected-location failure.", "error")
        prefix_note = ("Selected planning scenarios and their completed-work prefixes passed. "
                       if plan.get("admissible") is True and
                       (plan.get("status") == "supported" or plan.get("supported") is True)
                       else "The selected queue has no verified plan-specific stress audit. ")
        return _view("candidate", "Planning candidate only · stress audit outstanding",
                     prefix_note + "The wider required stress and numerical audit is outstanding; review and approval remain blocked.", "warning")
    if not _bound_audit(plan, audit, gate):
        reasons = _gate_reasons(gate)
        return _view("invalid_evidence", "Approval blocked · audit verification required",
                     "The displayed audit is not verified for this exact selected queue and current snapshot. "
                     "Do not treat a saved status as approval." + (" " + reasons if reasons else ""), "error")

    cases = _cases(audit)
    failed = sum(row["status"] == "failed" for row in cases)
    unresolved = sum(row["status"] == "unresolved" for row in cases)
    if unresolved:
        resolved_harm = failed > 0 or any(
            state.get("status") == "failed" and state.get("violations")
            for case in cases for state in _records(case.get("states")))
        note = " Separately resolved protected-location spill increases are also present." if resolved_harm else ""
        return _view("unresolved", f"Approval blocked · {unresolved} required case(s) unresolved",
                     "Required hydraulic, numerical or schedule evidence remains unresolved. "
                     "Inspect each case's recorded reasons." + note, "error")
    if failed:
        return _view("blocked", f"Approval blocked · protected-location spill increase ({failed}/{len(cases)} cases)",
                     "This plan increases modelled collector spill beyond the protected-location allowance in "
                     f"{failed} required case(s). Lower total spill does not waive those increases; inspect the affected prefixes and locations.", "error")
    if gate.get("approval_allowed") is not True:
        reasons = _gate_reasons(gate)
        return _view("invalid_evidence", "Approval blocked · evidence verification incomplete",
                     "The recorded model checks passed, but the validator does not allow approval."
                     + (" " + reasons if reasons else ""), "warning")
    if not queue:
        return _view("passed_empty", "No additional discretionary work · model checks passed",
                     "This empty queue passes the required model checks; baseline flood risk remains. "
                     "Review and approval are recorded separately. No work ticket can be issued from an empty queue.", "success")
    return _view("passed", "Selected queue · required model checks passed",
                 "This exact queue passes the required model checks. Supervisor review and approval are separate; "
                 "these synthetic checks do not establish field or crew safety.", "success")


def audit_case_options(audit):
    """Copy cases in stable failed / unresolved / remaining order."""
    priority = {"failed": 0, "unresolved": 1}
    return sorted(deepcopy(_cases(audit)), key=lambda row: priority.get(row.get("status"), 2))


def _number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def _records(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _violation_records(audit, scenario_id):
    """Prefer case/state records; compact census and top-level records also work."""
    cases = [case for case in _cases(audit) if case.get("scenario_id") == scenario_id]
    records = []
    for case in cases:
        states = case.get("states")
        if isinstance(states, list) and any(isinstance(state, dict) and isinstance(state.get("violations"), list)
                                            for state in states):
            for state in _records(states):
                for violation in _records(state.get("violations")):
                    records.append((violation, state, case))
        else:
            for violation in _records(case.get("violations")):
                records.append((violation, {}, case))
    if not cases and isinstance(audit, dict):
        for violation in _records(audit.get("violations")):
            if violation.get("scenario_id") == scenario_id:
                records.append((violation, {}, {}))
    return records


def audit_location_rows(audit, scenario_id):
    """Normalize actual violations without inventing values or merging prefixes.

    Missing, boolean and nonfinite numerical values remain None. Repeated nodes
    in distinct prefixes remain distinct rows. The caller must display the
    audit's verification status; these rows are not an integrity certificate.
    """
    rows = []
    for violation, state, case in _violation_records(audit, scenario_id):
        jobs = violation.get("completed_jobs", state.get("completed_jobs"))
        job_label = (", ".join(jobs) if jobs else "No additional work") if (
            isinstance(jobs, list) and all(isinstance(job, str) for job in jobs)) else None
        rows.append({
            "Location": violation.get("node_id"),
            "Baseline spill (m³)": _number(violation.get("reference_spill_m3")),
            "Resulting spill (m³)": _number(violation.get("spill_m3")),
            "Change (m³)": _number(violation.get("increase_m3")),
            "Limit (m³)": _number(violation.get("tolerance_m3")),
            "Completed jobs": job_label,
            "Scenario": scenario_id,
            "Prefix": violation.get("prefix_index", state.get("prefix_index")),
            "Stage": violation.get("stage", state.get("stage")),
            "State status": state.get("status", case.get("status")),
            "Result run ID": violation.get("run_id", state.get("run_id")),
            "Baseline run ID": violation.get("reference_run_id", state.get("reference_run_id")),
            "Evidence key": state.get("evidence_key"),
        })
    return rows
