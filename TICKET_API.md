# Durable ticket workflow API

`from monsoon.tickets import TicketStore, WorkflowError`

The database is schema-versioned SQLite (version 2; version 1 migrates additively without rewriting history). Methods raise `WorkflowError` (a `ValueError`) for rejected input or transitions. Every mutation and its audit event share one transaction. Actors are required non-empty names used as audit labels. This local research prototype does **not** authenticate people or enforce production roles.

```python
store = TicketStore("data/workflow.sqlite3")
store.ensure_project(case["id"], case["jobs"], actor="Planner")
store.set_runtime_identity(case["id"], runtime_identity, actor="System")
state = store.project_state(case["id"])
captured = store.set_context(case["id"], fingerprint, inputs, actor="Planner",
                             expected_version=state["version"])
```

`inputs` is the complete input manifest (JSON object); the integration layer computes the fingerprint from model, scenarios, jobs, deadline, engine and current physical/crew state. Changing either the fingerprint **or** inputs advances the project version. Identical calls are idempotent. `ensure_project` is also idempotent for identical definitions; changed definitions invalidate old plans and require a new context. Reject context changes while a started job has unresolved physical condition.

Pass the observed `expected_version` when installing calculation inputs. It is checked within the write transaction; the returned `captured` state belongs to that same transaction. Preserve its version for the entire calculation, check that it remains current after evaluation, and include it in the saved snapshot. Do not substitute a freshly read version for an older calculation.

`set_runtime_identity(case_id, identity, actor="System")` receives the integration layer's hash of the current case, software and engine. Repeating an identity is idempotent. A changed identity (including the first registration for an older database) advances the version and clears the current context. This check runs on every application entry, including the work-ticket page. Already-started tickets retain their original snapshot and may still report/verify/close despite a runtime change.

`project_state` returns `id`, `version`, `completed_jobs`, `elapsed_minutes`, `crew_location` (`DEPOT` or job id), `crew`, `context_fingerprint`, `runtime_identity`, `inputs`, `jobs`, `unresolved_jobs`, `condition_unknown`, `ready_to_replan`. The returned fields are read from one database snapshot. Times are minutes after shift start. Elapsed time after work is its observed finish **without** a fictitious return to depot. The next planner starts at that actual job location.

```python
from monsoon.service import audit_selected_plan, plan_snapshot

# episode and selected_plan are unchanged results of service.rehearse(...).
audit = audit_selected_plan(case, episode, selected_plan, store, root)
snapshot = plan_snapshot(case, episode, selected_plan, audit)
saved = store.save_plan(case_id, snapshot, actor="Planner")
if not saved["assurance_gate"]["approval_allowed"]:
    raise WorkflowError("; ".join(saved["assurance_gate"]["reasons"]))
store.review(saved["id"], actor="Reviewer", notes="Reviewed assumptions and alternatives")
approved = store.approve(saved["id"], actor="Supervisor", notes="Approved synthetic scope")

# Only a nonempty passing queue can issue a job. A no-work approval cannot.
if selected_plan["queue"]:
    ticket = store.create_ticket(approved["id"], selected_plan["queue"][0], actor="Dispatcher")
    store.assign(ticket["id"], crew="Crew A", actor="Dispatcher")
    store.start(ticket["id"], start_minute=10, actor="Crew lead")
    store.report_completion(ticket["id"], finish_minute=100,
                            evidence={"inspection": "Synthetic reported restoration"}, actor="Crew lead")
    store.verify(ticket["id"], accepted=True,
                 evidence="Synthetic inspection confirms the specified restored state", actor="Verifier")
    store.close(ticket["id"], actor="Supervisor")
```

The example's work times and observations illustrate the API only; they are not generated inspection evidence. The current reference candidate fails its required development checks and stops at the blocked-draft gate. Positive job execution is demonstrated separately with explicit arithmetic test fixtures. The real passing no-additional-work plan contains no dispatchable job.

Required snapshot fields: `queue` list, `supported` exactly true, `deadline_minutes`, `travel_minutes`, `context_fingerprint`, `state_version`. The calculation's fingerprint and version must still match within the save transaction; a cached result cannot inherit a newer context. If `admissible` is present it must be exactly true. The snapshot preserves all other supplied fields. Current full jobs, context inputs and observed state are automatically included; caller-provided jobs must match. Snapshot JSON, hash, identity, captured context/version, reviews and approvals are immutable. Snapshots cannot be deleted through the database's ordinary operations. The workflow trusts the application's evaluated `supported` flag; it is not a second hydraulic evaluator.

New v0.2 application contexts and snapshots also declare `assurance_requirement`, containing `schema_version`, `protocol_id` and `protocol_sha256`. A snapshot cannot remove or change the requirement inherited from its evaluated context. The complete plan-specific result lives in `snapshot["assurance"]`; the shared `monsoon.assurance` validator verifies its schema, frozen development stress protocol, measured evidence and exact audited-subject identity. The subject binds the queue, full canonical planning evaluation (including displayed scores and scenario results), planning decision manifest, model/runtime identity, input context, current observed state, deadline and travel settings. The saved snapshot hash then binds that subject **and** its complete audit result, and approval records the same snapshot hash.

