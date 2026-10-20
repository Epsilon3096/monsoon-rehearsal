# Continuous bench preparation — additive v0.6 capability

This adapter can prepare a wet state through a complete prescribed history beginning nominally dry, then evaluate a later event inside the **same uninterrupted SWMM run**. Geometry, storage curves, roughness and loss assumptions are fixed before preparation starts. It never assigns wet node depths, overwrites conduit flows, imports a hotstart, remaps water between geometries, or restarts the engine at the event boundary.

The demonstrated positive case is deliberately narrow: one analytical constant-area compartment, with an elevated outlet that remains hydraulically dry apart from SWMM's retained numerical depth floor. More complex candidates with moving conduit water and rising receiving water failed stricter conservation or resolution checks and remain unresolved. The simple geometry was selected during software-test development after those failures; it is not a surveyed, fitted or physically validated apparatus. No real observations, sensor calibration, participants, engineering approval or field benefit exist in this evidence.

The existing v0.5 adapter, worker, fixtures, historical evidence and frozen 24-event protocol are unchanged. A passing preparation calculation does not complete that physical protocol. Measured wet-start response validation and general wet-conduit/backwater accuracy remain unestablished.

## Public API

```python
from pathlib import Path
import json
from monsoon.bench_initialization import (
    validate_prepared_bench_run,
    run_prepared_bench,
    verify_prepared_bench_result,
    prepared_bench_engine_identity,
)

templates = Path("data/templates")
site = json.loads((templates / "synthetic_bench_prepared_site_v2.json").read_text())
model = json.loads((templates / "synthetic_bench_prepared_model_v2.json").read_text())
prepared_run = json.loads((templates / "synthetic_bench_prepared_run_v1.json").read_text())
contract = validate_prepared_bench_run(site, model, prepared_run)
result = run_prepared_bench(site, model, prepared_run, output_dir)
integrity = verify_prepared_bench_result(result)
```

All three inputs accept parsed JSON objects, JSON text or UTF-8 JSON bytes. Validation is inert. Execution creates a fresh evidence folder; the caller supplies its containing directory. There is no cache, caller-provided runner, online calibration, execution permission or operational activation. The additive callable API is available for a separately reviewed measured-boundary adapter; it does not automatically make a cold-start replay contract a prepared-event contract.

## Preparation contract

`monsoon.bench-prepared-run/1` is a wrapper around an unchanged `monsoon.bench-run/1` history. Its complete keys are:

| Field | Meaning |
|---|---|
| `schema_version` | Exactly `monsoon.bench-prepared-run/1` |
| `prepared_run_id` | Stable site-style identifier |
| `evidence_kind` | Exactly the model's label: `synthetic_fixture` or `supplied_bench_model` |
| `continuous_run` | Complete valid bench-run/1 from elapsed zero to the full preparation-plus-evaluation horizon |
| `event_start_s` | Positive integer strictly before the horizon and exactly on the reporting grid |
| `preparation` | Exactly `kind`, `source_id`, `equilibrium` |
| `notes` | Explicit interpretation of the supplied history |

`preparation.kind` is exactly `continuous_dry_start`. Its source must reference a supplied site source. The source is hash-bound as part of the site; this adapter does not fetch it or authenticate its truth. Initial zero inflow, zero specified node depth/link flow, receiving stage at or below outfall invert, numerical initial-water allowance, input coverage, all geometry restrictions and all v1 limits apply to the **entire** continuous history.

Every forcing series begins at zero and ends at the full horizon, with strictly increasing integer-second knots. The engine receives the same piecewise-linear forcing before and after the event split. An event whose earlier history is absent cannot be reconstructed by assigning an arbitrary initial head or silently filling missing inputs. A different model geometry requires its own separate dry-to-wet run; no history stitching is supported.

The only equilibrium recipes are:

```json
{"kind": "not_claimed"}
```

or:

```json
{
  "kind": "required_constant_forcing",
  "window_s": 20,
  "stage_range_tolerance_m": 0.0001,
  "storage_range_tolerance_m3": 0.000001,
  "flow_range_tolerance_m3_s": 0.0000001
}
```

`not_claimed` accepts only that one key. It makes no numerical or physical equilibrium assertion. For the required recipe, every boundary must be exactly constant throughout the final `window_s` of preparation, including all interior knots and both endpoints. The window must be report-grid aligned, at least `max(10 s, twice the report interval)`, and no longer than preparation. Stage, storage and flow tolerances must respectively lie within `[1e-8, 1e-4] m`, `[1e-10, 1e-6] m³`, and `[1e-12, 1e-7] m³/s`; permissive caller settings cannot exceed these source-defined caps.

The worker checks ranges at **every actual routing endpoint** throughout that window: all node heads and depths, conduit depths, individual node and conduit volumes, total stored water, individual conduit flows, every node's total inflow/outflow/lateral flow, signed outfall exchange and collector spill. It verifies the exact expected endpoint count and window boundaries. Matching coarse-report endpoints cannot hide oscillation between them. Both primary and half-step attempts must pass. Success is labelled `numerically_stationary_window`; it does not prove measured equilibration, asymptotic stability, or continued stationarity beyond the specified window.

