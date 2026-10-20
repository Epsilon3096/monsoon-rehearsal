"""Reproduce scientific comparisons and assurance gates without changing app data."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from monsoon import __version__
from monsoon.hydraulics import engine_info, run_state, verify_hydraulics, verify_hydraulic_horizon
from monsoon.planning import evaluate_holdouts
from monsoon.service import ROOT, audit_selected_plan, initialise, plan_snapshot, rehearse
from monsoon.tickets import WorkflowError


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def test_summary(path):
    if not path.exists():
        return {"status": "not_run", "reason": f"Run pytest with --junitxml={path} first."}
    root = ET.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    fields = {key: sum(int(s.get(key, "0")) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
    return {"status": "passed" if fields["failures"] == fields["errors"] == fields["skipped"] == 0 and fields["tests"] > 0 else "failed",
            **fields, "report": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def blocked_audit_roundtrip(case, store, episode, root):
    """Keep the real selected plan's unfavorable result durable and enforce it."""
    chosen = episode["recommended"]
    if chosen is None or not chosen["queue"]:
        raise AssertionError("The frozen reference must yield an actionable planning-grid candidate")
    audit = audit_selected_plan(case, episode, chosen, store, root)
    saved = store.save_plan(case["id"], plan_snapshot(case, episode, chosen, audit), "Verification planner")
    assert audit["status"] == "failed" and audit["counts"]["failed"] > 0, "The known adverse development evidence must remain explicit"
    assert saved["assurance_gate"]["valid"], "The saved failure must be intact evidence, not an invalid audit masquerading as a tested refusal"
    assert not saved["assurance_gate"]["approval_allowed"], "The known development-stress failure must block the default plan"
    before = store.events(case["id"])
    blocked = False
    try:
        store.review(saved["id"], "Verification reviewer", "A known failure cannot be waived by review notes.")
    except WorkflowError:
        blocked = True
    assert blocked and store.get_plan(saved["id"])["status"] == "draft"
    assert store.events(case["id"]) == before
    assert not store.list_tickets(case["id"])
    return {"status": "passed", "audit_status": audit["status"], "audit_counts": audit["counts"], "plan_id": saved["id"],
            "snapshot_hash": saved["snapshot_hash"], "review_refused": True,
            "approval_allowed": False, "gate_reasons": saved["assurance_gate"]["reasons"],
            "scope": "Actual SWMM development-stress audit of the frozen reference candidate; no work authorized."}, store.export_manifest(case["id"]), audit


