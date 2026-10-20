"""Read-only explanations of three retained synthetic SWMM decisions.

This module reads pinned historical summaries. It neither runs hydraulics nor
revalidates native output files, selects a policy, or authorizes work.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType


SOURCE_SHA256 = MappingProxyType({
    "evidence/planning.json": "fa75ba833aa6928ce162cb1aef1ffe7569244564bf44eef60c52c9583c6f8789",
    "evidence/holdouts.json": "204f7bb9307e5523ed807a94ff6ee59a290eb8ec9a50bf46335a2ed9a26f7d6f",
    "evidence/assurance-development-census.json": "1014785214de59c2b775673df3c6266536629e038e4b45a5f74728fe87e97527",
    "evidence/assurance-census-runs.json": "0b15e83d7f7d3b5d9ecaeb6933e3f675f3e4f02804410b789bb25c8234e3885f",
})


def _one(rows, **identity):
    matches = [row for row in rows if all(row.get(key) == value for key, value in identity.items())]
    if len(matches) != 1:
        raise ValueError(f"Historical record is not unique: {identity}")
    return matches[0]


def _source(path, selector, **identity):
    return {"path": path, "sha256": SOURCE_SHA256[path], "selector": selector, **identity}


def _metric(label, metric_id, scenario_id, location_id, baseline, action, **details):
    return {"label": label, "metric_id": metric_id, "scenario_id": scenario_id,
            "location_id": location_id, "baseline_label": "No additional work",
            "action_label": "Completed work", "baseline_value": baseline,
            "action_value": action, "difference": action - baseline,
            "absolute_difference": abs(action - baseline), "unit": "m3", **details}


def _card(identifier, title, status, scenario_id, queue, completed_jobs, explanation,
          metrics, source_records, screen):
    return {"id": identifier, "title": title, "status": status, "scenario_id": scenario_id,
            "queue": queue, "completed_jobs": completed_jobs, "explanation": explanation,
            "metrics": metrics, "source_records": source_records,
            "full_envelope_status": screen["status"], "full_envelope_counts": dict(screen["counts"]),
            "synthetic": True, "historical": True, "approval_allowed": False,
            "dispatch_allowed": False, "physical_validation_established": False}


def _cards(documents):
    planning_path, holdout_path, census_path, runs_path = SOURCE_SHA256
    planning, holdouts, census, runs = (documents[path] for path in SOURCE_SHA256)

    no_work = _one(planning["plans"], queue=[])
    j4_plan = _one(planning["plans"], queue=["J4"])
    p1_before = _one(no_work["scenario_results"], scenario_id="P1")
    p1_after = _one(j4_plan["scenario_results"], scenario_id="P1")
    j4_screen = _one(census["queues"], queue=["J4"])
    benefit = _card(
        "j4_p1_benefit", "A benefit in one scenario", "scenario_benefit", "P1",
        list(j4_plan["queue"]), list(p1_after["completed_jobs"]),
        "Restoring the storage inlet reduces total modelled spill in P1. This is a supported "
        "historical scenario comparison; the same job fails the broader required screen, so it is not an approved recommendation.",
        [_metric("Total modelled spill", "total_spill_m3", "P1", "network",
                 p1_before["total_spill_m3"], p1_after["total_spill_m3"],
                 completed_jobs=list(p1_after["completed_jobs"]))],
        [_source(planning_path, 'plans[queue=[]].scenario_results[scenario_id="P1"]',
                 run_id=p1_before["run_id"], completed_jobs=[]),
         _source(planning_path, 'plans[queue=["J4"]].scenario_results[scenario_id="P1"]',
                 run_id=p1_after["run_id"], completed_jobs=list(p1_after["completed_jobs"])),
         _source(census_path, 'queues[queue=["J4"]]', audit_sha256=j4_screen["audit_sha256"])],
        j4_screen)
    benefit["scenario_status"] = p1_after["status"]

    h2_before = _one(holdouts["comparisons"], method="no_work", scenario_id="H2")
    h2_after = _one(holdouts["comparisons"], method="robust", scenario_id="H2")
    h2_screen = _one(census["queues"], queue=h2_after["queue"])
    h2_violation = _one(h2_after["protected_violations"], node_id="B2", completed_jobs=["J3", "J4"])
    harm = _card(
        "h2_transfer_harm", "Less total spill, more harm at B2", "protected_harm", "H2",
        list(h2_after["queue"]), list(h2_after["completed_jobs"]),
        "The historical queue completes J4 then J3 in H2. Total modelled spill falls, but B2 spill "
        "increases beyond the protected-location tolerance. A lower total does not make this action admissible.",
        [_metric("Total modelled spill", "total_spill_m3", "H2", "network",
                 h2_before["total_spill_m3"], h2_after["total_spill_m3"],
                 completed_jobs=list(h2_after["completed_jobs"])),
         _metric("Protected B2 spill", "spill_m3", "H2", "B2",
                 h2_before["nodes"]["B2"]["spill_m3"], h2_after["nodes"]["B2"]["spill_m3"],
                 completed_jobs=list(h2_after["completed_jobs"]), tolerance_value=h2_violation["tolerance_m3"])],
        [_source(holdout_path, 'comparisons[method="no_work",scenario_id="H2"]',
                 run_id=h2_before["run_id"], completed_jobs=[]),
         _source(holdout_path, 'comparisons[method="robust",scenario_id="H2"]',
                 run_id=h2_after["run_id"], completed_jobs=list(h2_after["completed_jobs"])),
         _source(census_path, 'queues[queue=["J4","J1","J3","J2"]]',
                 audit_sha256=h2_screen["audit_sha256"])], h2_screen)
    harm["scenario_status"] = h2_after["status"]
    harm["completed_order"] = list(h2_after["newly_completed_jobs"])

    queue_screen = _one(census["queues"], queue=["J2", "J1"])
    stage_case = _one(queue_screen["cases"], scenario_id="S_STAGE")
    stage_run = _one(runs.values(), scenario_id="S_STAGE", completed_jobs=["J1", "J2"])
    numerics = stage_run["raw"]["assurance_numerics"]
    default = _one(numerics["runs"], configuration="default")
    half = _one(numerics["runs"], configuration="half step")
    h1_case = _one(queue_screen["cases"], scenario_id="H1")
    h1_harm = _one(h1_case["violations"], node_id="B2", completed_jobs=["J2"])
    uncertainty = _card(
        "j2_j1_uncertainty", "Numerical uncertainty is a separate reason to stop", "numerically_unresolved", "S_STAGE",
        list(queue_screen["queue"]), list(stage_run["completed_jobs"]),
        "For J2 then J1 in S_STAGE, T spill changes too much when the routing step is halved. "
        "These are diagnostic values, not a trusted benefit score. Separately, the same queue has a resolved "
        "H1 failure at its J2-only stopping state. Fixing the numerical discrepancy would not remove that harm.",
        [_metric("T spill: routing-step check", "spill_m3", "S_STAGE", "T",
                 default["nodes"]["T"]["spill_m3"], half["nodes"]["T"]["spill_m3"],
                 baseline_label=f'{numerics["routing_step_s"]:g} s routing step',
                 action_label=f'{numerics["half_step_s"]:g} s routing step',
                 comparison="routing_step_halving", diagnostic_only=True,
                 completed_jobs=list(stage_run["completed_jobs"]),
                 tolerance_value=numerics["per_node_deltas"]["T"]["tolerance_m3"]),
         _metric("Separate H1 stopping state: B2 spill after J2 only", "spill_m3", "H1", "B2",
                 h1_harm["reference_spill_m3"], h1_harm["spill_m3"],
                 completed_jobs=list(h1_harm["completed_jobs"]), tolerance_value=h1_harm["tolerance_m3"])],
        [_source(census_path, 'queues[queue=["J2","J1"]].cases[scenario_id="S_STAGE"]',
                 audit_sha256=queue_screen["audit_sha256"]),
         _source(runs_path, 'values[scenario_id="S_STAGE",completed_jobs=["J1","J2"]].raw.assurance_numerics',
                 run_ids={"default": default["run_id"], "half_step": half["run_id"]},
                 scenario_sha256=stage_run["scenario_sha256"], completed_jobs=list(stage_run["completed_jobs"])),
         _source(census_path, 'queues[queue=["J2","J1"]].cases[scenario_id="H1"].violations[node_id="B2"]',
                 run_id=h1_harm["run_id"], reference_run_id=h1_harm["reference_run_id"],
                 completed_jobs=list(h1_harm["completed_jobs"]))], queue_screen)
    uncertainty.update(scenario_status=stage_case["status"], reasons=list(stage_case["reasons"]),
                       benefit_score_m3=None, numerical_check_status=numerics["status"])
    return [benefit, harm, uncertainty]


def load_decision_review(project_root=None):
    """Return all three cards only when every pinned historical source matches.

    ``status='verified'`` means source bytes match this module's historical
    snapshot, not that an intervention or hydraulic result is approved. Files
    are reread each call; altered or missing evidence never uses a stale card.
    """
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    result = {"schema_version": "monsoon.decision-review/1", "status": "unavailable",
              "synthetic": True, "historical": True, "approval_allowed": False,
              "dispatch_allowed": False, "physical_validation_established": False,
              "integrity_scope": "Pinned historical JSON records only; native run files are not revalidated here.",
              "sources": [], "cards": [], "errors": []}
    documents = {}
    for relative, expected in SOURCE_SHA256.items():
        source = {"path": relative, "sha256": expected, "verified": False}
        result["sources"].append(source)
        try:
            data = (root / relative).read_bytes()
            source["actual_sha256"] = sha256(data).hexdigest()
            if source["actual_sha256"] != expected:
                raise ValueError("saved source checksum differs")
            documents[relative] = json.loads(data)
            source["verified"] = True
        except (OSError, ValueError, UnicodeError) as exc:
            result["errors"].append(f"{relative}: {exc}")
    if result["errors"]:
        return result
    try:
        result["cards"] = _cards(documents)
    except (KeyError, TypeError, ValueError) as exc:
        result["errors"].append(f"Historical decision identity could not be read: {exc}")
        return result
    result["status"] = "verified"
    return result
