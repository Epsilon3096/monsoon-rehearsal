# Work-window interruption audit

This additive module audits an unchanged `monsoon.planning.replay` result against a hypothetical cutoff or explicitly supplied observation records. It does not choose jobs, rerun the planner, execute SWMM, update tickets, or authorise work. It does not alter the frozen policy, protocol, source evidence, or earlier evaluation results.

The assertion **“an unfinished job automatically retains its pre-work state, with 100% accuracy” is rejected**. Starting work can change the physical condition before restoration is complete. An interrupted job therefore has an unresolved condition unless explicit condition evidence is supplied. The audit does not predict the hydraulics of partial excavation, debris, temporary obstructions, or other intermediate conditions.

Three times have different meanings:

| Time | Meaning in this audit |
|---|---|
| Planned restore-and-return deadline | The original replay's `deadline_minutes`, preserved without adjustment. |
| Uncertain storm timing | An optional declared range, with issue and availability times. It is not a guarantee, a probability distribution, or a replacement deadline. |
| Stop cutoff | A hypothetical cut in replay mode, or the declared time a stop instruction/unsafe condition was observed in observation mode. It is not silently inferred from forecast storm onset. |

All minute values use the same shift/window origin as the imported replay. A caller must identify the correct replay and actual window. Matching job IDs and a generated fingerprint do not independently establish that association.

## Pure APIs

```python
from monsoon.work_window import audit_replay_window, audit_observed_window

report = audit_replay_window(replay_result, stop_minute, storm_timing=None)

report = audit_observed_window(
    replay_result,
    observations,
    stop=stop,
    as_of_minute=as_of_minute,
    recovery=None,
    storm_timing=None,
)
```

The APIs accept JSON-compatible Python objects and return a report dictionary. Invalid input returns `valid: false`, `status: "invalid"`, and `errors`; it does not produce restoration credit. They perform no network or file access and do not authenticate callers or evidence authors. Use the separate authenticated operations workflow where a saved research record and account audit are required.

`valid: true` means the documented input structure and timeline checks passed. It does not mean that the source is authentic, that the underlying replay is supported, that a condition is independently verified, or that work is safe. An originally unsupported replay remains labelled unsupported in `original_replay_status` and its reasons remain visible.

## Replay input

Supply the complete, unchanged object returned by `planning.replay`. Required fields are `status`, `completed_jobs`, `events`, `finish_minute`, `work_finish_minute`, `crew_minutes`, `skipped`, `reasons`, `start_minute`, `start_location`, `final_location`, `last_work_location`, `deadline_minutes`, and `return_minutes`.

Each replay event requires `job_id`, `depart_minute`, `start_minute`, `finish_minute`, `actual_minutes`, `max_minutes`, `from_location`, `to_location`, `bound_finish_minute`, and `supported`. Unknown fields are rejected. The audit checks endpoint arithmetic, single-crew chronology, uniform travel, the original duration-support rule, completed-job consistency, and the original bound-plus-return dispatch gate. It cannot reconstruct missing endpoints or an original priority queue that is absent from the replay. `replay_job_order` means the supplied replay's dispatched event order, not a reconstructed priority queue.

The canonical `replay_sha256` binds the report to the supplied JSON values; it is not an authentication seal or proof of provenance. The input is not mutated. Changing the cutoff changes the audit view, not the replay, its queue, or its original deadline. No future cutoff is consulted to select jobs.

### Hypothetical mode

`audit_replay_window` returns projected timeline exposure. Even when a replay used a realised-duration scenario, its `completed_jobs` and finish times are not actual observations for this API. `decision_known_restored_jobs` stays empty and observed timestamps remain null.

| Cut position | Job state |
|---|---|
| At or before planned departure | `not_departed_at_cutoff` |
| After departure, before planned start | `travelling_at_cutoff` |
| Exactly at planned start | `planned_start_boundary_not_started` |
| Strictly inside the work interval | `work_interrupted_in_projection` |
| Exactly at replay finish | `replay_finish_boundary_unverified` |
| After replay finish | `replay_finished_unverified` |
| Job recorded only as skipped | `not_scheduled_in_replay` |

When departure and start coincide, the exact boundary is labelled `not_departed_at_cutoff`; it is still not a started job. Cutoff comparisons use exact ordering, without rounding an event across the boundary. The original planner's small arithmetic tolerance is preserved only when validating its original dispatch/support contract.

The projected return phase is reported separately as `return_phase`; it never supplies an observed depot arrival. `projected_finished_jobs` is a timeline list with no restoration credit. `unresolved_jobs` lists jobs whose projected work interval contains the cutoff. Recovery durations remain unknown in this mode.

## Observation mode

