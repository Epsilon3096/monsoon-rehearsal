# Local operator review and prospective shadow records

This is an authenticated **research recordkeeper**, separate from the existing synthetic Work tickets demonstration. It does not activate a site model, change hydraulic geometry, issue a work order, verify a professional qualification, authorise a pilot, or establish measured flood benefit. No real operator, site inspection, or observed trial is supplied with the release. Empty forms and templates are preparation tools, not completed validation.

The intended next use is a bench-first study while real operator and site access are arranged by the user. Record a genuine operator baseline before model disclosure, preserve disagreements and no-work choices, measure physical response, freeze the evaluation, and later collect prospective shadow observations. A named responsible engineer's documented review supports a readiness discussion; site permission, safe work procedures and any live pilot decision remain outside this application.

## Account and evidence boundary

`OperationsStore(path)` uses a separate SQLite database. Call `needs_bootstrap()`, then `bootstrap_admin(username, password, display_name)` exactly once on a new store. There are no default credentials. Passwords require 12–1024 characters and are stored as salted scrypt hashes (N=16384, r=8, p=1); session tokens are random, only their SHA-256 digests are stored, and expiry defaults to one hour. `login(username, password)` returns `{token, expires_at, user}`. `whoami(token)` returns the current public account. `logout(token)` revokes that session. `change_password(token, current_password, new_password)` invalidates every existing session for the account.

The first administrator manages accounts; that role does not implicitly perform research work. `create_user(token, username, password, display_name, roles)` requires an administrator. Roles can be combined intentionally. Use distinct named accounts for the people involved, not shared credentials.

| Role | Write authority |
|---|---|
| admin | Create/disable accounts; verified backup/restore to a new file |
| dispatcher | Stage a site package, record/revise an undisclosed baseline, disclose model artifact, seal a shadow decision |
| reviewer | Review a site staged by a different account, record operator feedback, record readiness evidence reviews |
| observer | Append observed/missing/error outcomes |
| inspector | Append outcomes and record readiness evidence reviews |

All authenticated accounts can read non-credential research records. `list_users(token)` is administrator-only; `disable_user(token, account_id, expected_version)` revokes that account's sessions. Credential/session records are never returned through the general record API. Research roles can store attachments. Every protected method authenticates again and verifies the record chain, so hiding a UI button is not the permission control.

`get_record(token, record_id)` returns `{id, kind, version, created_at, created_by, sha256, data}`. `list_records(token, kind=None, site_id=None)` returns a list of these records. Most mutations of an existing record require its current integer `expected_version`; a stale or concurrent edit raises `ConflictError`. `close()` and `disconnect()` are equivalent.

Local authentication is not identity proof. An administrator can create another local account; independent-account review therefore records separation of accounts, not independent employment or professional verification. This is not an internet-facing deployment: account recovery, rate limiting at a network boundary, encrypted storage, access monitoring and a production security review remain future work. Existing `TicketStore` APIs remain a local unauthenticated demonstration and are not covered by these controls.

## Attachment contract

`add_attachment(token, filename, content, media_type, provenance, observed_at)` returns an attachment record. `content` is `bytes`, 1 byte to 5 MiB; filenames must be plain names without paths, reserved device names or traversal. Supported matching extensions/types are `.txt`/`text/plain`, `.csv`/`text/csv`, `.json`/`application/json`, `.pdf`/`application/pdf`, `.png`/`image/png`, and `.jpg` or `.jpeg`/`image/jpeg`. Text is UTF-8; binary types undergo a header check, not malware scanning or a claim of source authenticity. Files are stored as immutable database BLOBs, never executed or unpacked.

`provenance` is either nonempty text or a JSON object with nonempty `source`; useful additional fields are `collected_by`, `collection_method`, `permission`, and instrument/calibration reference. `observed_at` is required, includes a timezone, and cannot be future-dated. The server separately records `received_at`. Both metadata and content are hashed. `read_attachment(token, attachment_id)` returns `{record, content}`; verification fails closed if bytes or metadata changed. Attachment IDs are passed as lists to the methods below. Upload evidence **before** sealing a decision if it was used as a decision input.