Unknown fields, incomplete contracts, JSON duplicate keys, boolean/nonfinite numeric values, unbound hashes and unsupported states fail closed. JSON remains limited to 5 MiB and 64 levels. The original 20-node/30-link, 3600-second, 50000-primary-step/100000-refinement-step limits still apply. Expanded prepared-state output additionally permits at most 10000 combined node/link reporting records across the complete history.

## Time and complete event state

The preparation ends at an exact routing and reporting endpoint. The worker records that live state once and uses it as both preparation's final state and evaluation's initial state. No interval is dropped or counted twice. All node and conduit water, including the engine's actual nominal-dry numerical water, stays in the control volume.

The result fields have explicit clocks:

| Field | Clock and content |
|---|---|
| `full_timeseries` | `elapsed_s` runs from dry simulation start through the full horizon |
| `timeseries` | `elapsed_s` starts at event zero; `simulation_elapsed_s` preserves the original clock |
| `initial_state` | Exactly the first event row, at event-relative zero |
| `dry_initial_state` | The live nominal-dry state before the first routing step |
| `initialization` | Event split, total/evaluation durations, fixed-geometry label and `state_reset_performed: false` |

Every state includes node head/depth, node total inflow/outflow/lateral flow, link depth/signed flow, individual node and conduit volumes, total storage, engine-applied lateral inflow, prescribed inflow/stage, signed receiving exchange and collector spill. Prescribed inputs and outfall boundary head retain their non-independent-response column roles. Positive `outflow_m3_s` means control-volume discharge; negative values mean receiving-water inflow. The receiving reservoir is outside the control volume.

The same engine session advances throughout both phases. EPA's `swmm_step` interface reports elapsed **days** and returns zero on its successful final step; the worker converts and verifies fixed endpoints. Model response samples are never interpolated. [EPA SWMM 5.2.4 `swmm5.c`](https://raw.githubusercontent.com/USEPA/Stormwater-Management-Model/v5.2.4/src/solver/swmm5.c)

## Conservation and numerical acceptance

`phase_balances.preparation`, `.evaluation`, and `.whole` independently retain initial/final water, prescribed and applied inflow, signed receiving exchange split into backflow and discharge, collector spill, per-boundary volumes, actual-routing peak heads/depths and routing-step counts. Evaporation, seepage and leakage remain explicitly `excluded_zero`; the whole-history native evaporation/seepage totals must also be exactly zero. No physical zero-leak finding is inferred.

For each phase and for **every cumulative routing endpoint inside it**, the check is:

`residual = initial storage + applied lateral inflow + receiving backflow - receiving discharge - collector spill - current node/conduit storage`

`tolerance = max(0.000001 m³, 0.01 × (phase initial storage + cumulative entering water))`

Endpoint and cumulative checks are separate. A run with a good final residual but an earlier excessive residual is unresolved. `cumulative_balance_audit` records checked and failed endpoint counts, maximum absolute residual, largest residual/tolerance ratio, its signed residual and tolerance, and first/last failed times. Cumulative values use the actual routing intervals: trapezoidal applied lateral/spill flows and exact positive/negative portions of the linearly interpolated signed outfall endpoint flow. Coarse report rows are not used to reconstruct these ledgers. The preparation/evaluation flow integrals must add to the whole-history integrals, and their shared storage state is not counted as a second external input.