def workflow_roundtrip(case, store, episode, root):
    """A real passing no-additional-work audit cannot authorize any job.

    Nonempty reference queues must not borrow this approval. The full actual-work
    state machine is exercised separately by explicitly arithmetic test fixtures;
    this verification command neither imports them nor represents them as SWMM.
    """
    chosen = next(plan for plan in episode["plans"] if not plan["queue"])
    audit = audit_selected_plan(case, episode, chosen, store, root)
    plan = store.save_plan(case["id"], plan_snapshot(case, episode, chosen, audit), "Verification planner")
    assert plan["assurance_gate"]["approval_allowed"], "The no-additional-work policy must pass its complete real audit"
    store.review(plan["id"], "Verification reviewer", "No additional work; review of finite synthetic development envelope only.")
    approved = store.approve(plan["id"], "Verification supervisor", "This empty queue authorizes no job.")
    assert approved["approval"]["snapshot_hash"] == plan["snapshot_hash"]
    before = store.events(case["id"])
    blocked = False
    try:
        store.create_ticket(plan["id"], case["jobs"][0]["id"], "Verification dispatcher")
    except WorkflowError:
        blocked = True
    assert blocked, "A no-work approval must never create a work ticket"
    assert store.events(case["id"]) == before and not store.list_tickets(case["id"])
    return {"status": "passed", "kind": "real_no_additional_work_gate", "plan_id": plan["id"],
            "audit_status": audit["status"], "snapshot_hash": plan["snapshot_hash"],
            "queue": [], "approval_allowed": True, "job_ticket_refused": True,
            "scope": "Real SWMM evidence; reviewed and approved only the empty queue. No work or physical observation is asserted."}, store.export_manifest(case["id"]), audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "var" / "reproduction")
    parser.add_argument("--cache", type=Path, default=ROOT / "var" / "hydraulic_runs")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    # Common raw runs are content-addressed; workflow observations live in a
    # separate persistent verification folder, never the interactive database.
    import os
    os.environ["MONSOON_CACHE_DIR"] = str(args.cache.resolve())
    verification_root = ROOT / "var"
    verification_root.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="verification-", dir=verification_root))
    print("Verifying every physical state and scenario at two routing steps...", flush=True)
    hydraulics = verify_hydraulics(args.cache, all_states=True, workers=args.workers)
    write_json(args.output / "hydraulics.json", hydraulics)
    print(f'Hydraulics: {hydraulics["status"]}, {hydraulics["state_scenario_pairs"]} state/scenario pairs.', flush=True)
    horizon = verify_hydraulic_horizon(args.cache, all_states=True, workers=args.workers)
    write_json(args.output / "horizon.json", horizon)
    print(f'Horizon adequacy: {horizon["status"]}; diagnostic sensitivities retained.', flush=True)
    case, store = initialise(root)
    try:
        scenarios = [s for s in case["scenarios"] if s["phase"] == "planning"]
        episode = rehearse(case, scenarios, case["default_deadline_minutes"], store, root)
        write_json(args.output / "planning.json", episode)
        holdouts = evaluate_holdouts(episode, case, [s for s in case["scenarios"] if s["phase"] == "holdout"],
                                    lambda completed, scenario: run_state(completed, scenario, args.cache))
        write_json(args.output / "holdouts.json", holdouts)
        blocked_workflow, blocked_manifest, blocked_audit = blocked_audit_roundtrip(case, store, episode, root)
        write_json(args.output / "selected-plan-audit.json", blocked_audit)
        write_json(args.output / "workflow-blocked.json", blocked_manifest)
        workflow, manifest, no_work_audit = workflow_roundtrip(case, store, episode, root)
        write_json(args.output / "workflow.json", manifest)
        write_json(args.output / "no-work-audit.json", no_work_audit)
    finally:
        store.disconnect()
    columns = ["phase", "method", "scenario_id", "status", "total_spill_m3", "crew_minutes", "completed_jobs"]
    with (args.output / "baseline-comparisons.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for phase, data in [("planning", episode), ("holdout", holdouts)]:
            for row in data["comparisons"]:
                item = {k: row.get(k) for k in columns}
                item.update(phase=phase, completed_jobs=";".join(row.get("completed_jobs", [])))
                writer.writerow(item)
    robust = {r["scenario_id"]: r for r in episode["comparisons"] if r["method"] == "robust"}
    marginal = {r["scenario_id"]: r for r in episode["comparisons"] if r["method"] == "marginal_benefit"}
    ties = all(abs(robust[s]["total_spill_m3"] - marginal[s]["total_spill_m3"]) < 1e-8 for s in robust)
    failed_holdouts = [{"method": r["method"], "scenario_id": r["scenario_id"], "status": r["status"], "reasons": r.get("reasons", [])}
                       for r in holdouts["comparisons"] if r["status"] != "supported"]
    continuity = max(abs(row[key]) for row in hydraulics["rows"] for key in ["continuity_error_percent", "half_step_continuity_error_percent"] if row[key] is not None)
    distinct_hydraulic_runs = len({row[key] for row in hydraulics["rows"] for key in ["run_id", "half_step_run_id"]})
    tests = test_summary(args.output / "pytest.xml")
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "status": "passed" if hydraulics["status"] == horizon["status"] == blocked_workflow["status"] == workflow["status"] == tests["status"] == "passed" else "incomplete_or_failed",
               "scope": "Numerical/software verification of synthetic prototype; no field or bench validation",
               "engine": engine_info(), "case_sha256": case["case_sha256"],
               "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted((ROOT / "monsoon").glob("*.py")) + [ROOT / "app.py"]},
               "tests": tests,
               "hydraulics": {k: hydraulics[k] for k in ["status", "state_scenario_pairs", "engine_runs", "routing_step_s", "halved_routing_step_s"]},
               "maximum_absolute_continuity_error_percent": continuity,
               "hydraulic_evaluation_count_note": "engine_runs counts requested evaluations, including cache reuse and equivalent pre-restored diagnostic states; it is not a fresh-subprocess or independent-replicate count.",
               "distinct_step_verification_run_ids": distinct_hydraulic_runs,
               "horizon": {k: horizon[k] for k in ["status", "state_scenario_pairs", "horizon_minutes", "extended_horizon_minutes", "horizon_sensitive_diagnostics"]},
               "planning": {"counts": episode["counts"], "priority_queue": episode["recommended"]["queue"],
                            "worst_spill_m3": episode["recommended"]["worst_spill_m3"],
                            "ties_adaptive_marginal_baseline_on_all_planning_scenarios": ties,
                            "frozen_fingerprint": episode["frozen_fingerprint"]},
               "holdout_failures": failed_holdouts, "selected_plan_gate": blocked_workflow, "workflow": workflow,
               "actual_work_loop_evidence": "Current approval-through-closeout and observed-state replanning are tested only with explicit arithmetic fixtures in pytest. Original v0.1 evidence is retained separately; its plan approvals do not establish a v0.2 stress pass.",
               "limits": ["Node spill at the model boundary is not mapped property inundation.",
                          "The robust policy has no demonstrated advantage over the adaptive marginal baseline in this case.",
                          "H2 fails the per-location screen for robust and marginal policies; no field deployment conclusion follows.",
                          "Downstream-first is an explicit topology heuristic and still needs operator review.",
                          "One crew, dry pre-event work, verified binary restoration, uniform travel, and finite scenarios only."]}
    write_json(args.output / "verification.json", summary)
    lines = [f"# Monsoon Rehearsal v{__version__} — original model and plan assurance regression verification", "", f'Generated {summary["created_utc"]}.', "",
             "This records software and numerical verification on a frozen synthetic catchment. No physical rig, site survey, field inspection, forecast connection, or measured flood-risk reduction is represented.", "",
             "## Executed checks", "",
             f'- Automated tests: **{tests.get("tests", 0)}**; failures **{tests.get("failures", "not run")}**; errors **{tests.get("errors", "not run")}**; skipped **{tests.get("skipped", "not run")}**.',
             f'- EPA SWMM {summary["engine"]["engine_version"]}: **{hydraulics["state_scenario_pairs"]}** state/scenario pairs, **{hydraulics["engine_runs"]}** requested evaluations at **0.5 and 0.25 seconds**, representing **{distinct_hydraulic_runs}** distinct run identities. Equivalent pre-restored diagnostic states and cached results reuse evidence; these are not independent replicates.',
             f'- Maximum absolute routing continuity error across both steps: **{continuity:.6f}%**.',
             '- Step-halving spill tolerance: max(0.05 m³, 2% of the larger magnitude), per protected node and total.',
             f'- Horizon check: **{horizon["status"]}** for event adequacy at 180 vs 360 minutes. Full per-state diagnostics are in `horizon.json`; D1 remains sensitive to the imposed-stage cold-start transient and is not claimed as a complete-event total.',
             '- The initial 1-second step failed the declared convergence tolerance in a high-tailwater diagnostic. Refining the numerical step globally to 0.5 seconds resolved it; geometry, forcing, policy, and tolerance were not tuned to the ranking.',
             f'- Real selected-plan stress audit: **{blocked_workflow["audit_status"]}**. Its blocked draft is durable, review is refused, and no ticket is issued: **{blocked_workflow["status"]}**.',
             f'- Real no-additional-work audit: **{workflow["audit_status"]}**. Review and approval refer only to its empty queue; an attempt to issue a job ticket is refused: **{workflow["status"]}**.',
             '- Full approval → ticket → assignment → start → report → verification → close → observed-state replan is covered by explicitly labelled arithmetic software fixtures in the automated tests. Those metrics and inspections are not real SWMM or field evidence.',
             '- Verification uses an isolated database; the interactive workspace is not altered. The original v0.1 evidence remains historical and is not upgraded into a passing v0.2 audit.', "",
             "## Planning result and limits", "",
             f'The exact search evaluated {episode["counts"]["enumerated_queues"]} priority queues across four planning scenarios: {episode["counts"]["supported_plans"]} supported, {episode["counts"]["inadmissible_plans"]} inadmissible, {episode["counts"]["unresolved_plans"]} unresolved.', "",
             f'The selected priority queue is **{" → ".join(episode["recommended"]["queue"])}**, with worst-scenario modeled node spill **{episode["recommended"]["worst_spill_m3"]:.6f} m³**. A priority queue is scanned for the next eligible fitting job; it is not a promise to finish all jobs.', "",
             '**The adaptive marginal baseline ties the robust queue in every planning scenario. This case does not establish an optimisation advantage over that strong baseline.**', "",
             "## Previously revealed frozen-policy holdouts", "", "| Method | Scenario | Status | Node spill (m³) | Completed jobs |", "|---|---|---|---:|---|"]
    for r in holdouts["comparisons"]:
        spill = f'{r["total_spill_m3"]:.6f}' if r.get("total_spill_m3") is not None else "unresolved"
        lines.append(f'| {r["method"]} | {r["scenario_id"]} | {r["status"]} | {spill} | {", ".join(r.get("completed_jobs", [])) or "none"} |')
    lines += ["", "**H2 makes the robust and adaptive marginal policies inadmissible under the location-level screen.** A smaller total spill cannot override worsening at a protected node. The result is retained without retuning. Every completed prefix is screened, so a plan with a harmless final state may still fail because of an earlier achieved state.", "",
              "The hindsight oracle is separately labelled and is never an operational competitor. These are prespecified within-network synthetic holdouts, now revealed, not an independent field trial. v0.2 explicitly includes H1/H2 with the declared stress cases as development evidence; a software-verification pass must not be read as approval of a candidate that fails those cases.", "",
              "## Evidence", "", "`verification.json` pins source and model hashes. `hydraulics.json` lists every original state/scenario comparison. `planning.json` contains all queues, rejections, baselines and frozen policies. `holdouts.json` preserves every revealed outcome and oracle. `baseline-comparisons.csv` is the compact comparison table. `selected-plan-audit.json` retains the real candidate's failures; `workflow-blocked.json` proves its refusal. `no-work-audit.json` retains the passing empty-queue audit. `workflow.json` contains both immutable plans and their events, with no work ticket or physical observation. `pytest.xml` records the separate arithmetic workflow exercises and the remaining automated tests.", "",
              "Raw SWMM inputs, reports, binary outputs, manifests and logs remain under `var/hydraulic_runs/` on the machine that ran verification. Absolute cache paths are machine-local and can be regenerated. The source archive includes the compact evidence, not the entire raw cache.", "",
              "## Still required before real-world use", "", "Surveyed geometry and initial conditions; site calibration; bench/field intervention validation; operator-reviewed baseline; travel and duration data; real forecast integration and calibration; production dispatch authentication and authorisation; additional catchments and independent holdouts. Dynamic wet-work transition modelling is required only if that scope is added; the MVP retains verified pre-event states. v0.3 research records have local authenticated roles, but the legacy demonstration ticket workflow remains separate. No first-prize or field-safety guarantee is made.", ""]
    (args.output / "VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "counts": episode["counts"], "workflow": workflow["status"], "evidence": str(args.output)}, indent=2), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