`audit_observed_window` requires explicit records. It never copies replay finishes into observed completion, verification, or return fields. No trial or operator participation is established merely by constructing a report.

`observations` has exactly these fields:

```text
events: list of documented events, in physical occurrence order
coverage: null, or the documentary coverage declaration described below
```

Every event requires:

```text
event_id: nonempty unique string
type: one of the event types below
minute: nonnegative finite physical occurrence time
available_minute: when that event record became available to the cutoff information view
evidence_ref: {id: nonempty string, sha256: lowercase 64-character hex digest,
               source: nonempty source description}
notes: optional nonempty string
```

| Event type | Additional required fields | Interpretation |
|---|---|---|
| `departure_observed` | `job_id` | Reported travel toward a job; does not establish work start. |
| `work_started` | `job_id` | Explicit reported work start. |
| `completion_reported` | `job_id` | Reported completion after positive elapsed work; still unverified. |
| `work_interrupted` | `job_id` | Reported interruption after a recorded start; condition becomes unresolved. |
| `condition_verified` | `job_id`, `condition`, `accepted` | A supplied inspection/acceptance record, subject to the limits below. |
| `return_started` | none | Reported return departure; does not resolve an abandoned job's condition. |
| `returned` | none | Explicit reported depot arrival. No departure time is invented if absent. |

`condition` is `restored`, `baseline`, `intermediate`, or `unknown`. `accepted` must be a boolean. A caller-entered acceptance is documentary evidence only: the API does not verify professional qualifications, inspection adequacy, the person, or the referenced content. A digest-shaped string is not a check that the referenced file exists or matches that digest.

An accepted `restored` record requires a separate recorded start and completion before or at verification. Cutoff credit additionally requires all three records to be available by the cutoff. An accepted `baseline` inspection may document a baseline condition after interruption, but it is never counted as a completed/restored improvement. `intermediate`, `unknown`, or unaccepted inspections do not yield restored credit or hydraulic support.

This is a single-crew, single-start-per-job record contract. Overlapping starts, repeated starts/completions, unknown job IDs, completion without a recorded start, and interruption after completion are invalid. The latter requires a new work cycle rather than reuse of old completion evidence. New work after return departure/arrival is outside this window. Physical completion/interruption strictly after return departure is also outside this cycle; use `available_minute` for a late report of an event that occurred earlier. A simultaneous work-end/return-departure boundary is allowed. Later condition inspections may be recorded after crew return; they remain separate evidence. Observed jobs may include a job recorded as skipped in the replay, but the departure from the replay is disclosed rather than used to revise the queue.

Times must satisfy:

```text
replay start <= event minute <= event available_minute <= as_of_minute
replay start <= stop.minute <= as_of_minute
```

Events are ordered by occurrence time; availability times may be out of order. A later upload of an earlier observation remains later information. `stop` requires exactly `{minute, reason, evidence_ref}`. Its minute is the declared observation time of the stop, not a forecast time or the later import time.

An actual recorded `work_started` **at or after the stop** is a stop-rule breach, even when the record arrives later. A hypothetical start exactly at a cut is merely a boundary that has not begun. The two modes deliberately have different interpretations.

### Information views and coverage

Each observed job row provides three distinct states:

- `state`: events physically occurring by the cutoff **and available by the cutoff**.
- `retrospective_state_at_cutoff`: events occurring by the cutoff, including reports arriving by the later as-of time.
- `state_as_of`: all supplied events occurring and available by the as-of time.

Later completion or inspection cannot retroactively enter `decision_known_restored_jobs`. `observation_events` retains validated event records, while later inspection times also appear in `verification_as_of_minute` and `verification_available_as_of_minute`. `completion_reported_as_of_minute` and `observed_start_as_of_minute` retain the corresponding later view.

An optional `coverage` declaration has exactly:

```text
{from_minute, through_minute, available_minute, evidence_ref}
```

It attests that the supplied event log covers crew/job activity for that interval. Its times satisfy `from <= through <= available <= as_of`. For cutoff completeness it must cover replay start through cutoff and be available by cutoff. It remains an attestation, not independent proof that no unlogged work occurred. Later records can expose gaps or contradict the declaration. The report always sets `coverage_independently_verified` and `unlogged_work_independently_excluded` to false.

With an available complete declaration, absence of a start is labelled `no_start_recorded_in_attested_log`. Without it, absence is `no_evidence` and the job remains unresolved. Neither label certifies the physical state. Prior restored conditions omitted from the replay are not reconstructed or verified by this audit.

### Recovery and return

`recovery` is null or exactly:

```text
{restoration_minutes: number or null,
 inspection_minutes: number or null,
 return_minutes: number or null,
 available_minute: number,
 source: nonempty description}
```

