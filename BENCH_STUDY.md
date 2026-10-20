# Separate bench research study ledger

`monsoon.bench_study` provides a bounded **calibration records → model freeze → withheld records** workflow for the new bench adapter. It is a separate dry-start model-development study. It does not alter the earlier planner, source evidence, physical protocol, measurement importer, or v0.1–v0.4 results.

**Predictions use the predeclared inflow and receiving-stage forcing. This version does not ingest or verify measured boundary traces or assess whether the apparatus reproduced that forcing.** Response errors can therefore describe disagreement with that declared experiment, but cannot isolate parameter error from a different delivered input. Every comparison carries this limitation and `acceptance_assessed: false`.

The ledger does not perform automatic fitting or choose the best model. A researcher records manually declared model candidates and their calibration errors, then selects one exact previously run model with a written rationale. Zero numerical error against generated synthetic observations is a software exercise, not calibration of a physical apparatus.

The adapter currently supports dry-zero-flow initialisation, with its explicit numerical initial-storage allowance. It does not implement the equilibrated-control family. A completed record sequence here **cannot mean completion of the 24-event physical protocol**, physical validation, operational activation, facility approval, or permission to conduct work.

## What is bound and retained

The store retains the exact site JSON bytes, parsed site identity, unchanged physical protocol identity, manually supplied model, run settings and forcing, observation JSON bytes, optional source attachments, numerical result artifacts, and comparison records. Each record identifies the currently loaded study source, adapter/worker/source files, SWMM/toolkit/native runtime and protocol file hashes.

Successful predictions come from the internally imported `monsoon.bench_model` adapter. The caller cannot submit prediction columns, provide a prediction callback, replace a frozen run spec, or inject an alternative runner through the public API. The adapter runs the declared routing step and an automatic half-step verification. Both attempts' artifacts are retained. Numerical agreement is a bounded project check, not proof of physical accuracy or universal convergence.

Before observations are joined, the store checks the adapter's paired-run integrity, site/model/run identity, exact reporting grid, saved result equality and complete artifact manifest. It retains native input, report, output and related files, copies their bytes into the SQLite evidence store, then creates and rereads a hashed prediction seal. A later mutation of an original prediction file or stored source blob blocks subsequent calculations.

Events form an append-only hash chain. SQLite write transactions enforce `expected_version` atomically and serialise model runs with freeze operations. A concurrent freeze cannot pass an unfinished calibration calculation. Update/delete triggers protect stored events and blobs through the ordinary database connection. These controls detect local inconsistencies; they are **not protection against a machine/database administrator rewriting the entire store, source code and hash history**.

This store has no account or role authentication. It is separate from `operations.py` and makes no system-wide security claim. Evidence source IDs, hashes, supplied collection times and accepted model parameters do not authenticate people, instruments, professional qualifications or actual collection. The public API has no caller-supplied clock. Test clock substitution is confined to software tests.

## APIs and return shapes

```python
from monsoon.bench_study import BenchStudyStore, BenchStudyError

with BenchStudyStore("var/bench-study.sqlite3") as store:
    study = store.create_study(site_package, title="Name of this research study")

    recorded = store.record_calibration(
        study["study_id"], study["version"],
        model_spec=model_spec,
        event=calibration_event,
        observations=observation_json,
        raw_files=None,
    )

    frozen = store.freeze_study(
        study["study_id"], recorded["study"]["version"],
        selected_model_sha256=recorded["record"]["model_sha256"],
        validation_plan=validation_assignments,
        rationale="Recorded reason for this manual parameter choice",
    )

    withheld = store.record_validation(
        study["study_id"], frozen["study"]["version"],
        event_id=next_assigned_event_id,
        observations=withheld_observation_json,
        raw_files=None,
    )
```

The names above are input variables, not example collected data. Do not run a measured study with invented values.

Additional methods are `get(study_id)`, `list_studies()`, `verify(study_id)`, and `close()`. Invalid inputs, stale versions, changed lineage and disallowed state transitions raise `BenchStudyError`, which is a `ValueError` with a `code` attribute. An accepted schema-valid observation record with a failed model run, missing readings or suspected response reuse is instead retained with an unresolved comparison.

`create_study` and `get` return state containing:

```text
study_id, title, evidence_kind, version, status, created_at, head_sha256
site_package, site_package_sha256, site_blob_sha256
protocol, protocol_sha256, scope
calibrations: list of immutable records
validations: list of immutable records
freeze: null or immutable freeze record
pending_validation_event_ids: ordered list
```

`list_studies()` returns only `study_id`, `title`, `evidence_kind`, `version`, `status`, and `created_at` for each study. `record_calibration` and `record_validation` return `{study, record}`. `freeze_study` returns `{study, freeze}`. Reading state adds `record_sha256` and `recorded_at` to each saved record.

