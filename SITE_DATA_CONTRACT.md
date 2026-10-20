# Site-data intake contract v1 — draft pending operator acceptance

This contract and importer are implemented for review. No operator has accepted the contract, no surveyed site package has been supplied, and no import can activate a hydraulic model or authorise a job. The bundled example is entirely synthetic. Its invented reviewer, approval, survey, sensor and future timestamps are software fixtures.

`data/site_contract_v1.json` is the JSON Schema for `monsoon.site/1`. `monsoon.site_data.validate_site_package` also checks relationships that JSON Schema alone cannot establish. The importer supports a bounded network of junctions, storage nodes, outfalls and surveyed links, with open rectangular, circular or trapezoidal cross-sections. Other cross-sections, regulators, pumps, multiple disconnected catchments, rainfall-runoff models, terrain/surface pathways and live geometry changes need a later explicit contract and model adapter. Unsupported data remains an invalid draft; it is never approximated into the synthetic reference.

## Evidence and activation semantics

| Report field | Meaning |
|---|---|
| `valid: true` / `ready_for_review` | Supplied fields satisfy this bounded structural and relational contract. |
| `valid: false` / `draft_invalid` | Required data are missing, unsupported, malformed or inconsistent. Issues identify `path`, `code` and `message`. |
| `contract_status` | Always `draft_pending_operator_acceptance` in v1. Owner acceptance belongs in a separate authenticated review record; changing this label does not manufacture acceptance. |
| `evidence_kind: synthetic_fixture` | Invented example. All source kinds must also be synthetic. |
| `evidence_kind: supplied_survey` | The submitter claims survey provenance. This is not verified survey truth. Synthetic sources cannot support the claim. |
| `operational_activation_allowed` | Always false. There is no site-to-SWMM activation function in this module. |
| `physical_validation_established` | Always false. Completeness, checksums and numerical checks do not establish physical evidence. |

Source URIs are inert references. Import does not fetch a URL, open a supplied path, trust executable content, inspect a photograph, verify source bytes, authenticate a surveyor or confer engineering authority. `sha256` names declared source bytes; an independent provenance review must compare the actual retained attachment bytes and permitted use. The application's operational-control layer can bind attachments and reviewer identities separately. It does not turn this schema check into field validation.

## Exact input rules

Inputs are a JSON object, UTF-8 JSON text or bytes. Duplicate object keys, non-finite numbers (`NaN`, infinity or overflow), non-string dictionary keys, unknown fields, more than 64 nested levels, and payloads above 5 MiB are rejected. The shared operations layer may impose a stricter upload limit. Numeric fields reject booleans and strings, and use an absolute software bound of `1e12` in the field's declared SI unit to keep calculations representable; this is not a physical plausibility endorsement.

Every required field must be present. `null` means unknown. Unknown hydraulic geometry, datum, calibration or intervention evidence blocks readiness; it is not replaced by zero, an average or a plausible default. Null is explicitly valid only for `supersedes_sha256` on a first version, and the storage-only fields on non-storage nodes. An empty jobs array means that this package proposes no discretionary intervention.

Stable IDs begin with a letter and contain up to 64 letters, digits, underscore, full stop, colon or hyphen. Node IDs, link IDs, job IDs and source IDs are unique within their own record types. They remain stable across revisions. Source references, endpoints, prerequisites, job targets and boundary records must resolve. Do not reuse a retired ID for a different physical asset.

