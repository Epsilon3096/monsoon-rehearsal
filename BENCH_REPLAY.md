# Separate measured-boundary replay ledger

`monsoon.bench_replay` adds a separate research sequence: **calibration boundary receipt → internal replay seal → calibration response receipt → model/recipe freeze → future validation boundary receipt → internal replay seal → withheld response receipt**. The historical declared-forcing study in `bench_study.py`, its database semantics, and the physical protocol remain unchanged. Use a new replay database; this module rejects an old study database without migrating it.

There are **no supplied real measured boundary traces or physical response observations**. The new `synthetic_bench_replay_*_v1.json` files are invented software fixtures. The native-engine exercise generates responses from an already sealed prediction plus explicit offsets. It is circular by design and establishes sequence, numerical checks, retention, and arithmetic only. It is not physical calibration, independently blinded validation, an instrument assessment, commissioning, or an operator trial.

## Planned targets and delivered inputs

A future assignment freezes an event ID, UTC window (or null synthetic window), and optional `planned_targets`. Targets describe the intended inflow and receiving-stage schedule. They are retained separately and **never used as the replay forcing**. Actual validation input values are absent from the freeze API and arrive later through `record_validation_boundaries`.

The server constructs a `monsoon.bench-run/1` internally from the complete supplied inflow and receiving-stage traces, the frozen duration and initial-state contract, and the exact selected model hash. Callers cannot supply the derived run, replace frozen parameters, submit predicted columns, provide an execution callback, or use response files as forcing. A boundary trace can differ from its target without causing the model to silently revert to the target. This version retains both records but does not calculate target-reproduction acceptance.

The boundary receipt is committed before executing SWMM. Its prediction and evidence seal are committed before the response API can receive response data. This enforces local receipt order, not externally witnessed blindness: the store cannot prove that a person did not view, copy, collect, or manipulate information elsewhere beforehand.

## Supported scope

This schema supports a whole-event **dry-zero-flow** start through the unchanged v1 adapter. Every input trace starts at event time zero, with zero inflow and receiving stage at or below its outfall invert, and ends at the declared event horizon. There is no hidden warmup, wet reset, arbitrary initial water assignment, or response-derived initial state.

The separate `bench_initialization` prepared-run wrapper is not integrated into replay-v1. Wet/equilibrated collection cannot be relabelled as a cold start. The physical protocol's unsupported rows remain unsupported; a completed replay ledger is not completion of the 24-event physical protocol. Initial numerical water, represented losses, spill escape, and receiving-water control-volume assumptions retain the limits documented in [BENCH_MODEL.md](BENCH_MODEL.md).

## Frozen recipe contract

`monsoon.bench-replay-recipe/1` contains exactly:

| Field | Contract |
|---|---|
| `schema_version`, `recipe_id`, `notes` | Exact schema, bounded stable ID, and explicit interpretation. |
| `model_sha256` | Canonical hash of the exact valid model candidate. |
| `duration_s` | Integer whole-event seconds, within the v1 model and reporting budgets. |
| `initial_conditions` | The v1 `{kind: dry_zero_flow, source_id}` contract. |
| `units` | Exactly `{time: s, stage: m, flow: m3/s, volume: m3}`. |
| `vertical_datum` | Exact supplied site datum. No automatic datum or unit conversion. |
| `clock` | Fields described below. |
| `interpolation` | Explicit interpolation, coverage, and missing-data policy below. |
| `boundary_series` | Every inflow and receiving-stage boundary exactly once. |
| `response_series` | One to 64 independent response series. |
| `sign_convention` | Exact conventions below. |

Every series entry has exactly `id`, `quantity`, `location_id`, `unit`, `expanded_uncertainty_abs`, and `source_id`. IDs are distinct across boundary and response inventories. Instrument/uncertainty source references must be nonempty and uncertainty must be finite and positive. References are retained declarations, not authenticated calibration certificates. Receipt metadata must match the recipe, including the declared instrument uncertainty and source; a different instrument specification requires a new design.

Boundary quantities are `inflow_m3_s` at every site's declared inflow node in `m3/s`, and `receiving_stage_m` at every outfall in `m`. These inventories cannot omit a known boundary. Responses may be:

| Quantity | Location | Unit |
|---|---|---|
| `stage_m` | Any non-outfall node | `m` |
| `outflow_m3_s` | A declared outfall | `m3/s` |
| `spill_m3_s` | A declared spill node | `m3/s` |
| `storage_m3` | `SYSTEM` | `m3` |

Receiving-stage and inflow inputs cannot be scored as independent responses. A response inventory can be sparse; it does not establish a complete measured control-volume balance. Repeated quantity/location response entries are rejected.