## Site and operator workflow

`stage_site(token, payload, attachment_ids=())` accepts a dict, JSON text or UTF-8 bytes. It invokes `monsoon.site_data.validate_site_package` itself and stores the exact parsed package and deterministic report. An invalid but parseable package may remain a staged draft; malformed/duplicate-key JSON is rejected. No caller-supplied `valid` flag is trusted.

`review_site(token, site_id, expected_version, notes, attachment_ids=())` requires a reviewer different from the stager and a currently valid package under the same validator. Its status is only `reviewed_for_research`. A correction requires staging a new site record, preserving the previous version and review.

`create_interview(token, site_id, operator_name, operator_role, window_description, constraints, baseline_plan, attachment_ids=())` records the claimed operator's decision **before** model disclosure. Names and testimony do not independently prove participation. The constraints object must explicitly include all six fields below; use null for unknown and preserve the resulting readiness gap:

```json
{
  "available_crew": null,
  "authorised_jobs": null,
  "access": null,
  "restoration_deadline": null,
  "stopping_rules": null,
  "closeout_evidence": null
}
```

When known, `authorised_jobs` is a list of unique job IDs; the operator queue must be a subset. The baseline object is `{queue: [job IDs], rationale: nonempty text, no_work_reason: text or null}`. An empty queue requires a reason. This structure intentionally captures no-work choices. `revise_interview(token, interview_id, expected_version, constraints, baseline_plan, notes)` is allowed only before disclosure and retains all earlier revisions.

`reveal_model(token, interview_id, expected_version, model_snapshot)` permanently locks the baseline. The model snapshot requires:

```text
model_id: nonempty model/version identifier
policy_id: nonempty policy/version identifier
generated_at: real ISO timestamp including timezone, no later than now
inputs_sha256: SHA-256 of the exact available_inputs JSON list
site_package_sha256: SHA-256 of the exact staged package used by the model
result:
  decision: recommend | abstain | no_work
  queue: list of unique job IDs
  reasons: list of nonempty strings
```

Abstention and no-work decisions require an empty queue and at least one reason. The public helper `input_snapshot_sha256(available_inputs)` computes the required fingerprint. A model artifact entered here is a recorded artifact, not proof that the model is validated or that it ran successfully. The store records disclosure order inside the application; it cannot exclude earlier off-platform exposure.

`record_interview_review(token, interview_id, expected_version, feedback, attachment_ids=())` requires the reviewer role, a sealed model disclosure and at least one attachment. `feedback` is nonempty text documenting the operator's response, disagreements, counterexamples and workflow implications. The UI provides a feedback text field and evidence attachment selector. This is documentation for discussion, not a testimonial manufactured by the app.

## Prospective shadow protocol

`create_shadow(token, site_id, interview_id, available_inputs, protocol, *, decision_at=None, operator_plan=None, model_snapshot=None, attachment_ids=(), mode="SHADOW")` returns the sealed decision record. Prefer `decision_at=None`, which uses server time. An explicit timestamp must be no later than now and at most five minutes old. The application refuses to backfill old decisions as prospective records. A baseline can be used in only one shadow decision; collect a new baseline for a new decision.

Each `available_inputs` item requires `id`, `source`, `observed_at`, `issued_at`, `available_at`, and `value`. IDs are unique. Use an explicit null `value` for unknown data. Timestamps require timezones. Observation/issue times cannot follow availability; none may follow decision time. Forecast `valid_at` can be an additional future timestamp, but it does not replace the issue/availability cutoff. Optional `attachment_ids` bind evidence whose observation and server receipt times predate the decision. These are declared source times, not independent provenance verification. The exact input fingerprint must match the disclosed model artifact.

`protocol` requires nonempty text for `protocol_id`, `objective`, `stopping_rules`, `exception_rules`, and `outcome_plan`. Include how actual plans, completion, exceptions, measured response, planning time and crew time will be recorded, and how loss of evidence is handled. Additional JSON fields may hold predeclared metrics or links to the frozen evaluation.