| Block | Required content and checks |
|---|---|
| Package | `schema_version`, stable `site_id`, `revision`, prior canonical `supersedes_sha256` or null, title, evidence kind, draft status, offset-aware `created_at`, notes. |
| Units | Exactly length `m`, area `m2`, volume `m3`, flow `m3/s`, time `s`, roughness `s/m^(1/3)`. Convert and document upstream; import does not guess units. |
| Coordinates | CRS identifier plus definition, `easting_northing` axis order and metre horizontal unit. A local bench CRS must state its origin/axes. A supplied projected site CRS must identify the actual survey reference. These declarations are checked for presence, not geodetic accuracy. |
| Vertical datum | One explicit common datum string for invert, ground, storage stage, measured stage and receiving-water stage. No assumed datum transformation or offset. |
| Sources | ID, kind, URI/reference, content SHA-256, observation timestamp with UTC offset, author and description. Observation cannot postdate package creation. Supplied survey sources distinguish survey, inspection and engineering approval. |
| Nodes | ID, kind (`junction`, `storage`, `outfall`), metre coordinates, invert and ground levels, source ID. Ground must exceed invert. |
| Storage | Absolute stage–area pairs in the common datum. Stages increase strictly, areas are positive, first stage equals surveyed invert, and the curve reaches declared overflow/ground level. The outgoing designed-outlet link must exist. No unmeasured lower volume is inferred. |
| Links | ID, from/to nodes, positive surveyed length and roughness, absolute inlet/outlet invert levels, supported measured cross-section and source ID. End inverts lie between their node invert and ground. Self-links, missing endpoints, disconnected components and nodes with no declared downstream path to an outfall fail. Adverse slopes are not silently corrected. |
| Boundaries | Explicit inflow nodes, all receiving outfalls, all potential collector-spill nodes, and an inventory source. Each list is nonempty and unique. Outfall list equals the complete outfall node set. Reviewer must establish that the inventory is physically complete. |
| Jobs | Link ID, title, current and approved target cross-sections, supporting before/after sources, explicit geometry approval, reviewer, approval time/source, nominal and upper-bound on-site seconds, prerequisite job IDs. Current geometry must equal the surveyed link state; target must differ. Upper bound includes setup, work, inspection, disposal and restoration, with route travel handled separately when a future adapter is defined. |

Only one job per physical link is permitted. Prerequisites must exist, be unique, and form an acyclic graph. Designed storage-outlet changes are excluded from this maintenance contract and need separate engineering design. A proposed target section is not evidence that restoration has happened. This importer never marks a ticket complete or accepted.

The node/link representation, head boundary, inflow boundary and initial-state distinctions follow EPA's hydraulic-model description; the narrow import limits and approval rules above are this project's design choices. [EPA SWMM Reference Manual Volume II, sections 2.1–2.3 and 5](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P100S9AS.txt).

## Staging and change review

`validate_site_package(payload)` returns a deterministic JSON-serialisable report. `package_sha256` is SHA-256 over UTF-8 JSON with sorted keys, compact separators, Unicode retained and non-finite values disallowed. It binds the entire parsed package, including evidence declarations. It differs from a hash of a prettified file's raw bytes.

`stage_site_package(payload, staging_dir)` snapshots the caller's input once, validates that snapshot and writes `site.json` plus `validation.json` in a directory named by its canonical hash. Parsed invalid drafts can be saved to preserve omissions and rejection reasons. Malformed JSON cannot be saved as a package. Caller changes made after the snapshot cannot change the bytes beneath its validated identity. No file outside the chosen staging directory is selected by an uploaded value.

`compare_site_versions(old, new)` produces all supplied-field changes with old/new values and human-readable summaries. Records are compared by stable ID. It checks the same site ID and explicit supersession hash, returns old/new validity and hashes, and always requires review. Pure record reordering has no semantic change list even though the whole-package identity changes. No comparison accepts a revision or changes the current case.

Before a real adapter can be activated, the responsible reviewer must separately accept the network boundary, survey/datum, proposed interventions, initial conditions, forcing, overflow destinations, sensor coverage and physical-validation evidence. Imported site state must have its own version and evidence; the frozen synthetic reference and its H2 failure remain regression evidence. This v1 release stops at staging and review preparation.

## Files and callable interfaces

- `data/templates/synthetic_site_v1.json`: valid, minimal three-node schema example, not the proposed two-branch bench experiment.
- `data/templates/synthetic_source_evidence.txt`: genuine fixture bytes proving only that the example is labelled synthetic.
- `data/templates/synthetic_measurements_v1.json`: invented arithmetic observations bound to the sample site's canonical hash.
- `monsoon.site_data.validate_site_package(payload) -> dict`
- `monsoon.site_data.stage_site_package(payload, staging_dir) -> dict`
- `monsoon.site_data.compare_site_versions(old, new) -> dict`
- `monsoon.measurements.validate_measurement_package(payload, site_package=None) -> dict`
- `monsoon.measurements.analyze_measurements(payload, site_package=None) -> dict`

Measurement analysis requires the matching site package. Read `PHYSICAL_VALIDATION.md` before interpreting its result. Targeted importer tests are in `tests/test_site_data.py` and `tests/test_measurements.py`; their success establishes software behavior only.