`sign_convention` is exactly:

```json
{
  "inflow": "positive_into_control_volume",
  "outfall_exchange": "positive_outward_negative_backflow",
  "spill": "positive_outward"
}
```

The recipe clock has `kind`, `origin`, `time_unit`, `max_synchronization_uncertainty_s`, and `source_id`. Its kind is `synthetic_virtual_elapsed` for the explicitly synthetic branch or `measured_utc_elapsed` for the supplied-survey branch. Origin is `window_start` and time unit is `s`. The declared synchronization uncertainty limit cannot exceed half a report interval. Measured clock uncertainty must be positive; zero is permitted only as an explicit virtual synthetic declaration.

The interpolation contract is exactly these fixed choices plus a declared integer `max_gap_s`:

```json
{
  "kind": "piecewise_linear",
  "knots": "integer_seconds",
  "max_gap_s": 10,
  "extrapolation": "forbidden",
  "missing_policy": "unresolved_no_fill",
  "response_alignment": "exact_report_grid_no_interpolation"
}
```

The shown ten-second maximum is the synthetic fixture's chosen design, not a general recommendation for real sensors. Each boundary may have its own strictly increasing integer-second knots, but every adjacent gap must meet the frozen limit and both endpoints must be present. At most 1,000 knots are accepted per trace. Linear interpolation describes only the bounded representation between supplied valid knots; it does not fill an unknown reading. An explicit null, missing endpoint, oversized gap, or unrepresented initial state makes the entire replay unresolved. Actual values are not smoothed, shifted, rescaled, extrapolated, replaced by targets, or forced to desired endpoints.

## Event contract and clock rules

A calibration event or validation-plan entry has exactly:

```text
{event_id, window, planned_targets}
```

`planned_targets` is null or exactly `{inflows, receiving_stages}` using the v1 run's target-curve shapes. These optional curves must satisfy the same bounded duration and dry-start contract, but need not equal later delivered traces.

For synthetic evidence, `window` is null and receipt `start_at`/`end_at` are null. For measured evidence, the event window is `{start_at, end_at}` using ordered explicit UTC timestamps whose duration exactly equals `duration_s`. A measured boundary receipt cannot be reserved before its event ends according to the server clock. Receipt window strings must exactly match the assigned window. A different actual window is nonconforming evidence, not permission to relabel the frozen assignment.

The public API has no caller-supplied clock. Tests use internal clock doubles that are never part of production intake. Freeze reads its final server instant after source hashing and plan preparation; every measured validation start must be at least 60 seconds later. Windows follow the frozen non-overlapping order. Synthetic virtual events are explicitly exempt from physical future-window checks and do not counterfeit current-time observations.

## Boundary receipt contract

`monsoon.bench-boundaries/1` contains exactly:

```text
schema_version, event_id, evidence_kind, start_at, end_at,
clock, vertical_datum, source_id, notes,
series: [
  {id, quantity, location_id, unit, expanded_uncertainty_abs, source_id,
   points: [{elapsed_s, value}, ...]}
]
```

`evidence_kind` is `synthetic_fixture` or `measured_bench`, determined by the site's evidence branch. The receipt clock repeats `kind`, `origin`, and `time_unit`, and supplies `synchronization_uncertainty_s` and `source_id`. The supplied clock uncertainty must be explicit, finite, and within the frozen limit; its source is retained without independent authentication. All metadata, inventory, units, datum, endpoints, sample ordering, gaps and numeric values are checked before execution.

Boundary `value` is a finite SI number or an explicit null for missing data. Nulls are retained as unresolved; they never become zeros. The model's supported flow, stage and initial-state limits also apply to the internally derived run. Unknown keys, response columns, duplicate JSON keys, booleans used as numbers, nonfinite numbers, and numeric strings are rejected as usable forcing.

The new calibration and validation boundary fixtures intentionally differ from planned target amplitudes (1.1× and 0.8× respectively). Their input numbers are invented. The separately named `synthetic_bench_replay_site_v1.json`/`model_v1.json` use a constant-area compartment with an elevated outlet that remains dry; they check retained-water bookkeeping, not flowing-conduit or backwater accuracy. A hash of semantic boundary content is kept separately from response fingerprints; identical boundaries may legitimately recur and do not authenticate independent responses.

## Response receipt contract

`monsoon.bench-replay-responses/1` contains exactly:

```text
schema_version, event_id, evidence_kind, start_at, end_at,
clock, vertical_datum, source_id, notes,
series: [exact frozen response metadata in its declared order],
samples: [{elapsed_s, observed: {series_id: number_or_null, ...}}, ...]
```

