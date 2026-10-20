"""Application orchestration. Scientific calculations remain in domain modules."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from monsoon import __version__
from monsoon.case import load_case
from monsoon.assurance import assurance_requirement, audit_plan
from monsoon.assurance_hydraulics import checked_state
from monsoon.hydraulics import engine_info, run_state
from monsoon.planning import evaluate_episode
from monsoon.tickets import TicketStore, WorkflowError

ROOT = Path(__file__).resolve().parents[1]


def data_root() -> Path:
    path = Path(os.environ.get("MONSOON_DATA_DIR", ROOT / "var")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def implementation_hash() -> str:
    files = sorted((ROOT / "monsoon").glob("*.py")) + [ROOT / "data" / "assurance_protocol.json"]
    return canonical_hash({p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in files})


def runtime_identity() -> str:
    return canonical_hash({"case": load_case(), "engine": engine_info(), "implementation": implementation_hash()})


def initialise(root: Path | None = None):
    root = root or data_root()
    root.mkdir(parents=True, exist_ok=True)
    case = load_case()
    store = TicketStore(root / "workflow.sqlite3")
    identity = runtime_identity()
    try:
        existing = store.project_state(case["id"])
    except WorkflowError:
        existing = None
    if existing and existing["unresolved_jobs"]:
        # Preserve the definitions under which actual work began until its
        # observations have been resolved. Runtime changes still stale approvals.
        if existing["jobs"] != case["jobs"]:
            case = dict(case, jobs=existing["jobs"], runtime_warning="Model job definitions changed while work was active. Resolve the original ticket before adopting the new definitions.")
    else:
        try:
            store.ensure_project(case["id"], case["jobs"], actor="Prototype")
        except WorkflowError:
            if not existing or not existing["completed_jobs"] or existing["jobs"] == case["jobs"]:
                store.disconnect()
                raise
            message = "Current job definitions differ from accepted physical history. Historical tickets remain accessible; a separately reviewed model state is required before further planning."
            case = dict(case, jobs=existing["jobs"], runtime_warning=message, planning_blocked_reason=message)
    store.set_runtime_identity(case["id"], identity, actor="Prototype")
    return case, store


def hydraulic_cache(root: Path | None = None) -> Path:
    return Path(os.environ.get("MONSOON_CACHE_DIR", (root or data_root()) / "hydraulic_runs")).resolve()


def context(case: dict, scenarios: list[dict], deadline: float, state: dict) -> dict:
    if case.get("planning_blocked_reason"):
        raise ValueError(case["planning_blocked_reason"])
    if not scenarios or any(s["phase"] != "planning" for s in scenarios):
        raise ValueError("Select at least one planning scenario. Holdouts cannot select a plan.")
    nominal = case.get("nominal_scenario_id")
    if nominal and nominal not in {s["id"] for s in scenarios}:
        raise ValueError(f"Include {nominal}, the declared nominal scenario used by the deterministic comparison.")
    if state.get("unresolved_jobs") or state.get("condition_unknown"):
        raise ValueError("Unverified asset condition must be resolved before another supported plan.")
    if not 0 < deadline <= 1440:
        raise ValueError("Work deadline must be between 1 and 1,440 minutes after shift start.")
    public_case = {k: v for k, v in case.items() if k != "scenarios"}
    return deepcopy({"case": public_case, "scenarios": scenarios, "deadline_minutes": deadline,
            "already_completed": sorted(state["completed_jobs"]),
            "start_minute": state["elapsed_minutes"], "start_location": state["crew_location"],
            "app_version": __version__, "implementation_hash": implementation_hash(), "engine": engine_info(),
            "assurance_requirement": assurance_requirement()})


def rehearse(case: dict, scenarios: list[dict], deadline: float, store: TicketStore,
             root: Path | None = None, operator_queue: list[str] | None = None,
             progress: Callable | None = None) -> dict:
    root = root or data_root()
    captured_runtime = runtime_identity()
    case, scenarios, operator_queue = deepcopy(case), deepcopy(scenarios), deepcopy(operator_queue)
    if canonical_hash(case) != canonical_hash(load_case()):
        raise ValueError("The supplied model differs from the current model. Reload and rehearse again.")
    state = store.project_state(case["id"])
    inputs = context(case, scenarios, deadline, state)
    # A user-entered comparison is decision-time information and belongs in provenance.
    inputs["operator_queue"] = operator_queue
    fingerprint = canonical_hash(inputs)
    captured = store.set_context(case["id"], fingerprint, inputs, actor="Planner", expected_version=state["version"])
    captured_version = captured["version"]
    cache = hydraulic_cache(root)
    runs = {}

    def hydraulic(completed, scenario):
        result = run_state(completed, scenario, cache)
        runs[result.get("run_id") or f'invalid:{scenario["id"]}:{",".join(sorted(completed))}'] = result
        if progress:
            progress(len(runs), result)
        return result

    # Do not expose sealed holdout members through the case object to the selector.
    planning_case = dict(case, scenarios=scenarios)
    result = evaluate_episode(planning_case, scenarios, hydraulic,
                              deadline_minutes=deadline, already_completed=state["completed_jobs"],
                              start_minute=state["elapsed_minutes"], start_location=state["crew_location"],
                              operator_queue=operator_queue)
    current = store.project_state(case["id"])
    if current["version"] != captured_version or current["context_fingerprint"] != fingerprint:
        raise ValueError("Inputs or observed work changed during calculation. Run a new rehearsal.")
    if runtime_identity() != captured_runtime:
        raise ValueError("Model, calculation code, engine or audit protocol changed during rehearsal. Restart and rehearse again.")
    if canonical_hash(inputs) != fingerprint:
        raise ValueError("Decision inputs changed during calculation. Run a fresh rehearsal.")
    result.update(context_fingerprint=fingerprint, inputs=inputs, hydraulic_run_ids=sorted(k for k in runs if not k.startswith("invalid:")),
                  state_version=captured_version)
    episode_dir = root / "episodes"
    episode_dir.mkdir(exist_ok=True)
    path = episode_dir / f"{fingerprint}.json"
    path.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    result["episode_file"] = str(path)
    return result


def plan_snapshot(case: dict, episode: dict, plan: dict, assurance: dict | None = None) -> dict:
    if not plan.get("admissible"):
        raise ValueError("Only a fully evaluated admissible plan can be reviewed.")
    return {**plan, "queue": list(plan["queue"]), "jobs": case["jobs"],
            "deadline_minutes": episode["inputs"]["deadline_minutes"],
            "travel_minutes": case.get("travel_minutes", 10),
            "supported": True, "admissible": True,
            "context_fingerprint": episode["context_fingerprint"],
            "state_version": episode["state_version"],
            "model_version": case["model_version"], "evidence_status": "synthetic",
            "episode_file": episode.get("episode_file"), "provenance": episode["inputs"],
            "hydraulic_run_ids": episode["hydraulic_run_ids"],
            "decision_manifest": episode["decision_manifest"], "frozen_fingerprint": episode["frozen_fingerprint"],
            "assurance_requirement": episode["inputs"]["assurance_requirement"],
            "assurance": assurance}


def audit_selected_plan(case, episode, plan, store, root=None, progress=None):
    """Audit a frozen choice; the stress outcomes never enter its selection."""
    root = root or data_root()
    captured_runtime = runtime_identity()
    case, episode, plan = deepcopy(case), deepcopy(episode), deepcopy(plan)
    if canonical_hash(case) != canonical_hash(load_case()):
        raise ValueError("The supplied model differs from the current model. Reload and rehearse again.")
    state = store.project_state(case["id"])
    if state["version"] != episode["state_version"] or state["context_fingerprint"] != episode["context_fingerprint"]:
        raise ValueError("Rehearse current inputs before auditing this plan.")
    current_inputs = context(case, episode["inputs"]["scenarios"], episode["inputs"]["deadline_minutes"], state)
    current_inputs["operator_queue"] = episode["inputs"].get("operator_queue")
    if canonical_hash(current_inputs) != episode["context_fingerprint"]:
        raise ValueError("The calculation or observed state changed. Run a fresh rehearsal.")
    matching = next((p for p in episode["plans"] if p["id"] == plan.get("id")), None)
    if matching is None or canonical_hash(matching) != canonical_hash(plan):
        raise ValueError("Selected plan does not match its frozen rehearsal.")
    runs = {}
    def hydraulic(completed, scenario):
        key = (tuple(sorted(completed)), canonical_hash(scenario))
        if key not in runs:
            runs[key] = checked_state(completed, scenario, hydraulic_cache(root))
            if progress:
                progress(len(runs), runs[key])
        return runs[key]
    report = audit_plan(case, episode, plan, hydraulic, hydraulic_identity=episode["inputs"]["engine"])
    current = store.project_state(case["id"])
    if runtime_identity() != captured_runtime or current["version"] != state["version"] or current["context_fingerprint"] != state["context_fingerprint"]:
        raise ValueError("Inputs or observed work changed during the stress audit. Rehearse and audit again.")
    directory = root / "audits"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{canonical_hash(report)}.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report


def find_run(run_id: str, root: Path | None = None) -> dict | None:
    base = hydraulic_cache(root)
    # The hydraulic module owns run directory details; search only its bounded cache.
    for path in base.glob(f"{run_id}*/result.json"):
        return json.loads(path.read_text(encoding="utf-8"))
    for path in base.glob(f"{run_id}*/manifest.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "total_spill_m3" in data:
            return data
    return None
