"""Exact, nonanticipating one-crew planning for the synthetic reference case.

``hydraulic_fn(completed_jobs, scenario)`` must return the documented hydraulic
result. The selector receives planning scenarios only. ``evaluate_holdouts``
replays already-frozen policies and never chooses a new operational policy.
All times are minutes after shift start. Bounds include the whole on-site job;
travel and a return to DEPOT are additional. This is a dry, restored-state model.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from itertools import combinations, permutations
import json
import math
from pathlib import Path
from typing import Callable, Iterable

_EPS = 1e-9
VERSION = "1.0.0"
_LOADED_SOURCE_SHA256 = sha256(Path(__file__).read_bytes()).hexdigest()


def _number(value, name, *, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return number


def _job_map(jobs):
    records = list(jobs.values()) if isinstance(jobs, dict) else list(jobs)
    result = {}
    for raw in records:
        job = deepcopy(raw)
        identifier = job.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise ValueError("Jobs require unique, nonempty string IDs")
        job["nominal_minutes"] = _number(job.get("nominal_minutes"), f"{identifier}.nominal_minutes", positive=True)
        job["max_minutes"] = _number(job.get("max_minutes"), f"{identifier}.max_minutes", positive=True)
        if job["nominal_minutes"] > job["max_minutes"]:
            raise ValueError(f"{identifier}: nominal duration exceeds its declared bound")
        job["cost_rm"] = _number(job.get("cost_rm", 0), f"{identifier}.cost_rm")
        job["downstream_rank"] = _number(job.get("downstream_rank", 0), f"{identifier}.downstream_rank")
        job["prerequisites"] = list(job.get("prerequisites", []))
        result[identifier] = job
    for identifier, job in result.items():
        if len(set(job["prerequisites"])) != len(job["prerequisites"]):
            raise ValueError(f"{identifier}: duplicate prerequisites")
        if set(job["prerequisites"]) - set(result):
            raise ValueError(f"{identifier}: unknown prerequisite")
    visiting, visited = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise ValueError("Job prerequisites contain a cycle")
        if identifier in visited:
            return
        visiting.add(identifier)
        for dependency in result[identifier]["prerequisites"]:
            visit(dependency)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in result:
        visit(identifier)
    return result


def enumerate_queues(job_ids: Iterable[str]) -> list[tuple]:
    """All ordered subsets, including no work: 65 for four, 1,957 for six."""
    identifiers = tuple(job_ids)
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError("Job IDs must be nonempty strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate job IDs are not allowed")
    identifiers = tuple(sorted(identifiers))
    return [queue for size in range(len(identifiers) + 1) for queue in permutations(identifiers, size)]


def _location(location, jobs):
    if not isinstance(location, str) or not location:
        raise ValueError("start_location must identify DEPOT, a job, or a job asset")
    if location == "DEPOT" or location in jobs:
        return location
    matching = [identifier for identifier, job in jobs.items() if job.get("asset_id") == location]
    if len(matching) == 1:
        return matching[0]
    raise ValueError(f"Unknown or ambiguous start location: {location}")


def _travel(origin, destination, minutes):
    return 0.0 if origin == destination else minutes


def _dispatch(queue, jobs, deadline_minutes, travel_minutes=10,
              actual_durations=None, already_completed=(), start_minute=0,
              start_location="DEPOT", selector=None):
    job_map = _job_map(jobs)
    ordered = list(queue)
    if len(set(ordered)) != len(ordered) or set(ordered) - set(job_map):
        raise ValueError("Queue must contain distinct known job IDs")
    done = set(already_completed)
    if done - set(job_map):
        raise ValueError("already_completed contains unknown jobs")
    deadline = _number(deadline_minutes, "deadline_minutes")
    travel = _number(travel_minutes, "travel_minutes")
    initial_minute = minute = _number(start_minute, "start_minute")
    location = _location(start_location, job_map)
    initial_location = location
    events, newly_done, reasons, skips = [], [], [], []
    remaining = []
    for identifier in ordered:
        if identifier in done:
            skips.append({"job_id": identifier, "reason": "already_completed"})
        else:
            remaining.append(identifier)
    status = "supported"
    if minute + _travel(location, "DEPOT", travel) > deadline + _EPS:
        status = "unsupported"
        reasons.append("Current time and location cannot return to the depot within the approved deadline.")
    while remaining and status == "supported":
        eligible = [identifier for identifier in remaining
                    if set(job_map[identifier]["prerequisites"]) <= done
                    and minute + _travel(location, identifier, travel)
                    + job_map[identifier]["max_minutes"]
                    + _travel(identifier, "DEPOT", travel) <= deadline + _EPS]
        if not eligible:
            break
        if selector is None:
            identifier = eligible[0]
        else:
            decision = selector(tuple(eligible), frozenset(done), minute, location)
            if isinstance(decision, dict) and decision.get("status") == "unsupported":
                status = "unsupported"
                reasons.extend(decision.get("reasons", ["Policy decision is unsupported."]))
                break
            identifier = decision
            if identifier is None:  # The policy deliberately stops when no supported positive increment exists.
                break
            if identifier not in eligible:
                raise ValueError("Policy selected an ineligible job")
        job = job_map[identifier]
        arrival = minute + _travel(location, identifier, travel)
        # Deliberately read the realised duration only AFTER dispatch selection.
        try:
            actual = job["nominal_minutes"] if actual_durations is None else _number(
                actual_durations[identifier], f"realised duration for {identifier}", positive=True)
        except (KeyError, ValueError, TypeError) as exc:
            status = "unsupported"
            reasons.append(f"Dispatched {identifier} has no valid realised duration: {exc}")
            break
        finish = arrival + actual
        event = {"job_id": identifier, "depart_minute": minute, "start_minute": arrival,
                 "finish_minute": finish, "actual_minutes": actual,
                 "max_minutes": job["max_minutes"], "from_location": location,
                 "to_location": identifier, "bound_finish_minute": arrival + job["max_minutes"],
                 "supported": actual <= job["max_minutes"] + _EPS}
        events.append(event)
        remaining.remove(identifier)
        minute, location = finish, identifier
        if actual > job["max_minutes"] + _EPS:
            status = "unsupported"
            reasons.append(f"{identifier} exceeded its declared duration bound ({actual:g} > {job['max_minutes']:g} minutes); physical restoration is unverified.")
            break
        done.add(identifier)
        newly_done.append(identifier)
    for identifier in remaining:
        missing = sorted(set(job_map[identifier]["prerequisites"]) - done)
        if missing:
            reason = "prerequisites_not_met"
        elif minute + _travel(location, identifier, travel) + job_map[identifier]["max_minutes"] + _travel(identifier, "DEPOT", travel) > deadline + _EPS:
            reason = "insufficient_bound_window"
        else:
            reason = "policy_stopped" if status == "supported" else "unsupported_episode"
        skips.append({"job_id": identifier, "reason": reason, "missing_prerequisites": missing})
    work_finish = minute
    minute += _travel(location, "DEPOT", travel)
    if minute > deadline + _EPS and status == "supported":
        status = "unsupported"
        reasons.append("The required return exceeds the approved deadline.")
    return {"status": status, "completed_jobs": newly_done, "events": events,
            "finish_minute": minute, "work_finish_minute": work_finish,
            "crew_minutes": minute - initial_minute, "skipped": skips, "reasons": reasons,
            "start_minute": initial_minute, "start_location": initial_location,
            "final_location": "DEPOT", "last_work_location": location,
            "deadline_minutes": deadline, "return_minutes": minute - work_finish}


def replay(queue, jobs, deadline_minutes, travel_minutes=10, actual_durations=None,
           already_completed=(), start_minute=0, start_location="DEPOT") -> dict:
    """Replay a locked priority queue with bound-gated, nonanticipating dispatch.

    Deferred jobs are reconsidered after every completion. A longer-than-bound
    job is an unsupported transition even if it happens to return before deadline.
    Nominal durations are used only when no realised-duration mapping is supplied.
    """
    return _dispatch(queue, jobs, deadline_minutes, travel_minutes, actual_durations,
                     already_completed, start_minute, start_location)


def _state_key(state):
    return "+".join(sorted(state)) or "EMPTY"


def _plan_id(queue):
    # The empty policy sorts first when its outcomes and resource use tie every
    # infeasible queue; the interface should recommend no work, not phantom work.
    return "P-" + ("-".join(queue) if queue else "0-NONE")


def _fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _case_snapshot(case):
    return deepcopy({key: value for key, value in case.items() if key != "scenarios"})


def _planner_source_fingerprint():
    """Pin the dispatch/ranking implementation, not only its release label."""
    return _LOADED_SOURCE_SHA256


class _Evaluator:
    def __init__(self, case, hydraulic_fn, settings):
        self.case = case
        self.jobs = _job_map(case["jobs"])
        self.hydraulic_fn = hydraulic_fn
        self.settings = settings
        self.protected = tuple(case.get("protected_nodes", ()))
        self.required_nodes = set(self.protected) | {node["id"] for node in case.get("nodes", ())}
        self.epsilon = _number(case.get("epsilon_m3", 0.05), "epsilon_m3")
        self.cache = {}
        self.callback_calls = 0

    def hydraulic(self, state, scenario):
        # Durations and labels do not change a physical state; the adapter also
        # hashes its complete forcing/engine/numerical configuration on disk.
        scenario_key = _fingerprint({key: value for key, value in scenario.items() if key != "durations"})
        key = (tuple(sorted(state)), scenario_key)
        if key not in self.cache:
            self.callback_calls += 1
            try:
                raw = self.hydraulic_fn(tuple(sorted(state)), deepcopy(scenario))
                self.cache[key] = self._compact_hydraulic(raw)
            except Exception as exc:
                self.cache[key] = {"valid": False, "run_id": None, "total_spill_m3": None,
                                   "nodes": {}, "errors": [f"Hydraulic evaluation failed: {type(exc).__name__}: {exc}"]}
        return self.cache[key]

    def _compact_hydraulic(self, raw):
        errors = list(raw.get("errors", []))
        valid = raw.get("valid") is True and raw.get("status") == "succeeded"
        if not valid:
            return {"valid": False, "run_id": raw.get("run_id"), "total_spill_m3": None,
                    "nodes": {}, "errors": errors or ["Hydraulic run is not valid and succeeded."]}
        try:
            if not isinstance(raw.get("run_id"), str) or not raw["run_id"].strip():
                raise ValueError("Hydraulic evidence requires a nonempty run_id")
            total = _number(raw.get("total_spill_m3"), "hydraulic total_spill_m3")
            nodes = deepcopy(raw.get("nodes", {}))
            if not isinstance(nodes, dict) or not nodes:
                raise ValueError("Hydraulic node metrics are missing")
            for node, metrics in nodes.items():
                metrics["spill_m3"] = _number(metrics.get("spill_m3"), f"{node}.spill_m3")
            missing = self.required_nodes - set(nodes)
            if missing:
                raise ValueError(f"Declared model/protected node metrics are missing: {sorted(missing)}")
            if not math.isclose(sum(item["spill_m3"] for item in nodes.values()), total, rel_tol=1e-6, abs_tol=0.001):
                raise ValueError("Total spill does not equal the sum of represented node spills")
        except (ValueError, TypeError, AttributeError) as exc:
            return {"valid": False, "run_id": raw.get("run_id"), "total_spill_m3": None,
                    "nodes": {}, "errors": errors + [str(exc)]}
        return {"valid": True, "run_id": raw.get("run_id"), "total_spill_m3": total,
                "nodes": nodes, "errors": errors}

    def violations(self, run, reference, state, scenario_id):
        return [{"scenario_id": scenario_id, "node_id": node, "completed_jobs": sorted(state),
                 "spill_m3": run["nodes"][node]["spill_m3"],
                 "reference_spill_m3": reference["nodes"][node]["spill_m3"],
                 "increase_m3": run["nodes"][node]["spill_m3"] - reference["nodes"][node]["spill_m3"],
                 "tolerance_m3": self.epsilon}
                for node in self.protected
                if run["nodes"][node]["spill_m3"] > reference["nodes"][node]["spill_m3"] + self.epsilon + _EPS]

    def scenario_result(self, queue, scenario, *, selector=None, nominal=False, oracle=False):
        settings = self.settings
        durations = {identifier: job["nominal_minutes"] for identifier, job in self.jobs.items()} if nominal else scenario.get("durations", {})
        replay_jobs = self.jobs
        if oracle:
            replay_jobs = deepcopy(self.jobs)
            for identifier, job in replay_jobs.items():
                if identifier in settings["already_completed"]:
                    continue
                job["max_minutes"] = job["nominal_minutes"] = _number(durations.get(identifier), f"oracle duration {identifier}", positive=True)
        replayed = _dispatch(queue, replay_jobs, actual_durations=durations, selector=selector, **settings)
        state = set(settings["already_completed"]) | set(replayed["completed_jobs"])
        result = {"scenario_id": scenario["id"], "status": "supported", "completed_jobs": sorted(state),
                  "newly_completed_jobs": list(replayed["completed_jobs"]), "crew_minutes": replayed["crew_minutes"],
                  "run_id": None, "total_spill_m3": None, "nodes": {}, "replay": replayed,
                  "protected_violations": [], "reasons": list(replayed["reasons"]), "intermediate_states": []}
        if replayed["status"] != "supported":
            result["status"] = "unresolved"
            return result
        reference = self.hydraulic(settings["already_completed"], scenario)
        final = self.hydraulic(state, scenario)
        if not reference["valid"] or not final["valid"]:
            result["status"] = "unresolved"
            result["run_id"] = final["run_id"]
            result["reasons"].extend(reference["errors"] + final["errors"])
            return result
        result.update({"run_id": final["run_id"], "total_spill_m3": final["total_spill_m3"], "nodes": final["nodes"]})
        # Every completed prefix is a declared supported dry-work stopping state.
        # Screening only the final state could conceal a harmful early cutoff.
        prefix = set(settings["already_completed"])
        prefixes = []
        for identifier in replayed["completed_jobs"]:
            prefix.add(identifier)
            prefixes.append(set(prefix))
        if not prefixes:
            prefixes = [state]
        for prefix in prefixes:
            run = self.hydraulic(prefix, scenario)
            if not run["valid"]:
                result["status"] = "unresolved"
                result["reasons"].extend(run["errors"])
                continue
            violations = self.violations(run, reference, prefix, scenario["id"])
            result["intermediate_states"].append({"completed_jobs": sorted(prefix), "run_id": run["run_id"],
                                                   "total_spill_m3": run["total_spill_m3"],
                                                   "protected_violations": violations})
            result["protected_violations"].extend(violations)
        if result["status"] == "unresolved":
            # Never present a partially resolved scenario as a supported score.
            result["total_spill_m3"] = None
        elif result["protected_violations"]:
            result["status"] = "inadmissible"
            result["reasons"].append("At least one protected location worsens beyond tolerance in a reachable completed-work state.")
        return result

    def plan(self, queue, scenarios, *, selector=None, nominal=False, oracle=False):
        results = [self.scenario_result(queue, scenario, selector=selector, nominal=nominal, oracle=oracle) for scenario in scenarios]
        unresolved = any(result["status"] == "unresolved" for result in results)
        admissible = all(result["status"] == "supported" for result in results)
        status = "unresolved" if unresolved else "supported" if admissible else "inadmissible"
        values = [result["total_spill_m3"] for result in results]
        return {"id": _plan_id(queue), "queue": list(queue), "admissible": admissible, "status": status,
                "worst_spill_m3": None if unresolved else max(values),
                "mean_spill_m3": None if unresolved else sum(values) / len(values),
                "worst_crew_minutes": max(result["crew_minutes"] for result in results),
                "worst_cost_rm": max(sum(self.jobs[identifier]["cost_rm"] for identifier in result["newly_completed_jobs"]) for result in results),
                "scenario_results": results,
                "reasons": sorted({reason for result in results for reason in result["reasons"]})}


def _rank(plans, tie_m3, tie_minutes=0.0, tie_cost_rm=0.0):
    """Stagewise bands measured from each attained minimum, never pairwise."""
    retained = [plan for plan in plans if plan["admissible"]]
    audit = []
    hydraulic_alternatives = []
    for field, band in (("worst_spill_m3", tie_m3), ("mean_spill_m3", tie_m3),
                        ("worst_crew_minutes", tie_minutes), ("worst_cost_rm", tie_cost_rm)):
        if not retained:
            break
        minimum = min(plan[field] for plan in retained)
        retained = [plan for plan in retained if plan[field] <= minimum + band + _EPS]
        audit.append({"field": field, "attained_minimum": minimum, "band": band,
                      "remaining_plan_ids": [plan["id"] for plan in retained]})
        if field == "mean_spill_m3":
            hydraulic_alternatives = list(retained)
    retained.sort(key=lambda plan: plan["id"])
    selected = retained[0] if retained else None
    alternatives = sorted((plan for plan in hydraulic_alternatives if not selected or plan["id"] != selected["id"]),
                          key=lambda plan: (plan["worst_crew_minutes"], plan["worst_cost_rm"], plan["id"]))
    return selected, alternatives, audit


def _marginal_table(evaluator, scenarios, remaining):
    """Freeze hydraulic marginal values for every possible observed state.

    The policy subsequently sees only this table, eligibility and elapsed time;
    no realised scenario hydraulic input or future duration enters its chooser.
    """
    table = {}
    initial = set(evaluator.settings["already_completed"])
    for size in range(len(remaining) + 1):
        for subset in combinations(remaining, size):
            state = initial | set(subset)
            candidates = {}
            for identifier in remaining:
                if identifier in state or not set(evaluator.jobs[identifier]["prerequisites"]) <= state:
                    continue
                differences, violations, errors = [], [], []
                for scenario in scenarios:
                    before = evaluator.hydraulic(state, scenario)
                    after = evaluator.hydraulic(state | {identifier}, scenario)
                    reference = evaluator.hydraulic(initial, scenario)
                    if not before["valid"] or not after["valid"] or not reference["valid"]:
                        errors.extend(before["errors"] + after["errors"] + reference["errors"])
                        continue
                    differences.append(before["total_spill_m3"] - after["total_spill_m3"])
                    violations.extend(evaluator.violations(after, reference, state | {identifier}, scenario["id"]))
                candidates[identifier] = {"valid": not errors and len(differences) == len(scenarios),
                                          "mean_gain_m3": sum(differences) / len(differences) if differences else None,
                                          "no_worsening": not violations, "errors": sorted(set(errors))}
            table[_state_key(state)] = candidates
    return table


def _marginal_selector(table, jobs, travel):
    def choose(eligible, done, minute, location):
        candidates = table.get(_state_key(done), {})
        scored = []
        errors = []
        for identifier in eligible:
            candidate = candidates.get(identifier)
            if not candidate or not candidate["valid"]:
                errors.append(f"Marginal comparison for {identifier} is unresolved in the frozen planning ensemble.")
                continue
            if not candidate["no_worsening"] or candidate["mean_gain_m3"] <= _EPS:
                continue
            increment = (_travel(location, identifier, travel) + jobs[identifier]["nominal_minutes"]
                         + _travel(identifier, "DEPOT", travel) - _travel(location, "DEPOT", travel))
            ratio = candidate["mean_gain_m3"] / increment
            scored.append((-ratio, jobs[identifier]["downstream_rank"], identifier))
        if errors:
            return {"status": "unsupported", "reasons": errors}
        return min(scored)[2] if scored else None
    return choose


def _definitions(nominal_id):
    return {
        "robust": {"label": "Finite-scenario planner", "definition": "Exact locked priority queues, worst spill, minimum-relative tie bands, grid mean, crew time, illustrative cost and stable ID."},
        "no_work": {"label": "No additional discretionary work", "definition": "Retain the verified starting state and return from the current location using the same deadline."},
        "downstream_first": {"label": "Downstream-first heuristic", "definition": "Reviewed topology rank then shorter nominal job then stable ID; skip jobs that cannot fit their upper bound, reconsider prerequisites, and use observed elapsed time. Defined heuristic, not independently validated expert practice."},
        "marginal_benefit": {"label": "Marginal hydraulic benefit per crew minute", "definition": "Recompute frozen planning-grid mean marginal spill reduction after each observed completion, divided by incremental nominal work and travel time. Apply protected-location screening and the common upper-bound gate; stop if no positive supported increment exists."},
        "deterministic_nominal": {"label": "Deterministic nominal planner", "definition": f"Exact planning using hydraulic scenario {nominal_id} and nominal job durations; the same declared upper-bound dispatch gate still applies."},
        "user_entered": {"label": "User-entered comparison", "definition": "The queue entered independently by the user, replayed under the same constraints; no operator expertise is claimed."},
    }


def _flatten(method, plan, definitions):
    return [{"method": method, "method_label": definitions[method]["label"], "queue": plan["queue"],
             "plan_status": plan["status"], **deepcopy(result)} for result in plan["scenario_results"]]


def evaluate_episode(case, scenarios, hydraulic_fn: Callable, deadline_minutes=180,
                     already_completed=(), start_minute=0, start_location="DEPOT",
                     operator_queue=None) -> dict:
    """Select and freeze policies from planning inputs; never accept holdouts.

    All returned plans/results are JSON serialisable. Actual hydraulic evidence
    is referenced by run_id and compact node metrics, not copied output files.
    No-work is a legitimate supported selection; recommendation=None means the
    required evidence/operational envelope could not support any candidate.
    """
    scenarios = deepcopy(list(scenarios))
    if not scenarios or any(scenario.get("phase") != "planning" for scenario in scenarios):
        raise ValueError("Selection requires a nonempty, planning-only scenario ensemble")
    ids = [scenario.get("id") for scenario in scenarios]
    if any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(set(ids)) != len(ids):
        raise ValueError("Planning scenarios need unique, nonempty IDs")
    jobs = _job_map(case["jobs"])
    already_completed = tuple(sorted(set(already_completed)))
    if set(already_completed) - set(jobs):
        raise ValueError("Unknown already-completed job")
    if any(job.get("mandatory", False) for job in jobs.values()):
        raise ValueError("Mandatory-work scheduling is outside this discretionary reference prototype")
    settings = {"deadline_minutes": _number(deadline_minutes, "deadline_minutes"),
                "travel_minutes": _number(case.get("travel_minutes", 10), "travel_minutes"),
                "already_completed": list(already_completed), "start_minute": _number(start_minute, "start_minute"),
                "start_location": _location(start_location, jobs)}
    tie = _number(case.get("tie_m3", 0.05), "tie_m3")
    tie_minutes = _number(case.get("tie_minutes", 0), "tie_minutes")
    tie_cost = _number(case.get("tie_cost_rm", 0), "tie_cost_rm")
    remaining = sorted(set(jobs) - set(already_completed))
    queues = enumerate_queues(remaining)
    evaluator = _Evaluator(case, hydraulic_fn, settings)
    plans = [evaluator.plan(queue, scenarios) for queue in queues]
    recommendation, alternatives, ranking = _rank(plans, tie, tie_minutes, tie_cost)
    nominal_id = case.get("nominal_scenario_id", scenarios[0]["id"])
    nominal_matches = [scenario for scenario in scenarios if scenario["id"] == nominal_id]
    if not nominal_matches:
        raise ValueError("The declared nominal scenario must belong to the selected planning ensemble")
    nominal_plans = [evaluator.plan(queue, nominal_matches, nominal=True) for queue in queues]
    nominal_plan, _, _ = _rank(nominal_plans, tie, tie_minutes, tie_cost)
    definitions = _definitions(nominal_id)
    downstream = sorted(remaining, key=lambda identifier: (jobs[identifier]["downstream_rank"], jobs[identifier]["nominal_minutes"], identifier))
    marginal_table = _marginal_table(evaluator, scenarios, remaining)
    policies = {"no_work": {"kind": "fixed_queue", "queue": []},
                "downstream_first": {"kind": "fixed_queue", "queue": downstream},
                "marginal_benefit": {"kind": "marginal", "queue": remaining}}
    if recommendation is not None:
        policies["robust"] = {"kind": "fixed_queue", "queue": recommendation["queue"]}
    else:
        policies["robust"] = {"kind": "unavailable", "queue": [], "reason": "No supported admissible plan in the required planning ensemble."}
    policies["deterministic_nominal"] = ({"kind": "fixed_queue", "queue": nominal_plan["queue"]}
                                          if nominal_plan else {"kind": "unavailable", "queue": [], "reason": "No supported nominal plan."})
    if operator_queue is not None:
        # Validate the user queue before any comparison is called an operational result.
        replay(operator_queue, jobs, **settings)
        policies["user_entered"] = {"kind": "fixed_queue", "queue": list(operator_queue)}
    comparisons, baseline_plans = [], {}
    for method, policy in policies.items():
        if policy["kind"] == "unavailable":
            comparisons.extend({"method": method, "method_label": definitions[method]["label"], "queue": [],
                                "scenario_id": scenario["id"], "status": "unresolved", "plan_status": "unresolved",
                                "total_spill_m3": None, "completed_jobs": list(already_completed), "crew_minutes": None,
                                "run_id": None, "reasons": [policy["reason"]]} for scenario in scenarios)
            continue
        selector = _marginal_selector(marginal_table, jobs, settings["travel_minutes"]) if policy["kind"] == "marginal" else None
        plan = evaluator.plan(policy["queue"], scenarios, selector=selector)
        plan["id"] = "B-" + method
        baseline_plans[method] = plan
        comparisons.extend(_flatten(method, plan, definitions))
    snapshot = _case_snapshot(case)
    manifest = {"planner_version": VERSION, "planner_source_sha256": _planner_source_fingerprint(),
                "case_id": case.get("id"), "model_version": case.get("model_version"),
                "case_fingerprint": _fingerprint(snapshot), "planning_scenarios": scenarios, "settings": settings,
                "nominal_scenario_id": nominal_id, "tie_m3": tie, "tie_minutes": tie_minutes, "tie_cost_rm": tie_cost,
                "protected_nodes": list(evaluator.protected), "epsilon_m3": evaluator.epsilon,
                "screened_states": "Every completed prefix plus final state, under the matching planning forcing",
                "duration_information": "Realised durations are read only after dispatch; planning ensemble used to select locked policies",
                "grid_mean_interpretation": "Unweighted mean of declared scenarios; not an expected annual loss"}
    frozen_fingerprint = _fingerprint({"manifest": manifest, "policies": policies,
                                       "marginal_policy_table": marginal_table,
                                       "baseline_definitions": definitions})
    return {"recommended": deepcopy(recommendation), "alternatives": deepcopy(alternatives), "comparisons": comparisons,
            "plans": plans, "baseline_plans": baseline_plans, "baseline_definitions": definitions,
            "policies": policies, "marginal_policy_table": marginal_table, "decision_manifest": manifest,
            "frozen_fingerprint": frozen_fingerprint, "ranking_audit": ranking,
            "counts": {"enumerated_queues": len(queues), "remaining_jobs": len(remaining), "planning_scenarios": len(scenarios),
                       "supported_plans": sum(plan["status"] == "supported" for plan in plans),
                       "inadmissible_plans": sum(plan["status"] == "inadmissible" for plan in plans),
                       "unresolved_plans": sum(plan["status"] == "unresolved" for plan in plans),
                       "hydraulic_callback_calls": evaluator.callback_calls},
            "limitations": ["Synthetic finite-scenario dry-maintenance reference; no field benefit established.",
                            "Protected-location non-worsening does not imply flood-free or safe conditions.",
                            "Dispatch comparison assumes uniform travel and verified binary restoration.",
                            "Downstream-first is an explicit topology heuristic, not validated operator practice."]}


def evaluate_holdouts(frozen_episode, case, holdouts, hydraulic_fn: Callable) -> dict:
    """Replay frozen operational policies, then separately calculate an oracle.

    The oracle knows the realised hydraulic event AND actual durations and may
    replace duration bounds with that perfect knowledge. It is diagnostic only,
    never used to select, repair or relabel an operational recommendation.
    """
    manifest = frozen_episode["decision_manifest"]
    if _fingerprint(_case_snapshot(case)) != manifest["case_fingerprint"]:
        raise ValueError("Case inputs changed after policy selection; lock a new decision episode")
    if manifest.get("planner_source_sha256") != _planner_source_fingerprint():
        raise ValueError("Frozen episode does not identify the current planner implementation; preserve it and lock a new decision episode")
    expected = _fingerprint({"manifest": manifest, "policies": frozen_episode["policies"],
                             "marginal_policy_table": frozen_episode["marginal_policy_table"],
                             "baseline_definitions": frozen_episode["baseline_definitions"]})
    if expected != frozen_episode["frozen_fingerprint"]:
        raise ValueError("Frozen decision inputs or policies were modified")
    holdouts = deepcopy(list(holdouts))
    planning_ids = {scenario["id"] for scenario in manifest["planning_scenarios"]}
    identifiers = [scenario.get("id") for scenario in holdouts]
    if not holdouts or any(scenario.get("phase") != "holdout" for scenario in holdouts):
        raise ValueError("Evaluation requires explicitly labelled holdout scenarios")
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
        raise ValueError("Holdouts require unique nonempty IDs")
    if set(identifiers) & planning_ids:
        raise ValueError("A planning scenario cannot be reused as a holdout")
    evaluator = _Evaluator(case, hydraulic_fn, deepcopy(manifest["settings"]))
    definitions = frozen_episode["baseline_definitions"]
    comparisons = []
    for method, policy in frozen_episode["policies"].items():
        if policy["kind"] == "unavailable":
            comparisons.extend({"method": method, "method_label": definitions[method]["label"], "queue": [],
                                "scenario_id": scenario["id"], "status": "unresolved", "plan_status": "unresolved",
                                "total_spill_m3": None, "completed_jobs": list(manifest["settings"]["already_completed"]),
                                "crew_minutes": None, "run_id": None, "reasons": [policy["reason"]]} for scenario in holdouts)
            continue
        selector = _marginal_selector(frozen_episode["marginal_policy_table"], evaluator.jobs,
                                     evaluator.settings["travel_minutes"]) if policy["kind"] == "marginal" else None
        comparisons.extend(_flatten(method, evaluator.plan(policy["queue"], holdouts, selector=selector), definitions))
    remaining = sorted(set(evaluator.jobs) - set(evaluator.settings["already_completed"]))
    queues = enumerate_queues(remaining)
    oracles = []
    for scenario in holdouts:
        diagnostic = {"scenario_id": scenario["id"], "label": "Hindsight oracle — diagnostic only",
                      "information_advantage": "Perfect hydraulic forcing and realised duration knowledge; actual durations replace forecast bounds",
                      "status": "unresolved", "plan": None, "exact_minimum_spill_m3": None,
                      "best_supported_plan": None, "enumerated_queues": len(queues), "reasons": []}
        try:
            oracle_plans = [evaluator.plan(queue, [scenario], oracle=True) for queue in queues]
        except (ValueError, TypeError, AttributeError) as exc:
            # A diagnostic with missing foreknowledge cannot erase the already
            # replayed operational evidence, including abstentions and overruns.
            diagnostic["reasons"] = [f"Hindsight oracle could not be resolved: {exc}"]
        else:
            oracle, _, _ = _rank(oracle_plans, manifest["tie_m3"], manifest["tie_minutes"], manifest["tie_cost_rm"])
            diagnostic["best_supported_plan"] = oracle
            unresolved = [plan for plan in oracle_plans if plan["status"] == "unresolved"]
            if unresolved:
                diagnostic["reasons"] = sorted({reason for plan in unresolved for reason in plan["reasons"]})
                diagnostic["reasons"].append("An unresolved candidate prevents an exact hindsight minimum or lower-bound claim.")
            elif oracle is None:
                diagnostic["status"] = "inadmissible"
                diagnostic["reasons"] = ["No admissible hindsight schedule under the declared constraints."]
            else:
                admissible_losses = [plan["worst_spill_m3"] for plan in oracle_plans if plan["admissible"]]
                diagnostic.update(status="supported", plan=oracle, exact_minimum_spill_m3=min(admissible_losses))
        oracles.append(diagnostic)
    return {"frozen_fingerprint": frozen_episode["frozen_fingerprint"], "comparisons": comparisons,
            "diagnostic_oracles": oracles, "holdout_ids": identifiers,
            "hydraulic_callback_calls": evaluator.callback_calls,
            "protocol": "Operational policies and marginal decision table were frozen before holdout evaluation. No reselection.",
            "limitations": ["Synthetic holdouts test a locked method, not calibrated field performance.",
                            "Holdout loss or no-worsening failure remains visible; a hindsight oracle is not an operational competitor."]}