The clock/datum/window checks are the same as for boundaries. Samples cover exactly `0, report_step_s, …, duration_s`, including both endpoints, with every declared response ID once per row. There is no response interpolation, clock alignment by fitting, endpoint replacement, sample deletion or missing-value substitution.

The stage is identified by `receipt_id` before parsing response content. A bounded malformed response, a wrong event ID, an explicit missing reading, or a source/runtime mismatch is retained as an unresolved response attempt. It consumes that receipt's response stage. It cannot be retried with better values. Unserializable objects, excessive sizes, unsafe attachment names, unknown receipt IDs, stale versions, or response calls before a seal are API gate errors, not accepted evidence receipts.

## Persistence, interruption, and verification

The new SQLite ledger has its own schema and append-only events/blobs, with ordinary-connection update/delete guards and a complete chronological hash chain. `expected_version` writes are serialized by SQLite transactions. A freeze cannot pass an open calibration receipt. The server accepts at most 50 calibration attempts and 24 validation assignments in this bounded study slice.

Boundary processing is deliberately two-stage:

1. Commit the exact bounded raw bytes, event/model/recipe identity, boundary validity or errors, derived run if usable, and a reserved private attempt directory. This consumes the validation assignment even if the trace is missing or malformed.
2. Execute the internal model once, retain the successful or failed files, and commit the boundary-only prediction seal before response receipt.

A process interruption between stages leaves `prediction_status: pending`. `close_interrupted_receipt` retains safe bounded partial files and seals it as `interrupted`, with no rerun. It then accepts one response receipt as unresolved. A failed calibration candidate/recipe/event tuple cannot be repeated in the same study, and a failed validation event cannot be replaced. New declared model candidates preserve earlier history; they do not erase failed attempts or create independent events from reused calibration observations.

Every usable v1 prediction must pass the internal adapter verifier and retain the **exact complete 18-file paired artifact inventory**, including both native input/report/output bundles and both worker/result/manifests. The replay prediction seal is additional. Original artifact bytes and their SQLite copies must still match on later reads and before comparison. The unchanged v1 pair remains intact; additional numerical audit evidence is stored separately rather than rewriting its result or manifest.

`bench_balance_audit` replays both exact retained native inputs in separate processes and checks cumulative water balance at every actual routing endpoint, using the explicitly defined `max(1 mL, 1% × (initial + entered water))` numerical allowance. The audit's exact source, rule, runtime and parent-input bindings are frozen alongside the replay recipe. Its complete 18-file bundle is retained separately as `balance_audit_artifacts`. `prediction_qualified` is true only when the original native pair **and** the verified additional audit pass. A native `prediction.valid: true` alone cannot qualify calibration, release residuals or be displayed as a successful replay.

Development exposed a real numerical limitation in the older flowing three-node synthetic pulse: the final-event balance can pass while a larger intermediate discrepancy appears and later cancels. The additive audit keeps that case unresolved. Its original v0.5 fixtures remain unchanged; the exact first v0.6 replay recipe/event/boundary files are retained in `data/templates/replay_development_failures/` with a manifest. The new, separately named analytical-compartment fixture was selected after that discovery and supports only a narrower software example. Changing the example does not repair or erase the failed flowing case. The native adverse regression explicitly verifies that it cannot qualify a freeze or release response residuals.

Source/engine/protocol/audit identity is fixed at study creation and bound again into calibration and freeze. Source changes after import require a fresh process; a changed lineage also requires a new study before reserving calibration or validation events or making a clean freeze. `verify` reports both `current_runtime_matches_study` and, after freeze, `current_runtime_matches_freeze`. Raw JSON bytes supplied as bytes or text are retained exactly; dictionaries are serialized. Up to eight optional basename-to-bytes attachments are accepted, each at most 8 MiB and at most 16 MiB total. `boundaries.json` and `responses.json` are reserved. JSON has a 5 MiB/64-level limit. Attachments are retained evidence; arbitrary CSV attachments are not silently parsed into readings.

Keep the database and its sibling `.artifacts` directory together. `export_evidence(study_id)` returns a verified ZIP snapshot with exact raw inputs, attachments, all native/audit/seal artifacts, study state, chronological events and a per-file SHA-256/size manifest. It checks current lineage and every byte during export and refuses unsealed interrupted records or changed evidence. Original absolute paths inside retained records/results are preserved literally: this ZIP is evidence, not a portable database restore or modified replay bundle. It excludes the database itself, account data and runtime binaries, and has a 512 MiB uncompressed limit.

Hashes and triggers detect local inconsistencies; they do not protect against an administrator rewriting the database, filesystem, source and entire hash history together. There is no account/role authentication, external timestamp witness, instrument verification, owner acceptance or operational authorization in this ledger.

