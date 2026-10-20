"""Frozen, observation-conditioned research policies for a controlled bench model.

This module does not authorise field work. The observation is a synthetic input
available before selection, not the subsequently revealed event. Receiving stage
is held fixed and the initial storage state is prescribed at event release. Those
experimental controls are assumptions, not claims about natural water levels.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from itertools import combinations, product
import json
import math
from pathlib import Path

from . import assurance, planning

VERSION = "0.3.0-research-1"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = (
    "monsoon/observed_policy.py", "monsoon/policy_evaluation.py",
    "monsoon/planning.py", "monsoon/assurance.py", "monsoon/assurance_hydraulics.py",
    "monsoon/case.py", "monsoon/hydraulics.py", "monsoon/_swmm_worker.py",
    "data/reference_case.json", "tests/test_observed_policy.py",
)
METHODS = {
    "observed_robust": "Observation-conditioned finite-grid queue",
    "screened_marginal": "Screened adaptive marginal benefit per crew minute",
    "screened_downstream": "Screened downstream-first heuristic",
    "screened_nominal": "Screened deterministic nominal objective",
    "no_work": "No additional discretionary work",
    "original_queue_diagnostic": "Original v0.1 queue (historical unscreened diagnostic)",
}


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_fingerprints():
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCE_PATHS}


def load_protocol(path=None):
    value = json.loads(Path(path or ROOT / "data/policy_v3_protocol.json").read_text(encoding="utf-8"))
    validate_protocol(value)
    return value


def validate_protocol(value):
    if value.get("schema_version") != 1 or fingerprint({k: v for k, v in value.items() if k != "protocol_sha256"}) != value.get("protocol_sha256"):
        raise ValueError("The frozen observation-policy protocol was altered or unsupported.")


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation timestamps require a timezone")
    return parsed


def validate_observation(observation, protocol):
    """Whitelist decision-time information; absent, stale or future data closes dispatch."""
    required = {"id", "observed_at", "available_at", "decision_at", "quality", "source_kind",
                "source_id", "boundary_contract", "storage", "receiving_stage"}
    errors, bounds = [], {}
    try:
        if not isinstance(observation, dict) or set(observation) != required:
            raise ValueError("Observation has missing or unrecognised fields; future event fields are forbidden")
        if any(not isinstance(observation[k], str) or not observation[k].strip()
               for k in ("id", "source_id")):
            raise ValueError("Observation and source IDs must be nonempty")
        if observation["quality"] != "accepted":
            raise ValueError("Observation quality has not been accepted")
        if observation["source_kind"] != "synthetic_bench_observation":
            raise ValueError("This research policy supports only explicitly synthetic bench observations")
        if observation["boundary_contract"] != "prescribed_initial_storage_and_controlled_fixed_stage":
            raise ValueError("The controlled bench boundary contract is missing")
        observed, available, decision = [_timestamp(observation[k]) for k in
                                         ("observed_at", "available_at", "decision_at")]
        if not observed <= available <= decision:
            raise ValueError("Observation was not available at the decision time")
        age = (decision - observed).total_seconds() / 60
        if age > protocol["observation_contract"]["maximum_age_minutes"]:
            raise ValueError("Observation is stale at the decision time")
        for key, datum, low, high in (("storage", "depth_above_storage_invert", 0, 2),
                                      ("receiving_stage", "synthetic_model_vertical_datum", 98, 103)):
            item = observation[key]
            if not isinstance(item, dict) or set(item) != {"value_m", "uncertainty_m", "unit", "datum"}:
                raise ValueError(f"{key} observation is incomplete")
            if item["unit"] != "m" or item["datum"] != datum:
                raise ValueError(f"{key} units or datum do not match the model")
            value = _finite(item["value_m"], key)
            uncertainty = _finite(item["uncertainty_m"], f"{key} uncertainty")
            if uncertainty < protocol["observation_contract"]["minimum_uncertainty_m"][key]:
                raise ValueError(f"{key} uncertainty is below the prespecified illustrative accuracy")
            if uncertainty <= 0 or value - uncertainty < low or value + uncertainty > high:
                raise ValueError(f"{key} uncertainty interval is outside represented geometry")
            bounds[key] = [round(value - uncertainty, 9), round(value + uncertainty, 9)]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors, "bounds_m": bounds}


def condition_development(case, observation, protocol):
    """Preserve EVERY unobserved profile; cross each with both level-error endpoints."""
    checked = validate_observation(observation, protocol)
    if not checked["valid"]:
        raise ValueError("; ".join(checked["errors"]))
    scenarios = []
    duration_sets = {
        "nominal": {j["id"]: j["nominal_minutes"] for j in case["jobs"]},
        "bound": {j["id"]: j["max_minutes"] for j in case["jobs"]},
    }
    for profile, (storage, stage), (duration_id, durations) in product(
            protocol["development_profiles"],
            product(checked["bounds_m"]["storage"], checked["bounds_m"]["receiving_stage"]),
            duration_sets.items()):
        hydraulic = deepcopy(profile["hydraulic"])
        hydraulic.update(initial_storage_depth_m=storage, tailwater_m=stage)
        scenarios.append({"id": f'DEV-{profile["id"]}-S{storage:g}-T{stage:g}-{duration_id}',
                          "phase": "planning", "profile_id": profile["id"], "hydraulic": hydraulic,
                          "durations": deepcopy(durations)})
    nominal = deepcopy(protocol["development_profiles"][0]["hydraulic"])
    nominal.update(initial_storage_depth_m=observation["storage"]["value_m"],
                   tailwater_m=observation["receiving_stage"]["value_m"])
    scenarios.append({"id": "DEV-NOMINAL-CENTRE", "phase": "planning", "profile_id": "nominal-centre",
                      "hydraulic": nominal, "durations": duration_sets["nominal"]})
    return scenarios


class _Evidence:
    """One shared numerical/provenance gate, including stable per-node decisions."""
    def __init__(self, case, callback):
        self.case, self.callback, self.cache = case, callback, {}
        self.settings = {"deadline_minutes": case["default_deadline_minutes"],
                         "travel_minutes": case["travel_minutes"], "already_completed": [],
                         "start_minute": 0, "start_location": "DEPOT"}
        self.subject = {"case": planning._case_snapshot(case), "settings": self.settings,
                        "implementation": assurance._runtime_identity()}
        self.evaluator = planning._Evaluator(case, None, self.settings)

    def get(self, state, scenario):
        key = fingerprint({"state": sorted(state), "hydraulic": scenario["hydraulic"]})
        if key not in self.cache:
            try:
                raw = self.callback(tuple(sorted(state)), deepcopy(scenario))
                entry, gate = assurance._prepare_hydraulic(raw, state, scenario, self.subject)
                compact = self.evaluator._compact_hydraulic(gate)
                half = self.evaluator._compact_hydraulic(entry["raw"].get("assurance_numerics", {}).get("runs", [{}, {}])[1])
                self.cache[key] = {"base": compact, "half": half, "entry": entry}
            except Exception as exc:
                bad = {"valid": False, "run_id": None, "total_spill_m3": None, "nodes": {},
                       "errors": [f"Required evidence failed: {type(exc).__name__}: {exc}"]}
                self.cache[key] = {"base": bad, "half": deepcopy(bad), "entry": {"errors": bad["errors"]}}
        return self.cache[key]

    def compare(self, state, scenario):
        value, reference = self.get(state, scenario), self.get((), scenario)
        errors = value["base"]["errors"] + reference["base"]["errors"]
        nodes, violations = [], []
        if all(r[k]["valid"] for r in (value, reference) for k in ("base", "half")):
            for node in self.evaluator.required_nodes:
                a, b = value["base"]["nodes"][node], reference["base"]["nodes"][node]
                delta = a["spill_m3"] - b["spill_m3"]
                half_delta = value["half"]["nodes"][node]["spill_m3"] - reference["half"]["nodes"][node]["spill_m3"]
                protected = node in self.case["protected_nodes"]
                bad = protected and delta > self.case["epsilon_m3"] + planning._EPS
                half_bad = protected and half_delta > self.case["epsilon_m3"] + planning._EPS
                if bad != half_bad:
                    errors.append(f"{node}: protected-location decision changes under step halving")
                row = {"node_id": node, "spill_m3": a["spill_m3"], "reference_spill_m3": b["spill_m3"],
                       "increase_m3": delta, "half_step_increase_m3": half_delta,
                       "max_depth_m": a.get("max_depth_m"),
                       "duration_above_threshold_min": a.get("duration_above_threshold_min"),
                       "reference_duration_above_threshold_min": b.get("duration_above_threshold_min"),
                       "threshold_m": a.get("threshold_m"), "protected": protected,
                       "passes": not bad, "gate_stable": bad == half_bad}
                nodes.append(row)
                if bad:
                    violations.append(deepcopy(row))
        else:
            errors.append("Baseline or completed-state numerical evidence is unresolved")
        return {"status": "unresolved" if errors else "failed" if violations else "passed",
                "completed_jobs": sorted(state), "scenario_id": scenario["id"],
                "run_id": value["base"]["run_id"], "reference_run_id": reference["base"]["run_id"],
                "total_spill_m3": None if errors else value["base"]["total_spill_m3"],
                "node_comparisons": sorted(nodes, key=lambda x: x["node_id"]),
                "violations": violations, "errors": sorted(set(errors))}


def _policy_selector(method, queue, table, jobs, travel):
    def choose(eligible, done, minute, location):
        candidates = table.get(planning._state_key(done), {})
        allowed = [j for j in eligible if candidates.get(j, {}).get("status") == "passed"]
        if method == "screened_marginal":
            scored = []
            for job in allowed:
                gain = candidates[job]["mean_gain_m3"]
                if gain <= planning._EPS:
                    continue
                minutes = (planning._travel(location, job, travel) + jobs[job]["nominal_minutes"]
                           + planning._travel(job, "DEPOT", travel) - planning._travel(location, "DEPOT", travel))
                scored.append((-gain / minutes, jobs[job]["downstream_rank"], job))
            return min(scored)[2] if scored else None
        return next((j for j in queue if j in allowed), None)
    return choose


def _snapshot_hash(value):
    return fingerprint({k: v for k, v in value.items() if k != "snapshot_sha256"})


def _exportable_observation(value):
    try:
        json.dumps(value, allow_nan=False)
        return deepcopy(value)
    except (ValueError, TypeError, OverflowError):
        # Preserve the invalid input as text, never as invented finite water data.
        return {"invalid_non_json_observation": repr(value)}


def freeze_observed_policy(case, observation, development_scenarios, hydraulic_fn, protocol):
    """Select using the frozen development grid and decision-time observation only.

    Failed candidate states are pruned using their first reproducible rejection
    certificate. Missing candidate evidence never becomes a positive score.
    Every baseline receives the identical observation, screening table and gate.
    """
    validate_protocol(protocol)
    validation = validate_observation(observation, protocol)
    snapshot = {"version": VERSION, "protocol_sha256": protocol["protocol_sha256"],
                "source_sha256": source_fingerprints(), "case_sha256": fingerprint(planning._case_snapshot(case)),
                "observation": _exportable_observation(observation), "observation_validation": validation,
                "status": "supported" if validation["valid"] else "abstained_invalid_observation",
                "policies": {}, "screening_table": {}, "state_screen": {}, "candidate_scores": [],
                "development_scenarios": [], "reasons": list(validation["errors"])}
    if not validation["valid"]:
        for method in METHODS:
            snapshot["policies"][method] = {"queue": [], "kind": "abstention", "reason": "; ".join(validation["errors"])}
        snapshot["policies"]["original_queue_diagnostic"] = {"kind": "historical_diagnostic", "queue": protocol["original_queue_diagnostic"]}
        snapshot["snapshot_sha256"] = _snapshot_hash(snapshot)
        return snapshot
    expected = condition_development(case, observation, protocol)
    scenarios = expected if development_scenarios is None else deepcopy(development_scenarios)
    if fingerprint(scenarios) != fingerprint(expected):
        raise ValueError("Selection ensemble differs from the complete frozen observation-conditioned development grid")
    snapshot["development_scenarios"] = scenarios
    jobs = planning._job_map(case["jobs"])
    evidence = _Evidence(case, hydraulic_fn)
    states, screens = {}, {}

    def screen(state):
        key = planning._state_key(state)
        if key in screens:
            return screens[key]
        rows = []
        # A failing/unresolved state needs only its first rejection certificate.
        # Passing states must resolve every member; no omitted case is averaged.
        for event in scenarios:
            row = evidence.compare(state, event)
            rows.append(row)
            if row["status"] != "passed":
                break
        status = rows[-1]["status"]
        screens[key] = {"status": status, "checked_scenarios": len(rows), "required_scenarios": len(scenarios),
                        "rejection_certificate": rows[-1] if status != "passed" else None}
        if status == "passed":
            states[key] = [r["total_spill_m3"] for r in rows]
        return screens[key]

    baseline = screen(())
    if baseline["status"] != "passed":
        snapshot["status"] = "unresolved"
        snapshot["reasons"].append("No-work numerical evidence is unresolved in the required development grid")
    else:
        # All reachable safe prefixes, independent of the next realised duration.
        for size in range(len(jobs)):
            for subset in combinations(sorted(jobs), size):
                key = planning._state_key(subset)
                if key not in states:
                    continue
                candidates = {}
                for job in sorted(set(jobs) - set(subset)):
                    if not set(jobs[job]["prerequisites"]) <= set(subset):
                        continue
                    after = tuple(sorted((*subset, job)))
                    checked = screen(after)
                    candidate = {"status": checked["status"], "mean_gain_m3": None}
                    if checked["status"] == "passed":
                        before_values, after_values = states[key], states[planning._state_key(after)]
                        candidate["mean_gain_m3"] = sum(a-b for a, b in zip(before_values, after_values)) / len(scenarios)
                    candidates[job] = candidate
                snapshot["screening_table"][key] = candidates

    snapshot["state_screen"] = screens
    snapshot["evidence_pairs_requested"] = len(evidence.cache)
    # Historical queue is exposed only as a diagnostic; it never enters ranking.
    snapshot["policies"] = {
        "no_work": {"kind": "screened_queue", "queue": []},
        "screened_downstream": {"kind": "screened_queue", "queue": sorted(jobs, key=lambda j: (jobs[j]["downstream_rank"], jobs[j]["nominal_minutes"], j))},
        "screened_marginal": {"kind": "screened_marginal", "queue": sorted(jobs)},
        "original_queue_diagnostic": {"kind": "historical_diagnostic", "queue": protocol["original_queue_diagnostic"]},
    }
    if snapshot["status"] != "supported":
        for method in METHODS:
            if method == "original_queue_diagnostic":
                continue
            snapshot["policies"][method] = {"kind": "abstention", "queue": [], "reason": snapshot["reasons"][-1]}
    else:
        nominal_index = next(i for i, event in enumerate(scenarios) if event["id"] == "DEV-NOMINAL-CENTRE")
        for queue in planning.enumerate_queues(jobs):
            selector = _policy_selector("observed_robust", queue, snapshot["screening_table"], jobs, case["travel_minutes"])
            replays = [planning._dispatch(queue, jobs, actual_durations=event["durations"], selector=selector,
                                         **evidence.settings) for event in scenarios]
            supported = all(r["status"] == "supported" for r in replays)
            losses = [states[planning._state_key(r["completed_jobs"])][i] for i, r in enumerate(replays)] if supported else []
            snapshot["candidate_scores"].append({"id": planning._plan_id(queue), "queue": list(queue),
                "admissible": supported, "worst_spill_m3": max(losses) if losses else None,
                "mean_spill_m3": sum(losses)/len(losses) if losses else None,
                "worst_crew_minutes": max(r["crew_minutes"] for r in replays),
                "worst_cost_rm": max(sum(jobs[j]["cost_rm"] for j in r["completed_jobs"]) for r in replays),
                "nominal_spill_m3": losses[nominal_index] if losses else None,
                "nominal_crew_minutes": replays[nominal_index]["crew_minutes"],
                "nominal_cost_rm": sum(jobs[j]["cost_rm"] for j in replays[nominal_index]["completed_jobs"])})
        robust, _, ranking = planning._rank(snapshot["candidate_scores"], case["tie_m3"])
        nominal_scores = []
        for score in snapshot["candidate_scores"]:
            item = deepcopy(score)
            item.update(worst_spill_m3=score["nominal_spill_m3"], mean_spill_m3=score["nominal_spill_m3"],
                        worst_crew_minutes=score["nominal_crew_minutes"], worst_cost_rm=score["nominal_cost_rm"])
            nominal_scores.append(item)
        nominal, _, nominal_ranking = planning._rank(nominal_scores, case["tie_m3"])
        snapshot["ranking_audit"] = {"observed_robust": ranking, "screened_nominal": nominal_ranking}
        for method, choice in (("observed_robust", robust), ("screened_nominal", nominal)):
            snapshot["policies"][method] = {"kind": "screened_queue", "queue": choice["queue"]}
    snapshot["snapshot_sha256"] = _snapshot_hash(snapshot)
    return snapshot


def replay_observed_policy(snapshot, case, evaluation_event, hydraulic_fn, protocol):
    """Replay frozen decisions. No realised forcing or future duration reaches a chooser."""
    validate_protocol(protocol)
    if snapshot["snapshot_sha256"] != _snapshot_hash(snapshot):
        raise ValueError("Frozen policy snapshot was altered")
    if snapshot["source_sha256"] != source_fingerprints() or snapshot["protocol_sha256"] != protocol["protocol_sha256"]:
        raise ValueError("Frozen policy source or protocol changed")
    if snapshot["case_sha256"] != fingerprint(planning._case_snapshot(case)):
        raise ValueError("Frozen hydraulic case changed")
    if evaluation_event.get("phase") != "evaluation":
        raise ValueError("Replay requires an explicitly sealed evaluation event")
    if evaluation_event["id"] in {s["id"] for s in snapshot["development_scenarios"]}:
        raise ValueError("A development case cannot be relabelled as evaluation")
    jobs = planning._job_map(case["jobs"])
    evidence = _Evidence(case, hydraulic_fn)
    results = []
    reference = evidence.compare((), evaluation_event)
    for method in METHODS:
        policy = snapshot["policies"][method]
        diagnostic = method == "original_queue_diagnostic"
        selector = None if diagnostic else _policy_selector(method, policy["queue"], snapshot["screening_table"], jobs, case["travel_minutes"])
        replayed = planning._dispatch(policy["queue"], jobs, actual_durations=evaluation_event.get("durations", {}),
                                     selector=selector, **evidence.settings)
        prefixes, state = [], set()
        for job in replayed["completed_jobs"]:
            state.add(job)
            prefixes.append(evidence.compare(state, evaluation_event))
        if not prefixes:
            prefixes = [deepcopy(reference)]
        reasons = list(replayed["reasons"]) + [e for row in prefixes for e in row["errors"]]
        statuses = {row["status"] for row in prefixes}
        status = ("unresolved" if replayed["status"] != "supported" or "unresolved" in statuses else
                  "inadmissible" if "failed" in statuses else "supported")
        if snapshot["status"] == "unresolved" and not diagnostic:
            status = "unresolved"
            reasons.extend(snapshot["reasons"])
        if snapshot["status"] == "abstained_invalid_observation" and not diagnostic:
            reasons.extend(snapshot["reasons"])
        final = prefixes[-1]
        overrun = any(not event["supported"] for event in replayed["events"])
        results.append({"method": method, "method_label": METHODS[method], "diagnostic_only": diagnostic,
                        "scenario_id": evaluation_event["id"], "observation_id": snapshot["observation"].get("id") if isinstance(snapshot["observation"], dict) else None,
                        "snapshot_sha256": snapshot["snapshot_sha256"], "status": status,
                        "decision_status": "historical_fixed_queue_diagnostic" if diagnostic else snapshot["status"], "queue": policy["queue"],
                        "completed_jobs": replayed["completed_jobs"], "crew_minutes": replayed["crew_minutes"],
                        "abstained": not replayed["events"], "duration_overrun": overrun,
                        "deadline_failure": replayed["finish_minute"] > case["default_deadline_minutes"],
                        "total_spill_m3": None if status == "unresolved" else final["total_spill_m3"],
                        "reference_spill_m3": reference["total_spill_m3"],
                        "node_comparisons": final["node_comparisons"], "prefixes": prefixes,
                        "replay": replayed, "reasons": sorted(set(reasons))})
    return {"event_id": evaluation_event["id"], "results": results, "evidence_pairs_requested": len(evidence.cache)}