State status is `calibration`, `withheld_pending`, or `withheld_records_complete`. The last means each assigned receipt is recorded, including unresolved/failed attempts. It does not mean the model passed acceptance or that an experiment succeeded.

`verify` returns `valid`, `integrity_valid`, `current_runtime_matches_freeze`, `study_id`, `errors` and, when readable, `version`/`head_sha256`. Before freeze, `current_runtime_matches_freeze` is null. After freeze, a source/runtime mismatch blocks validation even if the historical bytes remain intact. Use a verified `get()` result for a JSON download. Keep the database and its sibling `.artifacts` directory together; this module does not claim a backup/restore service.

## Study evidence kind

The site package determines the study branch:

| Site evidence kind | Study/observation evidence kind | Collection window |
|---|---|---|
| `synthetic_fixture` | `synthetic_fixture` | `window: null`; observation UTC fields are null. |
| `supplied_survey` | `measured_bench` | Explicit timezone-aware `start_at` and `end_at`. |

The bench model and run must also pass the adapter's matching site/model/evidence contract. A supplied-survey branch is still unverified supplied evidence; changing a label does not establish that measurements exist.

Synthetic virtual event time makes an explicitly generated software exercise runnable immediately. It does not counterfeit current-time physical measurements or claim that the exercise was an independently blinded trial. Production measured calls use the server's actual clock; the synthetic exercise does not override it.

## Event and response contract

A calibration `event`, or one entry in `validation_plan`, has exactly:

```text
{
  event_id: distinct identifier,
  run: complete monsoon.bench-run/1 object,
  window: null OR {start_at: timezone-aware timestamp, end_at: timestamp},
  series: [
    {id, quantity, location_id, unit, expanded_uncertainty_abs, source_id}
  ]
}
```

The `run.run_id` equals `event_id`; `run.model_sha256` identifies the exact model candidate. Its duration, forcing, initialisation and report grid must validate against `monsoon.bench_model`. The measured UTC window must have that same duration. No automatic datum/unit conversion is performed.

Declare 1–64 distinct response series. Each expanded absolute instrument uncertainty must be finite and positive, with a supplied source ID. Its authenticity or coverage is not verified here, and uncertainty-aware physical acceptance is not computed by this ledger.

| Quantity | Location | Unit | Role |
|---|---|---|---|
| `stage_m` | A declared non-outfall node | `m` | Response stage on the site's exact datum. |
| `outflow_m3_s` | A declared outfall | `m3/s` | Signed model exchange; positive outward, negative backflow. |
| `spill_m3_s` | A declared spill node | `m3/s` | Modelled external spill. |
| `storage_m3` | `SYSTEM` | `m3` | Total represented retained water. |

Prescribed inflow and receiving-outfall stage cannot be scored as independent responses. A sparse response selection is permitted for this research slice; it is not a complete control-volume measurement package. Full balance, all boundary coverage, uncertainty propagation, paired mechanisms, reset evidence and physical acceptance remain outside this ledger.

## Observation contract and blank shape

`observations` may be a dictionary, UTF-8 JSON text, or raw JSON bytes. Duplicate keys, unknown fields, prediction columns and nonfinite numbers are rejected. Original JSON bytes are retained when supplied; a dictionary is stored as canonical JSON.

This **unfilled schema illustration is invalid until an actual event contract and all required sample times are supplied**. It is not a measurement fixture:

```json
{
  "schema_version": "monsoon.bench-observations/1",
  "event_id": "REPLACE-WITH-ASSIGNED-ID",
  "evidence_kind": "synthetic_fixture",
  "start_at": null,
  "end_at": null,
  "source_id": "UNFILLED-SOURCE",
  "notes": "Unfilled example. No physical observations were collected.",
  "samples": [
    {"elapsed_s": 0, "observed": {"REPLACE-WITH-SERIES-ID": null}}
  ]
}
```

Supply every sample at `0, report_step_s, …, duration_s`, including both endpoints, with exactly the declared series IDs. Unknown readings are explicit nulls. There is no interpolation, extrapolation, endpoint forcing, sample deletion, unit conversion or zero substitution. Missing samples or malformed structure are rejected before a receipt; a complete grid containing null readings is retained as unresolved. All-missing data cannot qualify a model for freeze.

For measured records, the observation timestamps must exactly match the assigned window and the event must have ended by server receipt. A mismatched/nonconforming collection must be preserved separately as development evidence; it cannot be relabelled into the frozen assignment through this API. A late record can report an earlier event, but cannot change the immutable model or assignment.