## Residual meaning and reuse

Comparison status is `resolved_errors` or `unresolved`. Complete finite comparisons report per-series `sample_count`, `missing_count`, `rmse`, `bias`, `maximum_absolute_error`, and the declared `expanded_uncertainty_abs`. Bias is **observed minus predicted**. An unresolved series has null metrics. No physical error threshold is implemented.

Residuals are conditional on the supplied actual boundary representation, frozen model and initial-state recipe. Replaying supplied inputs removes reliance on an assumed target schedule, but it does not isolate parameter error from input measurement, timing, datum, storage/escape representation, initialization, sensor or numerical errors. Input uncertainty is not propagated. A numerically qualified replay is not proof of a physically accurate model.

Semantic response fingerprints ignore event/source/series labels and series order, and normalize integer/float numeric spelling and negative zero. A match between calibration and withheld partitions, or repeated withheld response, is retained as **suspected reuse**, with no numeric residual release. Calibration observations may be reused across manually declared candidate models, but that is not an independent event count. Identical physical readings can occur independently; this conservative local guard does not prove copying and cannot detect every transformed near-copy or information viewed outside the ledger. Identical boundary content is not itself a response reuse violation.

All study, receipt and comparison claims keep physical validation, operational activation, full protocol completion, external prospectivity, evidence authenticity, automatic fitting, parameter-error isolation, boundary-uncertainty propagation, and planned-target reproduction assessment false.

## Public API

```python
from monsoon.bench_replay import BenchReplayStore, BenchReplayError, validate_replay_recipe

with BenchReplayStore("var/bench-replay.sqlite3") as store:
    study = store.create_study(site_json, title="Declared research study")
    calibration = store.record_calibration_boundaries(
        study["study_id"], study["version"], model_spec=model_json,
        recipe=recipe_json, event=calibration_event, boundaries=boundary_bytes,
        raw_files=None,
    )
    study, receipt = calibration["study"], calibration["record"]
    recorded = store.record_responses(
        study["study_id"], study["version"], receipt_id=receipt["receipt_id"],
        responses=response_bytes, raw_files=None,
    )
    study = recorded["study"]
    frozen = store.freeze_study(
        study["study_id"], study["version"],
        selected_model_sha256=receipt["model_sha256"],
        selected_recipe_sha256=receipt["recipe_sha256"],
        validation_plan=future_events, rationale=manual_selection_rationale,
    )
    study = frozen["study"]
    received = store.record_validation_boundaries(
        study["study_id"], study["version"], event_id=next_assigned_event_id,
        boundaries=actual_boundary_bytes, raw_files=None,
    )
    # Only after the retained boundary-only seal, receive the withheld responses:
    study, receipt = received["study"], received["record"]
    completed = store.record_responses(
        study["study_id"], study["version"], receipt_id=receipt["receipt_id"],
        responses=withheld_response_bytes, raw_files=None,
    )
```

These variables are input placeholders, not example real data. Freeze requires an earlier complete nonempty internally generated calibration residual record for the exact chosen model/recipe. A failed run, missing response or suspected reuse cannot qualify it.

The interrupt close API is `close_interrupted_receipt(study_id, expected_version, receipt_id=..., reason=...)`. Other methods are `get(study_id)`, `list_studies()`, `verify(study_id)`, `export_evidence(study_id)` (ZIP bytes), and `close()`. Gate failures raise `BenchReplayError`, a `ValueError` carrying `code`; accepted failed receipts return their retained unresolved record.

Writes return `{study, record}` except freeze, which returns `{study, freeze}`. `get` returns `calibrations`, `validations`, `freeze`, `pending_validation_event_ids`, `pending_response_receipt_ids`, `version` and `head_sha256`, plus the site/protocol identity and unchanged false claims. Study status is `calibration`, `withheld_pending`, or `withheld_records_complete`. Completion means assigned receipts were consumed, including failures; it does not mean any acceptance passed.

Receipt `boundary_status` is `valid` or `invalid`. `prediction_status` is `pending`, `sealed`, or `interrupted`; a sealed prediction can still be numerically failed. `prediction_qualified` explicitly gates on both the original native pair and additional `balance_audit`. `response_status` is `pending`, `received`, or `invalid`; a structurally received response can still be unresolved due to missing readings or suspected reuse. Check the comparison and qualification fields rather than treating receipt status as a success flag.

The targeted `tests/test_bench_replay.py` suite exercises the new workflow separately from historical tests. It includes the actual pinned native SWMM pair with explicitly circular generated responses, plus adverse coverage, clock, datum, role injection, malformed receipt, interruption, artifact mutation, stale-write and future-freeze cases. No test creates real operator or physical measurement evidence.