The store pulls the operator plan and model from the sealed interview. Optional caller-supplied copies must match exactly. The model's site-package hash must match the interview and staged site, and its declared generation time cannot precede the valid site's package creation, any input's declared availability or linked attachment receipt. Site contract validation separately rejects source observations and approvals later than package creation. A valid site's authorised jobs and recommended queue must reference its declared job IDs. The site record, input set, operator constraints, protocol and model snapshot are hashed into `decision_seal_sha256`; later outcome appends cannot change that seal. Other modes are rejected. Unknown inputs or an invalid site package may be retained in a research record so that abstention and missing-input behaviour can be studied; these records explicitly say `draft_site_unvalidated` and do not clear their readiness gaps.

`record_outcome(token, shadow_id, expected_version, status, observed_at, observations, notes, attachment_ids=())` appends a separate immutable outcome, then advances the shadow record's version. It returns the outcome record; reload the shadow before another append. Status is `observed`, `missing`, or `error`; missing/error remain unresolved and can later be supplemented. The observation time must be after server sealing and no later than now. Missing/error may use `{}` observations but require explanatory notes.

An observed outcome requires later-collected attachment evidence and explicit fields `executed_plan` (job-ID list), `completed_jobs` (subset), `exceptions` (list), `measured_response` (object or null), `planning_minutes` and `crew_minutes` (non-negative finite numbers or null). Unknown response/time values remain visible; recorded actual work does not imply complete physical measurements. Already observed outcomes cannot be silently edited. The observed plan may differ from both candidate plans and must be recorded as actually performed. Never present the unexecuted alternative as a measured counterfactual flood reduction.

## Readiness, audit and backup

`record_evidence_review(token, site_id, category, assessment, notes, attachment_ids, *, engineer_name=None, qualification_reference=None)` requires reviewer or inspector and at least one attachment. Category is `physical_measurements`, `frozen_evaluation`, `operating_constraints` or `engineer_review`; assessment is `accepted_for_discussion`, `unresolved` or `rejected`. The engineer category requires a named engineer and a qualification/reference description, but its status remains `reported_not_independently_verified`. A checkbox or user-entered title cannot become verified professional authority.

`readiness(token, site_id)` reports separate documentary gaps for the site contract/review, operator comparison, operating inputs, physical measurements, frozen evaluation, operating constraints, engineering review and unresolved/missing shadow outcomes. Counts distinguish `synthetic_fixture_count`, `reported_measured_count` (a declared supplied-survey contract and a reported outcome, not independent verification), and all recorded observed-status entries. Synthetic records never count as measured site trials. An actual executed plan with unknown physical response retains a response-measurement gap. The report always states `physical_validation_established=False`, `professional_identity_verified=False`, `operational_activation_allowed=False` and `pilot_authorised=False`. Even a complete documentary set only supports an external responsible engineering discussion; this generic recordkeeper cannot certify arbitrary attachments or grant a permit.

`verify_integrity(token)` checks every record revision, audit-chain link and attachment hash. `export_site(token, site_id)` exports domain records and integrity metadata without credentials or attachment bytes. Each record revision and audit event is append-only in SQLite; revisions have optimistic concurrency checks. Hashes provide local alteration detection, **not** an external digital signature or protection against a privileged person replacing the database and recomputing every hash. Protect the database and backups with operating-system permissions and appropriate storage controls.

`backup(token, destination)` requires administrator and writes a verified consistent SQLite backup only to a **new** path. Its result includes `{path, sha256, integrity, contains_password_hashes_and_session_hashes: true}`. The backup contains sensitive research evidence and salted credential hashes. `restore_new(token, backup_path, destination)` verifies the source, restores into a new database, verifies again and revokes all restored sessions. It returns `{path, integrity, all_sessions_revoked: true, live_database_replaced: false}`. The live database is never silently replaced. Sign in afresh when deliberately switching to the restored copy. Corrupt/foreign backups and existing destinations are rejected.