A missing, invalid, failed, unresolved or mismatched required audit may be saved as an immutable **blocked draft** so the result is inspectable and exportable. It cannot advance through `review`, `approve`, ticket creation, assignment or start. A `status="passed"` label without the required measurements and matching provenance does not satisfy the gate. Review/approval notes and actor names cannot waive a failed audit. A blocked draft cannot be repaired in place: audit the still-current calculation and save a new immutable draft. Audits use the declared development stress protocol, including the previously revealed H1/H2 scenarios; passing means acceptance only within that tested synthetic envelope, not independent validation, a field-safety finding or a guarantee about untested scenarios. Changed inputs, observations, protocol, software or engine require a new rehearsal, audit and immutable plan.

The gate reconstructs scenario and prefix conclusions from saved hydraulic metrics, checks the required default-step, half-step and extended-horizon records, and verifies their raw artefact checksums. Deleting or changing raw evidence after approval therefore blocks future starts while retaining the original saved result. Raw evidence needs to remain accessible for authorization; a portable exported briefing records historical results and provenance without conferring an offline approval.

Historical snapshots with neither assurance field retain the prior workflow and are explicitly labelled `legacy_not_required`; they are never represented as having passed the later protocol. A present but malformed assurance field does not opt out. Historical evidence remains readable, and already-started work may report, verify and close even when its original context/runtime has changed or a newer audit validator can no longer accept it. This preserves actual observations without authorizing new work.

`save_plan`, `review`, `approve`, `get_plan`, `list_plans` return records with `id`, `project_id`, `snapshot`, `snapshot_hash`, `snapshot_integrity_valid`, `state_version`, `fingerprint`, `status` (`draft`, `reviewed`, `approved`), `queue`, `is_stale`, `assurance_gate`, `review`, `approval`, `created_at`, `created_by`. The gate includes `required`, `valid`, `approval_allowed`, `status` and `reasons`; inspection does not itself create a review. A stale plan retains its historical audit result/status but has `approval_allowed=false`. An old approval remains historically approved, with `is_stale=true`; it cannot issue/start current work. Every advancing transition rechecks the stored snapshot hash and required audit within the state-change transaction.

Each approved plan can issue multiple **per-job** tickets. Creating a ticket inherits the exact reviewed/approved plan. `create_ticket`, `assign`, `start`, `report_completion`, `verify`, `close`, `cancel`, `get_ticket`, `list_tickets` return records with `id`, `plan_id`, `project_id`, `job_id`, `status`, `crew`, `start_minute`, `finish_minute`, `actual_minutes`, `report_evidence`, `verification_evidence`, `observed_condition`, `is_stale`, `snapshot_hash`, `duration_bound_exceeded`, `deadline_including_return_exceeded`, `created_at`, `created_by`.

Ticket states are `approved → assigned → in_progress → completion_reported → verified → closed`. Review occurs on the immutable parent plan. Failed verification branches to `revision_needed`; resubmitting work/evidence through `report_completion` returns to `completion_reported`. `cancel(ticket_id, actor, reason)` applies only to approved/assigned work, including stale tickets.

Start checks travel, upper duration bound, required return, current approval, prerequisite restoration, the single persistent crew and approved queue order. It allows skipping jobs whose upper bound cannot fit, matching the scheduler's dispatch rule. `start_minute` means **on-site** start, not depot departure. It must be at least current elapsed plus travel; the initial minimum is normally 10 minutes. For a plan requiring assurance, on-site start must equal that audited time: later waiting must be recorded with `record_delay` and a new rehearsal/audit before work is authorized. This prevents an audit of an earlier observed state from silently authorizing a changed timing envelope. Starting advances the version and blocks another start or new plan until the physical state is resolved.

`record_delay(case_id, elapsed_minutes, actor, reason)` records an observed delay at the current crew location when no work/condition is unresolved. The clock must strictly advance. It preserves location, records the reason, increments the version and clears context so remaining work must be rehearsed and approved again. A delayed start cannot silently switch to a different first job from the old calculation: that job alone may be an unevaluated hydraulic state. Record the delay and replan before changing the next dispatch.

Completion reporting updates observed elapsed time/location and leaves restoration **unverified**. Actual overruns are recorded with explicit bound/deadline flags, rather than rejecting the observation or fabricating a shorter duration. The model cannot safely replan while work/condition is unresolved. Accepted `verify` adds the job once, advances the version and re-enables planning. A later close is administrative and does not change physical state again. Subsequent unstarted tickets become stale: cancel them and evaluate/review/approve a new plan from observed time and location. Already-started work can report/verify/close despite its original plan now being historical.

Verification requires non-empty evidence text or object. `accepted=False` keeps the job unresolved. `observed_condition` is `restored`, `uncertain` or `residual_restriction`; accepted restoration currently requires `restored`. Residual restrictions need inspection/model revision because the prototype deliberately has only binary validated intervention states. It cannot invent a residual hydraulic patch.

Read/export: `list_plans(case_id)`, `list_tickets(case_id)`, `events(case_id)` (ordered, append-only), `export_manifest(case_id)` (project, plans, tickets, events and schema version). All are JSON serialisable. Composite reads and evidence exports use one database revision, including when another connection records an observation. Use `disconnect()` to release the database connection; `close()` is reserved for ticket closeout. SQLite transactions and connection-level locks protect state changes across app reruns and independent connections. Local file access remains the trust boundary, not tamper-proof external audit storage. Hashes establish consistency, not the authenticity of arbitrary caller-supplied evidence. A person able to modify the Python runtime, replace the database or its triggers, or fabricate a complete consistent result is outside this prototype's trust boundary. Authenticated roles, signed provenance and independently controlled audit storage are not implemented.
