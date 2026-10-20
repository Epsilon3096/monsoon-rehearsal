"""Read-only interruption audits of an unchanged replay and explicit observations.

No selector, hydraulic simulation, ticket or operational approval is invoked.
Replay end times are predictions/simulation results, never observations. An
interrupted physical job is neither unchanged nor restored without evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re


SCHEMA_VERSION = "monsoon.work-window/1"
MAX_EVENTS = 2000
MAX_JSON_BYTES = 2 * 1024 * 1024
_JOB_TYPES = {"departure_observed", "work_started", "completion_reported", "work_interrupted", "condition_verified"}
_RETURN_TYPES = {"return_started", "returned"}
_UNRESOLVED = {"work_unfinished_or_unreported", "work_interrupted_unverified", "completion_reported_unverified",
               "condition_unresolved", "intermediate_condition_unsupported", "no_evidence"}


class WorkWindowError(ValueError):
    """The audit input is malformed or inconsistent with the stated scope."""


def _json(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            raise WorkWindowError("The audit input exceeds the 2 MiB limit.")
        return encoded
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError) as exc:
        raise WorkWindowError("Audit inputs must be bounded finite JSON data.") from exc


def _sha(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _number(value, label, *, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkWindowError(f"{label} must be a finite non-negative number of minutes" + (" or null." if nullable else "."))
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise WorkWindowError(f"{label} is outside the supported numeric range.") from exc
    if not math.isfinite(number) or number < 0:
        raise WorkWindowError(f"{label} must be finite and non-negative.")
    return number


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise WorkWindowError(f"{label} must be non-empty text of at most 8000 characters.")
    return value


def _keys(value, required, optional=(), *, label):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise WorkWindowError(f"{label} must contain exactly its documented required/optional fields.")


def _reference(value, label):
    _keys(value, {"id", "sha256", "source"}, label=label)
    _text(value["id"], f"{label}.id")
    _text(value["source"], f"{label}.source")
    if not isinstance(value["sha256"], str) or re.fullmatch(r"[a-f0-9]{64}", value["sha256"]) is None:
        raise WorkWindowError(f"{label}.sha256 must be a lowercase SHA-256 digest.")
    return deepcopy(value)


def _ids(value, label):
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise WorkWindowError(f"{label} must be a bounded list of job IDs.")
    identifiers = [_text(item, label) for item in value]
    if len(set(identifiers)) != len(identifiers):
        raise WorkWindowError(f"{label} cannot contain duplicates.")
    return identifiers


def _same(left, right):
    # Arithmetic consistency only. Cutoff classifications below deliberately
    # use exact <=/< boundaries without this floating-point tolerance.
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9)


def _replay(raw):
    _json(raw)
    if not isinstance(raw, dict):
        raise WorkWindowError("replay_result must be the existing planning.replay result object.")
    required = {"status", "completed_jobs", "events", "finish_minute", "work_finish_minute", "crew_minutes",
                "skipped", "reasons", "start_minute", "start_location", "final_location", "last_work_location",
                "deadline_minutes", "return_minutes"}
    _keys(raw, required, label="replay_result")
    result = deepcopy(raw)
    if result["status"] not in {"supported", "unsupported"}:
        raise WorkWindowError("Unknown replay status.")
    for key in ("start_minute", "finish_minute", "work_finish_minute", "crew_minutes", "deadline_minutes", "return_minutes"):
        result[key] = _number(result[key], f"replay.{key}")
    start, work_end, finish = (result[key] for key in ("start_minute", "work_finish_minute", "finish_minute"))
    if not start <= work_end <= finish or not _same(result["crew_minutes"], finish - start) or not _same(result["return_minutes"], finish - work_end):
        raise WorkWindowError("Replay work/return/crew endpoints are inconsistent.")
    for key in ("start_location", "last_work_location"):
        _text(result[key], f"replay.{key}")
    if result["final_location"] != "DEPOT":
        raise WorkWindowError("The supported replay contract has a planned final return to DEPOT.")
    if not isinstance(result["reasons"], list) or any(not isinstance(x, str) for x in result["reasons"]):
        raise WorkWindowError("Replay reasons must be a list of strings.")
    if not isinstance(result["events"], list) or len(result["events"]) > MAX_EVENTS:
        raise WorkWindowError("Replay events must be a bounded list.")
    previous_end, previous_location = start, result["start_location"]
    if result["last_work_location"] == "DEPOT" and result["return_minutes"] != 0:
        raise WorkWindowError("A replay already at DEPOT cannot have a nonzero return leg.")
    uniform_travel = result["return_minutes"] if result["last_work_location"] != "DEPOT" else None
    seen, supported = [], []
    for index, event in enumerate(result["events"]):
        event_required = {"job_id", "depart_minute", "start_minute", "finish_minute", "actual_minutes", "max_minutes",
                          "from_location", "to_location", "bound_finish_minute", "supported"}
        _keys(event, event_required, label="Replay event (missing endpoints cannot be inferred)")
        job = _text(event["job_id"], "Replay job ID")
        if job in seen:
            raise WorkWindowError("Replay jobs cannot repeat.")
        seen.append(job)
        for key in ("depart_minute", "start_minute", "finish_minute", "actual_minutes", "max_minutes", "bound_finish_minute"):
            event[key] = _number(event[key], f"Replay {job}.{key}")
        depart, arrival, end = (event[key] for key in ("depart_minute", "start_minute", "finish_minute"))
        if (not depart <= arrival < end or not _same(depart, previous_end)
            or not _same(event["actual_minutes"], end - arrival) or event["max_minutes"] <= 0
            or not _same(event["bound_finish_minute"], arrival + event["max_minutes"])
            or event["from_location"] != previous_location or event["to_location"] != job
            or not isinstance(event["supported"], bool)):
            raise WorkWindowError(f"Replay event {job} has inconsistent chronology, duration or locations.")
        within_bound = event["actual_minutes"] <= event["max_minutes"] + 1e-9
        if event["supported"] != within_bound or (not within_bound and index != len(result["events"]) - 1):
            raise WorkWindowError("Replay support flags or continuation after an overrun are inconsistent.")
        travel = arrival - depart
        if event["from_location"] == job:
            if not _same(travel, 0):
                raise WorkWindowError("Same-location travel must be zero in the supplied replay contract.")
        elif uniform_travel is None:
            uniform_travel = travel
        elif not _same(travel, uniform_travel):
            raise WorkWindowError("Replay travel legs disagree with its uniform travel/return allowance.")
        if within_bound:
            supported.append(job)
        previous_end, previous_location = end, job
    if not _same(previous_end, work_end) or previous_location != result["last_work_location"]:
        raise WorkWindowError("Replay final work endpoint disagrees with its events.")
    for event in result["events"]:
        return_allowance = (uniform_travel or 0) if event["job_id"] != "DEPOT" else 0
        if event["bound_finish_minute"] + return_allowance > result["deadline_minutes"] + 1e-9:
            raise WorkWindowError("A dispatched replay job could not pass the original bound-plus-return deadline gate.")
    if _ids(result["completed_jobs"], "Replay completed_jobs") != supported:
        raise WorkWindowError("Replay completed_jobs disagree with the bounded simulated events.")
    if result["status"] == "supported" and (len(supported) != len(seen) or finish > result["deadline_minutes"] + 1e-9):
        raise WorkWindowError("A supported replay cannot contain an unsupported duration or missed deadline.")
    if not isinstance(result["skipped"], list) or len(result["skipped"]) > MAX_EVENTS:
        raise WorkWindowError("Replay skipped jobs must be a bounded list.")
    for skip in result["skipped"]:
        _keys(skip, {"job_id", "reason"}, {"missing_prerequisites"}, label="Replay skipped job")
        identifier = _text(skip.get("job_id"), "Skipped job ID")
        _text(skip.get("reason"), "Skipped job reason")
        if "missing_prerequisites" in skip:
            _ids(skip["missing_prerequisites"], "Skipped job missing_prerequisites")
        if identifier in seen:
            raise WorkWindowError("Replay contains duplicate event/skipped job IDs.")
        seen.append(identifier)
    return result, seen


def _base(mode):
    return {"schema_version": SCHEMA_VERSION, "mode": mode, "valid": False, "status": "invalid",
            "summary": "The interruption audit could not interpret the supplied evidence.",
            "errors": [], "warnings": [], "replay_sha256": None, "stop_minute": None,
            "planned_deadline_minute": None, "jobs": [], "decision_known_restored_jobs": [],
            "decision_known_baseline_jobs": [], "unresolved_jobs": [], "recovery": {}, "storm_timing": None,
            "stop_rule_breach": False, "observation_events": [], "coverage_declaration": None,
            "work_authorisation_granted": False, "hydraulic_replay_allowed": False,
            "queue_reselected": False, "future_cutoff_used_for_job_selection": False,
            "coverage_independently_verified": False, "evidence_references_independently_verified": False,
            "unfinished_job_assumed_unchanged": False, "unfinished_job_assumed_restored": False,
            "limits": ["Read-only documentary/timeline audit; no scheduling, hydraulic computation or field authority.",
                       "A started interrupted job may leave debris, partial excavation or changed flow paths; neither baseline nor restored condition is automatic.",
                       "Evidence references and coverage declarations are supplied claims, not independent authentication or proof that unlogged work did not occur.",
                       "A documented condition still requires a reviewed model, initial/boundary states and appropriate hydraulic/operational assurance."]}


def _storm(value, cutoff, as_of=None):
    if value is None:
        return {"status": "unknown", "earliest_minute": None, "latest_minute": None,
                "available_at_cutoff": None, "used_as_deadline": False, "used_as_stop": False}
    _keys(value, {"earliest_minute", "latest_minute", "issued_minute", "available_minute", "source"}, label="storm_timing")
    result = deepcopy(value)
    for key in ("earliest_minute", "latest_minute"):
        result[key] = _number(result[key], f"storm_timing.{key}", nullable=True)
    issued = _number(result["issued_minute"], "storm_timing.issued_minute")
    available = _number(result["available_minute"], "storm_timing.available_minute")
    _text(result["source"], "storm_timing.source")
    if issued > available or (as_of is not None and available > as_of):
        raise WorkWindowError("Storm timing issue/availability times are inconsistent with the audit.")
    if result["earliest_minute"] is not None and result["latest_minute"] is not None and result["earliest_minute"] > result["latest_minute"]:
        raise WorkWindowError("Storm timing range is reversed.")
    return {**result, "status": "declared_uncertain_range", "available_at_cutoff": available <= cutoff,
            "used_as_deadline": False, "used_as_stop": False, "probability_assigned": False}


def _row(job_id, event=None):
    return {"job_id": job_id, "state": "no_evidence",
            "planned_depart_minute": event["depart_minute"] if event else None,
            "planned_start_minute": event["start_minute"] if event else None,
            "planned_finish_minute": event["finish_minute"] if event else None,
            "observed_start_minute": None, "completion_reported_minute": None,
            "verification_minute": None, "verification_available_minute": None}


def audit_replay_window(replay_result, stop_minute, *, storm_timing=None):
    """Cut an existing replay at a hypothetical stop, without crediting observations.

    A planned start exactly at the cut has not begun in this projection. A finish
    exactly at the cut is a replay completion boundary, not verified restoration.
    """
    report = _base("hypothetical_replay")
    try:
        _json(storm_timing)
        replay, identifiers = _replay(replay_result)
        cutoff = _number(stop_minute, "stop_minute")
        report.update(replay_sha256=_sha(replay_result), stop_minute=cutoff,
                      planned_deadline_minute=replay["deadline_minutes"],
                      storm_timing=_storm(storm_timing, cutoff), original_replay_status=replay["status"],
                      original_replay_reasons=replay["reasons"], replay_job_order=[e["job_id"] for e in replay["events"]])
        by_id = {event["job_id"]: event for event in replay["events"]}
        interrupted, travelling, projected_finished = [], [], []
        for identifier in identifiers:
            event = by_id.get(identifier)
            row = _row(identifier, event)
            if event is None:
                state = "not_scheduled_in_replay"
            elif cutoff <= event["depart_minute"]:
                state = "not_departed_at_cutoff"
            elif cutoff < event["start_minute"]:
                state = "travelling_at_cutoff"
                travelling.append(identifier)
            elif cutoff == event["start_minute"]:
                state = "planned_start_boundary_not_started"
            elif cutoff < event["finish_minute"]:
                state = "work_interrupted_in_projection"
                interrupted.append(identifier)
            elif cutoff == event["finish_minute"]:
                state = "replay_finish_boundary_unverified"
                projected_finished.append(identifier)
            else:
                state = "replay_finished_unverified"
                projected_finished.append(identifier)
            row.update(state=state, observed_start_minute=None, observed_restoration_credit=False)
            report["jobs"].append(row)
        work_end, finish = replay["work_finish_minute"], replay["finish_minute"]
        if replay["return_minutes"] == 0:
            return_phase = "no_return_duration_in_replay"
        elif cutoff < work_end:
            return_phase = "return_not_yet_reached_in_replay"
        elif cutoff == work_end:
            return_phase = "planned_return_start_boundary"
        elif cutoff < finish:
            return_phase = "planned_return_in_progress"
        elif cutoff == finish:
            return_phase = "planned_depot_arrival_boundary"
        else:
            return_phase = "planned_return_finished"
        report.update(valid=True,
                      status="hypothetical_interruption_exposure" if interrupted else "hypothetical_travel_exposure" if travelling or return_phase == "planned_return_in_progress" else "hypothetical_timeline_only",
                      projected_finished_jobs=projected_finished, unresolved_jobs=list(interrupted),
                      return_phase=return_phase, stop_before_replay_start=cutoff < replay["start_minute"],
                      stop_after_planned_deadline=cutoff > replay["deadline_minutes"],
                      recovery={"status": "not_observed", "interrupted_jobs": interrupted,
                                "original_return_allowance_minutes": replay["return_minutes"],
                                "restoration_minutes": None, "inspection_minutes": None, "return_minutes": None,
                                "budgeted_finish_minute": None, "fits_planned_deadline": None,
                                "return_confirmed": False, "recovery_or_return_may_be_required": bool(interrupted or travelling or cutoff < finish),
                                "recovery_plan_approved": False})
        report["summary"] = (f"Hypothetical stop at minute {cutoff:g}: {len(interrupted)} job(s) lie inside their replay work interval; "
                             f"{len(projected_finished)} job(s) reach a replay finish boundary. No observed restoration or return is established.")
        report["warnings"].append("Replay finish/completed_jobs fields remain simulated timing, even if the caller supplied realised-duration scenarios.")
        if replay["status"] != "supported":
            report["warnings"].append("The original replay is unsupported; this cut does not repair its duration or deadline failure.")
    except (WorkWindowError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        report = _base("hypothetical_replay")
        report["errors"] = [str(exc)]
    return report


def _observations(raw, identifiers, start_minute, cutoff, as_of):
    _json(raw)
    _keys(raw, {"events", "coverage"}, label="observations")
    if not isinstance(raw["events"], list) or len(raw["events"]) > MAX_EVENTS:
        raise WorkWindowError("Observation events must be a bounded list.")
    events, event_ids, starts, departures, completions = [], set(), {}, set(), set()
    prior_minute, active, return_start, returned = start_minute, None, None, None
    for original in raw["events"]:
        if not isinstance(original, dict):
            raise WorkWindowError("Each observation event must be an object.")
        kind = original.get("type")
        if kind not in _JOB_TYPES | _RETURN_TYPES:
            raise WorkWindowError("Unknown observation event type.")
        required = {"event_id", "type", "minute", "available_minute", "evidence_ref"}
        if kind in _JOB_TYPES:
            required.add("job_id")
        if kind == "condition_verified":
            required.update({"condition", "accepted"})
        _keys(original, required, {"notes"}, label=f"{kind} event")
        event = deepcopy(original)
        identifier = _text(event["event_id"], "Event ID")
        if identifier in event_ids:
            raise WorkWindowError("Observation event IDs cannot repeat.")
        event_ids.add(identifier)
        minute = event["minute"] = _number(event["minute"], "Event minute")
        available = event["available_minute"] = _number(event["available_minute"], "Event available_minute")
        if not prior_minute <= minute <= available <= as_of:
            raise WorkWindowError("Events need occurrence order, occurrence before availability, and no future observations beyond as_of_minute.")
        prior_minute = minute
        event["evidence_ref"] = _reference(event["evidence_ref"], "Event evidence_ref")
        if "notes" in event:
            _text(event["notes"], "Event notes")
        job = event.get("job_id")
        if kind in _JOB_TYPES:
            if job not in identifiers:
                raise WorkWindowError("Observed job IDs must belong to the supplied replay's recorded scope.")
            if returned is not None and kind != "condition_verified":
                raise WorkWindowError("This single-window audit cannot append more work after the recorded depot return.")
        if kind == "departure_observed":
            if job in departures or job in starts or active is not None or return_start is not None:
                raise WorkWindowError("Duplicate or inconsistent job departure for the single crew.")
            departures.add(job)
        elif kind == "work_started":
            if job in starts or active is not None or return_start is not None:
                raise WorkWindowError("Overlapping/repeated work or work after return starts is outside this single-crew audit.")
            starts[job], active = minute, job
        elif kind in {"completion_reported", "work_interrupted"}:
            if return_start is not None and minute > return_start:
                raise WorkWindowError("Physical completion/interruption after return starts is outside this work cycle; use available_minute for a later report of an earlier event.")
            if job not in starts or (kind == "completion_reported" and (job in completions or minute <= starts[job])):
                raise WorkWindowError("Completion/interruption requires a recorded start; positive work duration and unique completion are required.")
            if kind == "work_interrupted" and job in completions:
                raise WorkWindowError("Interruption after completion needs a new work cycle; this single-start audit cannot reuse earlier completion evidence.")
            if active not in (None, job):
                raise WorkWindowError("An event conflicts with the single crew's active job.")
            if kind == "completion_reported":
                completions.add(job)
            active = None
        elif kind == "condition_verified":
            if job not in starts:
                raise WorkWindowError("Restoration verification requires a recorded start in this window.")
            if event["condition"] not in {"restored", "baseline", "intermediate", "unknown"} or not isinstance(event["accepted"], bool):
                raise WorkWindowError("Verification requires a documented condition and an explicit boolean acceptance.")
            if event["condition"] == "restored" and event["accepted"] and job not in completions:
                raise WorkWindowError("Restored credit requires separate completion reporting followed by verification.")
            if event["accepted"] and event["condition"] in {"restored", "baseline"} and active == job:
                active = None
        elif kind == "return_started":
            if return_start is not None or returned is not None:
                raise WorkWindowError("Return departure cannot repeat or follow the recorded arrival.")
            return_start = minute
            active = None  # Leaving does not establish the abandoned job's condition.
        elif kind == "returned":
            if returned is not None or (return_start is not None and minute < return_start):
                raise WorkWindowError("The recorded depot arrival is inconsistent.")
            returned = minute
            active = None
        events.append(event)
    coverage = raw["coverage"]
    if coverage is not None:
        _keys(coverage, {"from_minute", "through_minute", "available_minute", "evidence_ref"}, label="coverage")
        coverage = deepcopy(coverage)
        for key in ("from_minute", "through_minute", "available_minute"):
            coverage[key] = _number(coverage[key], f"coverage.{key}")
        if not coverage["from_minute"] <= coverage["through_minute"] <= coverage["available_minute"] <= as_of:
            raise WorkWindowError("Coverage times are inconsistent.")
        coverage["evidence_ref"] = _reference(coverage["evidence_ref"], "coverage.evidence_ref")
    return events, coverage


def _coverage_complete(coverage, start, cutoff, availability_cutoff):
    return bool(coverage and coverage["from_minute"] <= start and coverage["through_minute"] >= cutoff
                and coverage["available_minute"] <= availability_cutoff)


def _condition(events, job, coverage_complete):
    state = "no_start_recorded_in_attested_log" if coverage_complete else "no_evidence"
    start, completion, verification = None, None, None
    for event in events:
        if event.get("job_id") != job:
            continue
        kind = event["type"]
        if kind == "departure_observed":
            state = "travelling_or_awaiting_work"
        elif kind == "work_started":
            state, start = "work_unfinished_or_unreported", event["minute"]
        elif kind == "completion_reported":
            state, completion, verification = "completion_reported_unverified", event["minute"], None
        elif kind == "work_interrupted":
            state, verification = "work_interrupted_unverified", None
        elif kind == "condition_verified":
            verification = event
            # The filtered information view can lack a start/completion whose
            # report arrived later. Verification alone cannot supply them.
            if start is None or (event["condition"] == "restored" and completion is None):
                state = "condition_unresolved"
            elif event["accepted"] and event["condition"] == "restored":
                state = "restored_documented"
            elif event["accepted"] and event["condition"] == "baseline":
                state = "baseline_restoration_documented"
            elif event["accepted"] and event["condition"] == "intermediate":
                state = "intermediate_condition_unsupported"
            else:
                state = "condition_unresolved"
    return {"state": state, "observed_start_minute": start, "completion_reported_minute": completion,
            "verification_minute": verification["minute"] if verification else None,
            "verification_available_minute": verification["available_minute"] if verification else None}


def _recovery(raw, cutoff, as_of, deadline, unresolved, returned):
    result = {"status": "not_supplied", "restoration_minutes": None, "inspection_minutes": None,
              "return_minutes": None, "budgeted_finish_minute": None, "fits_planned_deadline": None,
              "return_confirmed": returned is not None, "return_observed_minute": returned,
              "recovery_or_return_may_be_required": bool(unresolved or returned is None),
              "recovery_plan_approved": False, "unverified_condition_cleared_by_budget": False}
    if raw is None:
        return result
    _keys(raw, {"restoration_minutes", "inspection_minutes", "return_minutes", "available_minute", "source"}, label="recovery")
    bounds = {key: _number(raw[key], f"recovery.{key}", nullable=True)
              for key in ("restoration_minutes", "inspection_minutes", "return_minutes")}
    available = _number(raw["available_minute"], "recovery.available_minute")
    if available > as_of:
        raise WorkWindowError("A recovery estimate cannot arrive after the audit as-of time.")
    _text(raw["source"], "recovery.source")
    result.update(bounds, source=raw["source"], available_minute=available, available_at_cutoff=available <= cutoff)
    if available > cutoff:
        result["status"] = "later_estimate_not_available_at_cutoff"
    elif any(value is None for value in bounds.values()):
        result["status"] = "unknown_duration_bounds"
    else:
        budgeted = cutoff + sum(bounds.values())
        if not math.isfinite(budgeted):
            raise WorkWindowError("Recovery arithmetic exceeds the supported numeric range.")
        result.update(status="declared_budget_only", budgeted_finish_minute=budgeted, fits_planned_deadline=budgeted <= deadline)
    return result


def audit_observed_window(replay_result, observations, *, stop, as_of_minute, recovery=None, storm_timing=None):
    """Audit reported actual events against a recorded stop, preserving information time.

    ``stop.minute`` is when the stop instruction/unsafe condition was actually
    observed, not a forecast storm time. Event availability governs what could
    have been known then; later reports remain a separate retrospective view.
    """
    report = _base("reported_observations")
    try:
        _json({"stop": stop, "recovery": recovery, "storm_timing": storm_timing})
        replay, identifiers = _replay(replay_result)
        _keys(stop, {"minute", "reason", "evidence_ref"}, label="stop")
        cutoff, as_of = _number(stop["minute"], "stop.minute"), _number(as_of_minute, "as_of_minute")
        if cutoff < replay["start_minute"] or as_of < cutoff:
            raise WorkWindowError("The observed stop must lie in this replay window and no later than the audit as-of time.")
        _text(stop["reason"], "Stop reason")
        _reference(stop["evidence_ref"], "stop.evidence_ref")
        events, coverage = _observations(observations, identifiers, replay["start_minute"], cutoff, as_of)
        known = [event for event in events if event["minute"] <= cutoff and event["available_minute"] <= cutoff]
        retrospective = [event for event in events if event["minute"] <= cutoff]
        complete = _coverage_complete(coverage, replay["start_minute"], cutoff, cutoff)
        retrospective_complete = _coverage_complete(coverage, replay["start_minute"], cutoff, as_of)
        by_id = {event["job_id"]: event for event in replay["events"]}
        for job in identifiers:
            decision_state = _condition(known, job, complete)
            retro = _condition(retrospective, job, retrospective_complete)
            current = _condition(events, job, _coverage_complete(coverage, replay["start_minute"], as_of, as_of))
            row = {**_row(job, by_id.get(job)), **decision_state,
                   "retrospective_state_at_cutoff": retro["state"], "state_as_of": current["state"],
                   "observed_start_as_of_minute": current["observed_start_minute"],
                   "completion_reported_as_of_minute": current["completion_reported_minute"],
                   "verification_as_of_minute": current["verification_minute"],
                   "verification_available_as_of_minute": current["verification_available_minute"]}
            report["jobs"].append(row)
        restored = [row["job_id"] for row in report["jobs"] if row["state"] == "restored_documented"]
        unresolved = [row["job_id"] for row in report["jobs"] if row["state"] in _UNRESOLVED]
        post_stop_starts = [event["event_id"] for event in events if event["type"] == "work_started" and event["minute"] >= cutoff]
        known_returns = [event["minute"] for event in known if event["type"] == "returned"]
        all_returns = [event["minute"] for event in events if event["type"] == "returned"]
        return_at_cutoff = known_returns[-1] if known_returns else None
        planned_order = [event["job_id"] for event in replay["events"]]
        actual_order = [event["job_id"] for event in events if event["type"] == "work_started"]
        expected_subsequence = [job for job in planned_order if job in actual_order]
        deviations = actual_order != expected_subsequence
        report.update(valid=True, replay_sha256=_sha(replay_result), stop_minute=cutoff, as_of_minute=as_of,
                      planned_deadline_minute=replay["deadline_minutes"], stop=deepcopy(stop),
                      original_replay_status=replay["status"], original_replay_reasons=replay["reasons"],
                      replay_job_order=planned_order, actual_started_order=actual_order,
                      actual_order_differs_from_replay=deviations,
                      documentary_coverage_at_cutoff="attested_complete" if complete else "missing_or_incomplete",
                      retrospective_documentary_coverage="attested_complete" if retrospective_complete else "missing_or_incomplete",
                      observation_events=events, coverage_declaration=coverage,
                      unlogged_work_independently_excluded=False,
                      decision_known_restored_jobs=restored, unresolved_jobs=unresolved,
                      decision_known_baseline_jobs=[row["job_id"] for row in report["jobs"] if row["state"] == "baseline_restoration_documented"],
                      stop_rule_breach=bool(post_stop_starts), stop_rule_breach_event_ids=post_stop_starts,
                      later_available_event_ids=[event["event_id"] for event in events if event["available_minute"] > cutoff],
                      post_cutoff_event_ids=[event["event_id"] for event in events if event["minute"] > cutoff],
                      returned_by_as_of=bool(all_returns), return_observed_as_of_minute=all_returns[-1] if all_returns else None,
                      reported_return_after_deadline=bool(all_returns and all_returns[-1] > replay["deadline_minutes"]),
                      stop_after_planned_deadline=cutoff > replay["deadline_minutes"],
                      storm_timing=_storm(storm_timing, cutoff, as_of),
                      recovery=_recovery(recovery, cutoff, as_of, replay["deadline_minutes"], unresolved, return_at_cutoff))
        report["status"] = "observed_stop_breach" if post_stop_starts else "unresolved" if unresolved or not complete or return_at_cutoff is None else "documented_conditions_only"
        report["summary"] = (f"Reported stop at minute {cutoff:g}: {len(restored)} restored job(s) have completion and accepted verification known by the cutoff; "
                             f"{len(unresolved)} job condition(s) remain unresolved in that information view. "
                             + (f"{len(post_stop_starts)} start(s) at or after the stop are recorded as breaches. " if post_stop_starts else "")
                             + ("A depot return is not documented in that information view. " if return_at_cutoff is None else "")
                             + "Later evidence is retained separately; this audit grants no hydraulic or work authority.")
        if not complete:
            report["warnings"].append("No complete event-coverage declaration was available at the cutoff; absence of an event is not proof that work did not occur.")
        if deviations:
            report["warnings"].append("Reported actual work order differs from the supplied replay. The audit preserves that deviation and does not reconstruct a new optimal queue.")
        if replay["status"] != "supported":
            report["warnings"].append("The original replay is unsupported; observed records do not repair its original approval or numerical evidence.")
        report["observations_sha256"] = _sha(observations)
        report["stop_sha256"] = _sha(stop)
    except (WorkWindowError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        report = _base("reported_observations")
        report["errors"] = [str(exc)]
    return report