Optional `raw_files` is a mapping of up to eight safe basenames to nonempty bytes. No paths, traversal names, URLs or automatic downloads are accepted. `observations.json` is reserved for the supplied observation file. Attachments are limited to 8 MiB each and 16 MiB total; JSON intake/persisted event records have a 5 MiB bound. Prediction artifacts are separately bounded. The store hashes source bytes; it does not prove their truth or derive response values from arbitrary attached CSVs.

## Freeze and withheld rules

1. Record at least one complete, nonempty calibration error record generated using the internal paired numerical adapter. A failed run, missing-only comparison or suspected reused validation response cannot qualify the selected model. All earlier candidate/error records remain present.
2. Select one exact calibrated candidate hash with a written rationale. No automated ranking or optimisation occurs. The selected model includes its exact completed-job state; other intervention states require their own appropriate declared model-development study.
3. Freeze 1–24 distinct future validation assignments, their exact forcing, run windows, expected response columns, uncertainties and order. Validation IDs cannot reuse any calibration event ID. The freeze binds all calibration record hashes, selected prediction seals, site, model, source, runtime and unchanged protocol identity.
4. The final server freeze time is read **after** source hashing and contract preparation. For measured studies every assigned start must be **at least 60 seconds later** than that final instant. Measured windows must be in the declared non-overlapping order. This is a local workflow guard, not a witnessed physical timestamp or an instruction to begin work.
5. Receive each assigned validation event once, in frozen order. Its run/parameters/forcing are taken only from the freeze; observations cannot replace them. A failed or unresolved accepted receipt consumes the assignment. It cannot be silently skipped, overwritten or retried with a more favourable replacement.
6. After freeze, calibration is closed. Changing parameters, geometry, solver/source, protocol or the validation design requires a new prospective study. Historical results and failures remain attached to their old identities.

The workflow can enforce local order and identity, but cannot prove that an external person did not collect, view, copy or manipulate data earlier. Supplied UTC times and hashes are not independently witnessed prospectivity. There is no automated permit or professional sign-off.

### Suspected reuse

The store fingerprints response content by quantity, location, unit and exact sample times/values. Renaming an event, source or series, or reordering series, does not hide an identical semantic response. The same calibration observations may be reused across manually declared candidate models; that is ordinary model development, not an independent event count.

A content match across calibration/withheld partitions, or a repeated withheld response, is retained as **suspected reuse** with an unresolved comparison and no numeric comparison release. Identical values alone do not prove reuse: independent dry/no-spill runs can match. This conservative guard cannot authenticate independence, and has no override that converts the record into clean withheld evidence. It prevents that local record from qualifying a calibration model and prevents replacement of an already received withheld assignment. It cannot detect every transformed copy or information known outside this store.

## Comparison and record fields

Each record includes `record_id`, `partition`, `evidence_kind`, `model_spec`, `model_sha256`, `event`, `observations`, `received_at`, `lineage`, `prediction_origin`, `prediction`, `prediction_artifacts`, `prediction_seal_sha256`, `observation_response_sha256`, `suspected_reuse_matches`, `attachments` and `comparison`.

The comparison contains:

```text
status: resolved_errors OR unresolved
summary, errors, limitations
acceptance_assessed: false
physical_validation_established: false
series: [
  {series_id, quantity, location_id, unit, status,
   sample_count, missing_count, rmse, bias, maximum_absolute_error,
   expanded_uncertainty_abs}
]
```

Bias uses observed minus predicted. An unresolved series has null error metrics. These summaries are retained for model development; they do not implement the physical protocol's complete uncertainty bounds or acceptance thresholds. `resolved_errors` means finite error arithmetic was calculated over the complete declared grid, not that the errors were small, the model was fitted, the observed forcing matched, or the model was validated.

Every study/record keeps `operational_activation_allowed`, `physical_validation_established`, `full_protocol_completed`, `external_prospectivity_verified`, `evidence_authenticity_verified` and `automatic_fit_performed` false. No local declaration makes those flags true.

## Verification performed

The focused `tests/test_bench_study.py` suite has 44 passing tests at source freeze. It includes a real SWMM paired-run calibration/freeze/withheld roundtrip with explicitly invented observations. Other tests cover caller-prediction rejection, exact grid enforcement, manual candidate history, failed engine and missing-data retention, immutable freeze/order, suspected response reuse despite renamed/reordered labels, later validation-to-calibration reuse, atomic concurrent writes, source/runtime changes, raw/artifact alteration before and after comparison, server clock rollback, measured future-window checks and preparation-time freeze races.

These tests demonstrate software behavior and numerical lineage. No real operator, measured apparatus, physical acceptance, bench commissioning, 24-event protocol completion, or supervised pilot is claimed by this implementation or its synthetic exercise.