These are declared, unapproved duration bounds. If all are finite, nonnegative, and known by cutoff, the audit reports `budgeted_finish_minute = cutoff + restoration + inspection + return` and whether it is at or before the original deadline. A null duration leaves that budget unresolved. A later estimate is retained with `later_estimate_not_available_at_cutoff` and cannot retrospectively create a cutoff budget.

A fitting budget, including zero durations, does not complete work, establish inspection, prove return, or approve recovery. Explicit depot arrival is required for `recovery.return_confirmed` in the cutoff information view. `returned_by_as_of` is a separate later view. An observed return strictly after the original deadline sets `reported_return_after_deadline`; arrival exactly at it does not.

### Storm timing

`storm_timing` is null or exactly:

```text
{earliest_minute: number or null,
 latest_minute: number or null,
 issued_minute: number,
 available_minute: number,
 source: nonempty description}
```

The range cannot be reversed, and issue must precede availability. Observation mode also requires availability by the as-of time. Unknown endpoints remain null. The report preserves whether the range was available at cutoff; it never uses it to reselect jobs, replace the original deadline, infer the observed stop, or assign a probability.

## Stable report fields

Both modes, including invalid reports, include:

```text
schema_version = "monsoon.work-window/1"
valid, status, mode, summary, errors, warnings
replay_sha256, stop_minute, planned_deadline_minute
jobs: list of row dictionaries
decision_known_restored_jobs: list of job IDs
decision_known_baseline_jobs: list of job IDs
unresolved_jobs: list of job IDs
recovery: dictionary
storm_timing: dictionary or null
stop_rule_breach: boolean
observation_events: list
coverage_declaration: dictionary or null
```

Every job row includes `job_id`, `state`, `planned_depart_minute`, `planned_start_minute`, `planned_finish_minute`, `observed_start_minute`, `completion_reported_minute`, `verification_minute`, and `verification_available_minute`. Unavailable times are null. Observation mode adds the retrospective/as-of fields described above. Hypothetical mode adds `observed_restoration_credit: false`.

Statuses are:

| Status | Meaning |
|---|---|
| `invalid` | The documented input contract could not be interpreted consistently. |
| `hypothetical_interruption_exposure` | At least one replay work interval contains the cut. |
| `hypothetical_travel_exposure` | The cut falls in projected job travel or depot-return travel. |
| `hypothetical_timeline_only` | Other projected timeline boundary/view; no observed restoration claim. |
| `observed_stop_breach` | At least one supplied start occurred at or after the stop. |
| `unresolved` | Cutoff job conditions, coverage, or explicit cutoff return evidence are missing. |
| `documented_conditions_only` | The supplied cutoff records resolve those documentary gaps; no physical or operational approval follows. |

All reports keep these flags false: `work_authorisation_granted`, `hydraulic_replay_allowed`, `queue_reselected`, `future_cutoff_used_for_job_selection`, `coverage_independently_verified`, `evidence_references_independently_verified`, `unfinished_job_assumed_unchanged`, and `unfinished_job_assumed_restored`.

## Blank integration shape

This is an **invalid placeholder shape**, not an observation fixture or evidence of any trial. Replace all placeholders using a correctly identified actual window and source records. The sample digest deliberately fails validation.

```json
{
  "observations": {"events": [], "coverage": null},
  "stop": {
    "minute": null,
    "reason": "REPLACE_WITH_RECORDED_STOP_REASON",
    "evidence_ref": {
      "id": "REPLACE_WITH_SOURCE_ID",
      "sha256": "REPLACE_WITH_ACTUAL_SOURCE_SHA256",
      "source": "REPLACE_WITH_SOURCE_DESCRIPTION"
    }
  },
  "as_of_minute": null,
  "recovery": null,
  "storm_timing": null
}
```

Pass `observations` as the second API argument and the other fields as keyword arguments. Import the unchanged replay separately. The UI must not convert a synthetic replay into actual intent or pre-fill counterfeit event/evidence records.

## Verification and limits

The focused suite `tests/test_work_window.py` has 110 passing checks at source freeze. It covers exact start/finish/return boundaries; altered original bound gates and travel; delayed prerequisite availability; reporting versus verification; interruption after completion; physical work events after return; incomplete coverage; actual stop-rule breaches; observed order deviations; late inspection and return; recovery budgets; storm-time separation; malformed, unknown, boolean, nonfinite, oversized, and cyclic input. These are synthetic unit tests and establish software behavior only.

No operator interview, field work, physical measurement, hydraulic partial-state validation, supervised pilot, or actual early-stop trial is established by this module or its tests. A documented condition is still insufficient for hydraulic replay without reviewed model suitability, initial and boundary states, and the applicable assurance process. No frozen scientific result is extended or relabelled by this feature.