Native total storage is the sum of node and link water. Raw routing storage remains internal ft³ in the pinned toolkit, while live `VOLUME` getters provide project units. Its conversion factor is the recorded rounded `0.02832 m³/ft³`. [EPA `massbal_getStorage`](https://raw.githubusercontent.com/USEPA/Stormwater-Management-Model/v5.2.4/src/solver/massbal.c), [EPA conversion table](https://raw.githubusercontent.com/USEPA/Stormwater-Management-Model/v5.2.4/src/solver/swmm5.c)

The native routing percentage is **insufficient as a bench-scale conservation test**: the pinned upstream implementation replaces the percentage with a tiny value whenever the absolute residual is below 1 internal ft³, approximately 28.32 L under its conversion. Independent local native probes reproduced a material residual while that percentage remained tiny. This is why the new endpoint and cumulative-volume gates are mandatory; a small displayed engine percentage cannot overrule them. [EPA `massbal_getFlowError`](https://raw.githubusercontent.com/USEPA/Stormwater-Management-Model/v5.2.4/src/solver/massbal.c)

All v1 finite-output, nominal-dry initialization, prescribed/applied forcing, native routing-total reconciliation, warning/error, nonconvergence and unsupported lateral-overtopping checks remain mandatory over the entire history, including preparation. Positive and negative outfall exchange preserve the reviewed v1 mapping; outfall bookkeeping can make both total-flow getters positive during backflow, so subtracting them would erase receiving inflow. [EPA `node_getSystemOutflow`](https://raw.githubusercontent.com/USEPA/Stormwater-Management-Model/v5.2.4/src/solver/node.c)

The public executor always runs a primary and an automatically halved step in isolated processes. The complete geometry, forcing history, preparation recipe and split are identical; only the routing step and its model-hash binding change. The v1 2% comparisons and absolute floors remain, with additional comparisons of every sampled node/conduit volume and node-flow diagnostic, each phase's volumes and actual-routing peak heads, and the full event-initial state. Stage scaling uses depth relative to the node invert, so absolute elevation datum does not relax a tolerance. Either failed attempt or comparison makes the pair unresolved; neither is silently substituted for the other.

## Demonstrated software behaviour and retained adverse evidence

The positive analytical fixture uses `synthetic_bench_prepared_site_v2.json`, `synthetic_bench_prepared_model_v2.json`, `synthetic_bench_prepared_run_v1.json`, and `synthetic_bench_prepared_compartment_source_v2.txt`.

The 0.1 m² compartment starts at invert 0.04 m. A 7 L pulse is supplied during 0–50 s; the event starts at 100 s and supplies a separate 2 L pulse during 100–115 s. The horizon is 160 s. The analytical compartment heads are `0.04 + 0.007/0.1 = 0.11 m` at event start and `0.04 + 0.009/0.1 = 0.13 m` at the end, both below the elevated conduit inlet at 0.23 m. The primary run produces about 0.10997936 m and 0.12997347 m. The node-water discrepancy is less than 3 mL, the stage discrepancy less than 0.03 mm, and the actual 2.9264 mL numerical conduit water is retained separately. Total event-initial water is about 7.000862 L; final total water is about 9.000273 L. All routing-prefix balances, both complete attempts, their state comparisons and the required 80–100 s stationary window pass. This establishes this bounded software case only.

The following failures remain visible:

- `synthetic_bench_prepared_oscillating_{site,model,run}_v2.json` preserves the earlier three-node raised-outlet candidate. Although phase-end balances pass, the primary preparation has 154 excessive cumulative residual endpoints from about 2.26–3.79 s; the worst is about 1.481 mL against the 1 mL floor. Its cause is not established. Requesting equilibrium also exposes persistent moving-water state variation.
- `synthetic_bench_prepared_tailwater_unresolved_v2.json`, bound to the unchanged original v1 site/model, raises receiving stage to 0.06 m and later lowers it. Its preparation residual at 50 s is about −1.91445 L and its evaluation residual about +1.91493 L, despite a whole-history endpoint residual of about +0.000476 L. Both split and cumulative checks reject it. Independent native probes matched that residual and the all-water volume, so it is not reclassified as a reporting-clock or units mistake. Wet-conduit/backwater adequacy remains unresolved.
- Shorter-connector and higher-roughness diagnostic candidates passed cumulative checks but failed one or more half-step flow comparisons. Their native attempts remain indexed; they were not promoted to supported evidence or used to relax thresholds.

The narrow analytical geometry was chosen after these failures to verify executable accounting and state continuity without claiming that the complex hydraulics had been solved. The physical protocol's unsupported mechanisms remain unsupported until independently resolved and measured.

## Evidence and verification

Each complete pair retains 18 native/evidence files: top result and manifest, plus input, report, binary output, exact request, worker log, worker result, attempt result and manifest for each primary/refined child. The source guard and worker fingerprint bind the unchanged v1 files, both new preparation modules, toolkit version and native runtime bytes. The supported runtime remains SWMM 5.2.4 / swmm-toolkit 0.17.0; loaded source changes require restart.

The isolated child gives SWMM local filenames within its attempt directory, preserving the input bytes and destination while avoiding native truncation of long absolute output names. A 264-character output-path regression verifies identical numerical results and the complete sealed 18-file export. Windows must still accept the child working directory itself; a directory beyond its process-launch limit fails without qualification.

`verify_prepared_bench_result` requires exactly the 18 expected native/evidence filenames, then checks stored-result equality, complete safe file inventory, every checksum, pair/child fingerprints, request preparation hashes and the current loaded source/runtime identity. Missing or renamed native output fails even if a modified manifest has internally consistent checksums. It establishes local consistency, not source authenticity, measurement truth or an external trust anchor. A hosting service must additionally constrain evidence paths and record the accepted manifest hash to distinguish later wholesale self-consistent replacement.

`evidence/v0.6/prepared-bench-evidence.json` anchors the final positive case, the two selected unresolved cases, and 14 retained development attempt manifest hashes. Its three compact `prepared-*-native.zip` archives include the complete fresh native pairs, their exact fixtures and supplied synthetic source text, and the adapter source bytes matching the final fingerprints. Historical attempts retain their recorded outcomes under their then-current checks; an earlier endpoint-only pass is explicitly **not** a pass under the final cumulative checks. Archived absolute file maps preserve original provenance; the archive checksum anchors their bytes rather than pretending a relocated bundle has the original live paths.

Focused tests cover strict invalid-input rejection, preserved dry-v1 semantics, exact clocks and shared event state, analytical 7 L/9 L water levels, all-node/all-conduit storage, signed zero-crossing integration, intermediate conservation failure despite endpoint cancellation, subreport transient rejection, required-stationarity rejection, half-step wet-state comparison, native artifact tampering and loaded-source guards. These are software tests, not physical observations or calibration.
