"""Durable, evidence-gated, single-crew workflow for the research prototype.

Named actors are an audit label, not authentication. All time values are minutes
after shift start, rather than wall-clock datetimes. Immutable plan snapshots and
append-only events make the approved calculation recoverable after replanning.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4


class WorkflowError(ValueError):
    """A requested workflow action is unsupported or inconsistent."""


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Values must be finite, JSON-serialisable data.") from exc


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{label} must be non-empty text.")
    return value.strip()


def _minute(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkflowError(f"{label} must be a finite non-negative number of minutes.")
    if not math.isfinite(value) or value < 0:
        raise WorkflowError(f"{label} must be a finite non-negative number of minutes.")
    return float(value)


def _evidence(value):
    if isinstance(value, str):
        value = _text(value, "Evidence")
    elif not isinstance(value, dict) or not value:
        raise WorkflowError("Evidence must be non-empty text or a non-empty evidence object.")
    _json(value)
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _assurance_gate(snapshot):
    """Describe dispatch eligibility without rerunning the hydraulic evaluator.

    The shared assurance validator owns the frozen protocol, evidence checks and
    audited-subject hash. A label such as ``status='passed'`` is never sufficient.
    Legacy snapshots predate this opt-in contract and remain explicitly labelled
    as such, rather than being presented as having passed a later audit.
    """
    required = "assurance_requirement" in snapshot or "assurance" in snapshot
    if not required:
        return {"required": False, "valid": True, "approval_allowed": True,
                "status": "legacy_not_required", "reasons": []}
    try:
        from monsoon.assurance import validate_audit
        result = validate_audit(snapshot)
        if not isinstance(result, dict):
            raise ValueError("Assurance validator returned an unsupported result.")
        reasons = result.get("reasons")
        if not isinstance(reasons, list) or any(not isinstance(x, str) for x in reasons):
            raise ValueError("Assurance validator omitted its validation reasons.")
        result = dict(result, required=True, valid=result.get("valid") is True,
                      status=result.get("status") if isinstance(result.get("status"), str) else "invalid")
        result["approval_allowed"] = (result.get("valid") is True
                                      and result.get("approval_allowed") is True
                                      and result.get("status") == "passed"
                                      and not reasons)
        if not result["approval_allowed"] and not reasons:
            result["reasons"] = ["The required assurance audit has not passed."]
        return result
    except Exception as exc:
        # Historical work must remain readable/reportable if the audit cannot be
        # interpreted by the current runtime. Future dispatch still fails closed.
        return {"required": True, "valid": False, "approval_allowed": False,
                "status": "invalid", "reasons": [f"Assurance validation failed: {exc}"]}


class TicketStore:
    SCHEMA_VERSION = 2

    def __init__(self, db_path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=30000")
        self._db.execute("PRAGMA journal_mode=WAL")
        existing = self._db.execute("PRAGMA user_version").fetchone()[0]
        # Version 2 adds runtime identity without rewriting version 1 history.
        if existing not in (0, 1, self.SCHEMA_VERSION):
            self._db.close()
            raise WorkflowError(f"Unsupported database schema version {existing}.")
        self._db.executescript("""
          CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, version INTEGER NOT NULL, jobs_json TEXT NOT NULL,
            fingerprint TEXT, inputs_json TEXT NOT NULL DEFAULT '{}',
            completed_json TEXT NOT NULL DEFAULT '[]', elapsed REAL NOT NULL DEFAULT 0,
            location TEXT NOT NULL DEFAULT 'DEPOT', crew TEXT);
          CREATE TABLE IF NOT EXISTS runtime_identities (
            project_id TEXT PRIMARY KEY REFERENCES projects(id),
            identity TEXT NOT NULL, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS plans (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
            snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
            state_version INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL, created_by TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reviews (
            plan_id TEXT PRIMARY KEY REFERENCES plans(id), actor TEXT NOT NULL,
            notes TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS approvals (
            plan_id TEXT PRIMARY KEY REFERENCES plans(id), actor TEXT NOT NULL,
            notes TEXT NOT NULL, snapshot_hash TEXT NOT NULL, created_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tickets (
            id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id),
            project_id TEXT NOT NULL REFERENCES projects(id), job_id TEXT NOT NULL,
            status TEXT NOT NULL, crew TEXT, start_minute REAL, finish_minute REAL,
            report_evidence_json TEXT, verification_evidence_json TEXT,
            observed_condition TEXT, created_at TEXT NOT NULL, created_by TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, schema_version INTEGER NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(id), entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
            created_at TEXT NOT NULL, payload_json TEXT NOT NULL);
          CREATE TRIGGER IF NOT EXISTS immutable_plan_snapshot
          BEFORE UPDATE OF snapshot_json,snapshot_hash,state_version,fingerprint,project_id,created_at,created_by
          ON plans BEGIN SELECT RAISE(ABORT,'Plan snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_plan_identity BEFORE UPDATE OF id ON plans
          BEGIN SELECT RAISE(ABORT,'Plan identities are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_plan_delete BEFORE DELETE ON plans
          BEGIN SELECT RAISE(ABORT,'Plan snapshots are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT,'Audit events are append-only'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_review_update BEFORE UPDATE ON reviews
          BEGIN SELECT RAISE(ABORT,'Reviews are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_review_delete BEFORE DELETE ON reviews
          BEGIN SELECT RAISE(ABORT,'Reviews are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_approval_update BEFORE UPDATE ON approvals
          BEGIN SELECT RAISE(ABORT,'Approvals are immutable'); END;
          CREATE TRIGGER IF NOT EXISTS immutable_approval_delete BEFORE DELETE ON approvals
          BEGIN SELECT RAISE(ABORT,'Approvals are immutable'); END;
        """)
        self._db.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    def disconnect(self):
        """Close the database connection; ``close`` closes a work ticket."""
        with self._lock:
            self._db.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    @contextmanager
    def _read_snapshot(self):
        """Read one database revision, reusing any enclosing transaction.

        A connection-local lock alone cannot exclude another connection's commit
        between SELECTs. Deferred read transactions preserve a coherent WAL
        snapshot while allowing independent observations to be committed.
        """
        with self._lock:
            owns_transaction = not self._db.in_transaction
            if owns_transaction:
                self._db.execute("BEGIN")
            try:
                yield
                if owns_transaction:
                    self._db.execute("COMMIT")
            except Exception:
                if owns_transaction:
                    self._db.execute("ROLLBACK")
                raise

    def _event(self, project, kind, entity, action, actor, payload=None):
        self._db.execute("INSERT INTO events(schema_version,project_id,entity_type,entity_id,action,actor,created_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                         (self.SCHEMA_VERSION, project, kind, entity, action, actor, _now(), _json(payload or {})))

    def _row(self, table, identifier):
        # table names only come from internal constants, never caller input.
        result = self._db.execute(f"SELECT * FROM {table} WHERE id=?", (identifier,)).fetchone()
        if result is None:
            raise WorkflowError(f"Unknown {table[:-1]}: {identifier}")
        return dict(result)

    def _unresolved(self, case_id):
        return [r[0] for r in self._db.execute(
            "SELECT job_id FROM tickets WHERE project_id=? AND status IN ('in_progress','completion_reported','revision_needed') ORDER BY job_id", (case_id,))]

    def _ready(self, project):
        if self._unresolved(project["id"]):
            raise WorkflowError("Work is in progress or its physical condition is unverified; resolve that ticket before planning.")

    def ensure_project(self, case_id, jobs, actor="System"):
        case_id, actor = _text(case_id, "Case id"), _text(actor, "Actor")
        if not isinstance(jobs, list) or not jobs:
            raise WorkflowError("A project requires a non-empty job list.")
        copied = json.loads(_json(jobs))
        ids = []
        for job in copied:
            if not isinstance(job, dict):
                raise WorkflowError("Each job must be an object.")
            jid = _text(job.get("id"), "Job id")
            if jid in ids:
                raise WorkflowError("Job ids must be unique.")
            ids.append(jid)
            maximum = _minute(job.get("max_minutes"), "Job upper duration bound")
            if maximum <= 0:
                raise WorkflowError("Job duration must be positive.")
            if "nominal_minutes" in job and not 0 < _minute(job["nominal_minutes"], "Nominal duration") <= maximum:
                raise WorkflowError("Nominal job duration must be positive and within the upper bound.")
            prerequisites = job.setdefault("prerequisites", [])
            if (not isinstance(prerequisites, list)
                    or any(not isinstance(p, str) or not p.strip() for p in prerequisites)
                    or len(set(prerequisites)) != len(prerequisites)):
                raise WorkflowError("Prerequisites must be a list of unique job ids.")
        by_id = {j["id"]: j for j in copied}
        def visit(jid, trail):
            if jid in trail:
                raise WorkflowError("Job prerequisites contain a cycle.")
            for prerequisite in by_id[jid]["prerequisites"]:
                if prerequisite not in by_id:
                    raise WorkflowError("A job prerequisite references an unknown job.")
                visit(prerequisite, trail | {jid})
        for jid in ids:
            visit(jid, set())
        encoded = _json(copied)
        with self._tx():
            old = self._db.execute("SELECT * FROM projects WHERE id=?", (case_id,)).fetchone()
            if old is None:
                self._db.execute("INSERT INTO projects(id,version,jobs_json) VALUES(?,0,?)", (case_id, encoded))
                self._event(case_id, "project", case_id, "created", actor, {"jobs": copied})
            elif old["jobs_json"] != encoded:
                self._ready(dict(old))
                restored = set(json.loads(old["completed_json"]))
                if not restored.issubset(ids):
                    raise WorkflowError("Cannot remove a job with accepted physical history.")
                old_jobs = {j["id"]: j for j in json.loads(old["jobs_json"])}
                if any(_json(old_jobs[jid]) != _json(by_id[jid]) for jid in restored):
                    raise WorkflowError("Cannot reinterpret an accepted intervention using changed job definitions; start a separately reviewed project/model state.")
                self._db.execute("UPDATE projects SET jobs_json=?,version=version+1,fingerprint=NULL WHERE id=?", (encoded, case_id))
                self._event(case_id, "project", case_id, "job_definitions_changed", actor, {"jobs": copied})
        return self.project_state(case_id)

    def set_context(self, case_id, fingerprint, inputs=None, actor="Planner", expected_version=None):
        fingerprint, actor = _text(fingerprint, "Context fingerprint"), _text(actor, "Actor")
        inputs = {} if inputs is None else inputs
        if not isinstance(inputs, dict):
            raise WorkflowError("Context inputs must be an object.")
        encoded = _json(inputs)
        with self._tx():
            project = self._row("projects", case_id)
            if expected_version is not None and project["version"] != expected_version:
                raise WorkflowError("Observed state changed before setting context. Reload current state and rehearse again.")
            self._ready(project)
            if project["fingerprint"] != fingerprint or project["inputs_json"] != encoded:
                self._db.execute("UPDATE projects SET fingerprint=?,inputs_json=?,version=version+1 WHERE id=?", (fingerprint, encoded, case_id))
                self._event(case_id, "project", case_id, "context_changed", actor,
                            {"fingerprint": fingerprint, "inputs": inputs, "previous_version": project["version"]})
            captured_state = self.project_state(case_id)
        return captured_state

    def set_runtime_identity(self, case_id, identity, actor="System"):
        """Invalidate unstarted approvals after a model/software/engine change.

        Started work keeps its original immutable snapshot and can still report
        and verify observations. Registering the first identity also invalidates
        legacy approvals whose runtime identity was never recorded.
        """
        identity, actor = _text(identity, "Runtime identity"), _text(actor, "Actor")
        with self._tx():
            project = self._row("projects", case_id)
            previous = self._db.execute(
                "SELECT identity FROM runtime_identities WHERE project_id=?", (case_id,)).fetchone()
            previous_identity = previous["identity"] if previous else None
            if previous_identity != identity:
                self._db.execute(
                    "INSERT INTO runtime_identities(project_id,identity,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(project_id) DO UPDATE SET identity=excluded.identity,updated_at=excluded.updated_at",
                    (case_id, identity, _now()))
                self._db.execute("UPDATE projects SET version=version+1,fingerprint=NULL WHERE id=?", (case_id,))
                self._event(case_id, "project", case_id, "runtime_identity_changed", actor,
                            {"previous_identity": previous_identity, "identity": identity,
                             "previous_version": project["version"]})
            captured_state = self.project_state(case_id)
        return captured_state

    def record_delay(self, case_id, elapsed_minutes, actor, reason):
        """Record observed waiting at the current location and require replanning."""
        elapsed_minutes = _minute(elapsed_minutes, "Observed elapsed time")
        actor, reason = _text(actor, "Actor"), _text(reason, "Delay reason")
        with self._tx():
            project = self._row("projects", case_id)
            self._ready(project)
            if elapsed_minutes <= project["elapsed"]:
                raise WorkflowError("Observed delay must strictly advance the current clock.")
            self._db.execute("UPDATE projects SET elapsed=?,version=version+1,fingerprint=NULL WHERE id=?",
                             (elapsed_minutes, case_id))
            self._event(case_id, "project", case_id, "delay_recorded", actor,
                        {"previous_elapsed_minutes": project["elapsed"], "elapsed_minutes": elapsed_minutes,
                         "crew_location": project["location"], "reason": reason})
            captured_state = self.project_state(case_id)
        return captured_state

    def project_state(self, case_id):
        with self._read_snapshot():
            row = self._row("projects", case_id)
            unresolved = self._unresolved(case_id)
            runtime = self._db.execute(
                "SELECT identity FROM runtime_identities WHERE project_id=?", (case_id,)).fetchone()
            return {"id": row["id"], "version": row["version"],
                    "completed_jobs": json.loads(row["completed_json"]),
                    "elapsed_minutes": row["elapsed"], "crew_location": row["location"],
                    "crew": row["crew"], "context_fingerprint": row["fingerprint"],
                    "runtime_identity": runtime["identity"] if runtime else None,
                    "inputs": json.loads(row["inputs_json"]), "jobs": json.loads(row["jobs_json"]),
                    "unresolved_jobs": unresolved, "condition_unknown": bool(unresolved),
                    "ready_to_replan": not unresolved}

    def save_plan(self, case_id, snapshot, actor="Planner"):
        actor = _text(actor, "Actor")
        if not isinstance(snapshot, dict):
            raise WorkflowError("Plan snapshot must be an object.")
        snapshot = json.loads(_json(snapshot))
        if snapshot.get("supported") is not True or snapshot.get("admissible", True) is not True:
            raise WorkflowError("Only a supported, admissible evaluated plan can be saved for approval.")
        queue = snapshot.get("queue")
        if not isinstance(queue, list) or any(not isinstance(j, str) for j in queue) or len(set(queue)) != len(queue):
            raise WorkflowError("Plan queue must contain unique job ids.")
        deadline = _minute(snapshot.get("deadline_minutes"), "Deadline")
        _minute(snapshot.get("travel_minutes"), "Travel time")
        with self._tx():
            project = self._row("projects", case_id)
            self._ready(project)
            if project["fingerprint"] is None:
                raise WorkflowError("Set current evaluated input context before saving a plan.")
            if snapshot.get("context_fingerprint") != project["fingerprint"] or snapshot.get("state_version") != project["version"]:
                raise WorkflowError("Evaluated snapshot is stale or lacks its input fingerprint/state version. Rehearse current inputs before saving.")
            jobs = json.loads(project["jobs_json"])
            ids = {j["id"] for j in jobs}
            if not set(queue).issubset(ids) or set(queue) & set(json.loads(project["completed_json"])):
                raise WorkflowError("Queue contains an unknown or already verified job.")
            if deadline < project["elapsed"]:
                raise WorkflowError("Plan deadline precedes the observed elapsed time.")
            if "jobs" in snapshot and _json(snapshot["jobs"]) != project["jobs_json"]:
                raise WorkflowError("Snapshot job definitions differ from the current project.")
            snapshot["jobs"] = jobs
            snapshot["observed_state"] = {"completed_jobs": json.loads(project["completed_json"]),
                                         "elapsed_minutes": project["elapsed"], "crew_location": project["location"]}
            snapshot["context_inputs"] = json.loads(project["inputs_json"])
            # The application context declares the contract before evaluation.
            # Omitting its marker from a new snapshot cannot downgrade that plan
            # to the historical, pre-assurance workflow.
            if "assurance_requirement" in snapshot["context_inputs"]:
                requirement = snapshot["context_inputs"]["assurance_requirement"]
                if ("assurance_requirement" in snapshot
                        and _json(snapshot["assurance_requirement"]) != _json(requirement)):
                    raise WorkflowError("Plan assurance requirement differs from its evaluated context.")
                snapshot["assurance_requirement"] = requirement
            encoded = _json(snapshot)
            plan_id = "P-" + uuid4().hex[:16]
            digest = hashlib.sha256(encoded.encode()).hexdigest()
            self._db.execute("INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?)",
                             (plan_id, case_id, encoded, digest, project["version"], project["fingerprint"], "draft", _now(), actor))
            self._event(case_id, "plan", plan_id, "saved", actor, {"snapshot_hash": digest, "state_version": project["version"], "fingerprint": project["fingerprint"]})
        return self.get_plan(plan_id)

    def _current_plan(self, plan_id, expected=None):
        plan = self._row("plans", plan_id)
        project = self._row("projects", plan["project_id"])
        if project["version"] != plan["state_version"] or project["fingerprint"] != plan["fingerprint"]:
            raise WorkflowError("Plan is stale: evaluate, review and approve a new plan using current inputs and observations.")
        if expected and plan["status"] != expected:
            raise WorkflowError(f"Plan must be {expected}; current status is {plan['status']}.")
        if hashlib.sha256(plan["snapshot_json"].encode()).hexdigest() != plan["snapshot_hash"]:
            raise WorkflowError("Plan snapshot integrity check failed; its saved approval cannot be used.")
        gate = _assurance_gate(json.loads(plan["snapshot_json"]))
        if not gate["approval_allowed"]:
            raise WorkflowError("Plan assurance blocks this action: " + "; ".join(gate["reasons"]))
        if expected in ("reviewed", "approved"):
            review = self._db.execute("SELECT 1 FROM reviews WHERE plan_id=?", (plan_id,)).fetchone()
            if review is None:
                raise WorkflowError("The saved plan has no immutable review record.")
        if expected == "approved":
            approval = self._db.execute("SELECT snapshot_hash FROM approvals WHERE plan_id=?", (plan_id,)).fetchone()
            if approval is None or approval["snapshot_hash"] != plan["snapshot_hash"]:
                raise WorkflowError("The saved approval does not match the exact plan snapshot.")
        return plan, project

    def review(self, plan_id, actor, notes=""):
        actor = _text(actor, "Actor")
        if not isinstance(notes, str):
            raise WorkflowError("Review notes must be text.")
        with self._tx():
            plan, project = self._current_plan(plan_id, "draft")
            self._ready(project)
            self._db.execute("INSERT INTO reviews VALUES(?,?,?,?)", (plan_id, actor, notes, _now()))
            self._db.execute("UPDATE plans SET status='reviewed' WHERE id=?", (plan_id,))
            self._event(plan["project_id"], "plan", plan_id, "reviewed", actor, {"notes": notes})
        return self.get_plan(plan_id)

    def approve(self, plan_id, actor, notes=""):
        actor = _text(actor, "Actor")
        if not isinstance(notes, str):
            raise WorkflowError("Approval notes must be text.")
        with self._tx():
            plan, project = self._current_plan(plan_id, "reviewed")
            self._ready(project)
            self._db.execute("INSERT INTO approvals VALUES(?,?,?,?,?)", (plan_id, actor, notes, plan["snapshot_hash"], _now()))
            self._db.execute("UPDATE plans SET status='approved' WHERE id=?", (plan_id,))
            self._event(plan["project_id"], "plan", plan_id, "approved", actor, {"notes": notes, "snapshot_hash": plan["snapshot_hash"]})
        return self.get_plan(plan_id)

    def get_plan(self, plan_id):
        with self._read_snapshot():
            plan = self._row("plans", plan_id)
            project = self._row("projects", plan["project_id"])
            plan["snapshot_integrity_valid"] = (hashlib.sha256(plan["snapshot_json"].encode()).hexdigest()
                                                 == plan["snapshot_hash"])
            plan["snapshot"] = json.loads(plan.pop("snapshot_json"))
            plan["queue"] = plan["snapshot"]["queue"]
            plan["is_stale"] = project["version"] != plan["state_version"] or project["fingerprint"] != plan["fingerprint"]
            plan["assurance_gate"] = _assurance_gate(plan["snapshot"])
            if not plan["snapshot_integrity_valid"]:
                plan["assurance_gate"].update(valid=False, approval_allowed=False, status="invalid")
                plan["assurance_gate"]["reasons"] = [*plan["assurance_gate"]["reasons"],
                    "The saved snapshot does not match its immutable snapshot hash."]
            if plan["is_stale"]:
                plan["assurance_gate"]["approval_allowed"] = False
                plan["assurance_gate"]["reasons"] = [*plan["assurance_gate"]["reasons"],
                    "The saved plan is historical: its input context or observed state has changed."]
            for name in ("review", "approval"):
                row = self._db.execute(f"SELECT * FROM {name}s WHERE plan_id=?", (plan_id,)).fetchone()
                plan[name] = dict(row) if row else None
            return plan

    def list_plans(self, case_id):
        with self._read_snapshot():
            ids = [r[0] for r in self._db.execute("SELECT id FROM plans WHERE project_id=? ORDER BY created_at DESC,id", (case_id,))]
            return [self.get_plan(pid) for pid in ids]

    def create_ticket(self, plan_id, job_id, actor):
        actor, job_id = _text(actor, "Actor"), _text(job_id, "Job id")
        with self._tx():
            plan, project = self._current_plan(plan_id, "approved")
            self._ready(project)
            snapshot = json.loads(plan["snapshot_json"])
            if job_id not in snapshot["queue"]:
                raise WorkflowError("Job is not part of the exact approved plan.")
            if self._db.execute("SELECT 1 FROM tickets WHERE plan_id=? AND job_id=? AND status!='cancelled'", (plan_id, job_id)).fetchone():
                raise WorkflowError("This plan already has a non-cancelled ticket for the job.")
            ticket_id = "T-" + uuid4().hex[:16]
            self._db.execute("INSERT INTO tickets(id,plan_id,project_id,job_id,status,created_at,created_by) VALUES(?,?,?,?,'approved',?,?)",
                             (ticket_id, plan_id, project["id"], job_id, _now(), actor))
            self._event(project["id"], "ticket", ticket_id, "issued", actor,
                        {"job_id": job_id, "plan_id": plan_id, "snapshot_hash": plan["snapshot_hash"]})
        return self.get_ticket(ticket_id)

    def _ticket_status(self, ticket_id, expected):
        ticket = self._row("tickets", ticket_id)
        if ticket["status"] not in expected:
            raise WorkflowError(f"Ticket must be {' or '.join(expected)}; current status is {ticket['status']}.")
        return ticket

    def assign(self, ticket_id, crew, actor):
        actor, crew = _text(actor, "Actor"), _text(crew, "Crew")
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("approved",))
            _, project = self._current_plan(ticket["plan_id"], "approved")
            if project["crew"] not in (None, crew):
                raise WorkflowError("This prototype has one persistent crew; changing crew requires a new project/shift.")
            self._db.execute("UPDATE projects SET crew=? WHERE id=?", (crew, project["id"]))
            self._db.execute("UPDATE tickets SET crew=?,status='assigned' WHERE id=?", (crew, ticket_id))
            self._event(project["id"], "ticket", ticket_id, "assigned", actor, {"crew": crew})
        return self.get_ticket(ticket_id)

    def start(self, ticket_id, start_minute, actor):
        actor, start_minute = _text(actor, "Actor"), _minute(start_minute, "On-site start")
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("assigned",))
            plan, project = self._current_plan(ticket["plan_id"], "approved")
            self._ready(project)
            snapshot = json.loads(plan["snapshot_json"])
            jobs = {j["id"]: j for j in snapshot["jobs"]}
            job = jobs[ticket["job_id"]]
            completed = set(json.loads(project["completed_json"]))
            if ticket["job_id"] in completed:
                raise WorkflowError("This job has already been verified as restored.")
            if not set(job["prerequisites"]).issubset(completed):
                raise WorkflowError("Job prerequisites must be verified before starting.")
            travel = snapshot["travel_minutes"] if project["location"] != ticket["job_id"] else 0
            earliest = project["elapsed"] + travel
            if start_minute < earliest - 1e-9:
                raise WorkflowError(f"On-site start precedes observed time plus travel ({earliest:g} min).")
            if (("assurance_requirement" in snapshot or "assurance" in snapshot)
                    and start_minute > earliest + 1e-9):
                raise WorkflowError("The on-site start is later than the audited input state permits. Record the observed delay and rehearse, audit, review and approve the updated plan first.")
            if start_minute + job["max_minutes"] + snapshot["travel_minutes"] > snapshot["deadline_minutes"] + 1e-9:
                raise WorkflowError("The job upper duration bound and required return do not fit the approved deadline.")
            # A queue is a policy, not an unrestricted set. Only its first job
            # whose prerequisites and upper bound fit may be dispatched.
            eligible = []
            for jid in snapshot["queue"]:
                candidate = jobs[jid]
                if jid in completed or not set(candidate["prerequisites"]).issubset(completed):
                    continue
                leg = snapshot["travel_minutes"] if project["location"] != jid else 0
                if project["elapsed"] + leg + candidate["max_minutes"] + snapshot["travel_minutes"] <= snapshot["deadline_minutes"] + 1e-9:
                    eligible.append(jid)
            if not eligible or eligible[0] != ticket["job_id"]:
                raise WorkflowError("Job is not the next dispatchable job in the approved queue; review a revised plan.")
            self._db.execute("UPDATE tickets SET status='in_progress',start_minute=? WHERE id=?", (start_minute, ticket_id))
            self._db.execute("UPDATE projects SET version=version+1,elapsed=?,location=? WHERE id=?", (start_minute, ticket["job_id"], project["id"]))
            self._event(project["id"], "ticket", ticket_id, "started", actor, {"start_minute": start_minute, "crew": ticket["crew"]})
        return self.get_ticket(ticket_id)

    def report_completion(self, ticket_id, finish_minute, evidence, actor):
        actor, finish_minute, evidence = _text(actor, "Actor"), _minute(finish_minute, "Finish"), _evidence(evidence)
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("in_progress", "revision_needed"))
            if finish_minute <= ticket["start_minute"]:
                raise WorkflowError("Finish must be after on-site start.")
            if ticket["finish_minute"] is not None and finish_minute < ticket["finish_minute"]:
                raise WorkflowError("Revised completion cannot move observed time backwards.")
            plan = self._row("plans", ticket["plan_id"])
            snapshot = json.loads(plan["snapshot_json"])
            job = next(j for j in snapshot["jobs"] if j["id"] == ticket["job_id"])
            actual = finish_minute - ticket["start_minute"]
            self._db.execute("UPDATE tickets SET status='completion_reported',finish_minute=?,report_evidence_json=? WHERE id=?", (finish_minute, _json(evidence), ticket_id))
            self._db.execute("UPDATE projects SET version=version+1,elapsed=?,location=? WHERE id=?", (finish_minute, ticket["job_id"], ticket["project_id"]))
            self._event(ticket["project_id"], "ticket", ticket_id, "completion_reported", actor,
                        {"finish_minute": finish_minute, "actual_minutes": actual, "evidence": evidence,
                         "duration_bound_exceeded": actual > job["max_minutes"],
                         "deadline_including_return_exceeded": finish_minute + snapshot["travel_minutes"] > snapshot["deadline_minutes"]})
        return self.get_ticket(ticket_id)

    def verify(self, ticket_id, accepted, evidence, actor, observed_condition="restored"):
        actor, evidence = _text(actor, "Actor"), _evidence(evidence)
        if not isinstance(accepted, bool):
            raise WorkflowError("Verification accepted must be true or false.")
        if observed_condition not in ("restored", "uncertain", "residual_restriction"):
            raise WorkflowError("Observed condition must be restored, uncertain or residual_restriction.")
        if accepted and observed_condition != "restored":
            raise WorkflowError("This binary-state prototype cannot model residual or uncertain restoration. Record failed verification and require inspection/model revision.")
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("completion_reported",))
            project = self._row("projects", ticket["project_id"])
            completed = json.loads(project["completed_json"])
            if accepted and ticket["job_id"] in completed:
                raise WorkflowError("Physical restoration has already been accepted for this job.")
            if accepted:
                completed = sorted(completed + [ticket["job_id"]])
            self._db.execute("UPDATE tickets SET status=?,verification_evidence_json=?,observed_condition=? WHERE id=?",
                             ("verified" if accepted else "revision_needed", _json(evidence), observed_condition, ticket_id))
            self._db.execute("UPDATE projects SET version=version+1,completed_json=? WHERE id=?", (_json(completed), project["id"]))
            self._event(project["id"], "ticket", ticket_id, "verification_accepted" if accepted else "verification_failed", actor,
                        {"accepted": accepted, "observed_condition": observed_condition, "evidence": evidence,
                         "physical_state_changed": accepted, "completed_jobs": completed})
        return self.get_ticket(ticket_id)

    def close(self, ticket_id, actor):
        actor = _text(actor, "Actor")
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("verified",))
            self._db.execute("UPDATE tickets SET status='closed' WHERE id=?", (ticket_id,))
            self._event(ticket["project_id"], "ticket", ticket_id, "closed", actor)
        return self.get_ticket(ticket_id)

    def cancel(self, ticket_id, actor, reason):
        actor, reason = _text(actor, "Actor"), _text(reason, "Cancellation reason")
        with self._tx():
            ticket = self._ticket_status(ticket_id, ("approved", "assigned"))
            self._db.execute("UPDATE tickets SET status='cancelled' WHERE id=?", (ticket_id,))
            self._event(ticket["project_id"], "ticket", ticket_id, "cancelled", actor, {"reason": reason})
        return self.get_ticket(ticket_id)

    def get_ticket(self, ticket_id):
        with self._read_snapshot():
            ticket = self._row("tickets", ticket_id)
            plan = self.get_plan(ticket["plan_id"])
            for field in ("report_evidence", "verification_evidence"):
                value = ticket.pop(field + "_json")
                ticket[field] = json.loads(value) if value is not None else None
            ticket["is_stale"] = plan["is_stale"]
            ticket["snapshot_hash"] = plan["snapshot_hash"]
            ticket["actual_minutes"] = (ticket["finish_minute"] - ticket["start_minute"]) if ticket["finish_minute"] is not None else None
            job = next(j for j in plan["snapshot"]["jobs"] if j["id"] == ticket["job_id"])
            ticket["duration_bound_exceeded"] = ticket["actual_minutes"] is not None and ticket["actual_minutes"] > job["max_minutes"]
            ticket["deadline_including_return_exceeded"] = ticket["finish_minute"] is not None and ticket["finish_minute"] + plan["snapshot"]["travel_minutes"] > plan["snapshot"]["deadline_minutes"]
            return ticket

    def list_tickets(self, case_id):
        with self._read_snapshot():
            ids = [r[0] for r in self._db.execute("SELECT id FROM tickets WHERE project_id=? ORDER BY created_at DESC,id", (case_id,))]
            return [self.get_ticket(tid) for tid in ids]

    def events(self, case_id):
        with self._lock:
            result = []
            for row in self._db.execute("SELECT * FROM events WHERE project_id=? ORDER BY sequence", (case_id,)):
                record = dict(row)
                record["payload"] = json.loads(record.pop("payload_json"))
                result.append(record)
            return result

    def export_manifest(self, case_id):
        # A single DB transaction holds a coherent revision across all evidence reads.
        with self._tx():
            return {"schema_version": self.SCHEMA_VERSION, "exported_at": _now(),
                    "authentication": "none; named actors are research-prototype audit labels",
                    "project": self.project_state(case_id), "plans": self.list_plans(case_id),
                    "tickets": self.list_tickets(case_id), "events": self.events(case_id)}
