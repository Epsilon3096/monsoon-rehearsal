# Isolated bench model adapter — v1

This is an executable research adapter for a separately described apparatus. It converts a valid site-v1 package plus explicit model and run contracts into an isolated EPA SWMM simulation. It does not activate the historical reference model, authorise maintenance, verify a survey, fit parameters, or establish physical validation. There is still no supplied physical apparatus, survey, observation, or participant.

The new fixtures are entirely invented software test cases. Their geometry is independent of the historical township reference. `synthetic_bench_site_v1.json`, `synthetic_bench_model_v1.json`, `synthetic_bench_run_v1.json`, and `synthetic_bench_source_v1.txt` live under `data/templates/`. The earlier synthetic site/measurement fixtures, frozen 24-event protocol, policy sources, and study results are unchanged.

## Supported physical representation

The adapter supports fixed conduit geometry, prescribed piecewise-linear inflow, prescribed receiving-water stage, and a nominally drained start. Every internal compartment is represented as a free-surface storage node. Site-v1 storage curves are used directly. A site-v1 junction must have a supplemental stage-area curve and source reference in the bench model; a missing curve is rejected. Curves must span exactly the invert through the spill elevation with no extrapolation. Their integrated volume represents the compartment, while conduits retain their own water volume.

This follows SWMM's distinction between storage units and volume-free junctions. The numerical minimum surface area is explicitly supplied and may not exceed the smallest supplied compartment area; it is not a substitute for a volume curve. The storage and dynamic-wave descriptions are in the [EPA Hydraulic Reference Manual, §§2.1.4, 3.3 and 5.4](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P100S9AS.txt).

Supported conduit shapes match site-v1: open rectangle, circular, and trapezoid. Their dimensions, endpoint invert elevations, length, and chosen completed-job geometry are explicit. No generic capacity multiplier is applied. Every link also has explicit Manning roughness, entrance loss, exit loss and average loss coefficients. The model may declare different roughness from the site record, making the candidate assumption visible and hash-bound. Supplied source references are not fetched or authenticated by the adapter.

All non-outfall nodes must appear in both the site's spill inventory and the model's absorbing-collector inventory. Overflow is water leaving the control volume at that compartment; no ponding, surface transfer, re-entry, property flooding, or unobserved collection path is inferred. If a simulated open conduit's endpoint head or represented link depth exceeds its bank height, the run is unresolved because lateral escape is unrepresented. This computational check cannot prove that an actual apparatus has no other escape path.

Each outfall has exactly one incoming conduit. Positive outfall exchange means discharge from the control volume; negative exchange means receiving-water inflow. A prescribed receiving reservoir is outside the control volume. If a real receiving tank is included inside the experiment's measured stored water, it requires an explicit storage representation and a different external boundary; it cannot silently be treated as a volume-free outfall. SWMM supports time-varying receiving stage and ungated backflow; see the [EPA User's Manual, outfall and time-series definitions](https://www.epa.gov/system/files/documents/2022-02/storm-water-management-model-users-manual-version-5.2.pdf).

Evaporation, seepage, and leakage are each explicitly declared `excluded_zero`, with a source reference. Nonzero or unknown losses are unsupported by this first adapter. A measured experiment must justify that bounded simplification through its independent control-volume and loss assessment; a software declaration does not establish a zero leak rate.

## Initial state and time

The only accepted initial kind is `dry_zero_flow`: zero prescribed initial inflow, zero specified internal node depth and conduit flow, and receiving stage at or below the outfall invert. No hotstart, arbitrary node depth override, hidden warmup, measured equilibration, or wet reset is accepted. The engine's actual t=0 node/link volumes and flows are retained.

The pinned engine initializes nominally dry conduits with a small depth floor. In the supplied synthetic rig this is approximately 0.00003048 m and 0.000004877 m³ total initial link water. This is numerical initialization, not an invented physical measurement. `initial_numerical_storage_tolerance_m3` explicitly bounds acceptable initialized water; the fixture declares 0.00001 m³. Nonzero initial node storage or link flow is rejected. The complete initial volume is included in every balance, with no subtraction or relabelling as exact zero.

All run times are elapsed SI seconds. Prescribed points start at zero and end at the declared horizon, strictly increasing, with no missing-value filling or extrapolation. Their integer-second knots are linearly interpolated as prescribed inputs. All response samples occur on the exact declared reporting grid, including t=0 and the final horizon. Model responses are not interpolated onto a different grid.

The worker steps the engine at every routing interval. The EPA API's elapsed return is in **decimal days**, and its final successful step returns zero; the worker converts to seconds and checks the fixed-step endpoint. The internal calendar date is an arbitrary simulation clock and does not assert a physical collection date. [EPA SWMM 5.2.4 `swmm5.c`](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/swmm5.c)

`inflow_m3_s` contains the engine-applied lateral flow. `prescribed_inflow_m3_s` separately evaluates the bound input curve at the sample time. `receiving_stage_m` is the prescribed receiving stage; `stage_m` at an outfall is the engine's boundary node head, which can also reflect its hydraulic outlet rules. These input/boundary columns are excluded from independent response validation. Internal node stage, signed receiving exchange, internal link flows, collector spill and total stored water are model responses.

## Versioned contracts

Unknown fields, null numeric values, booleans used as numbers, nonfinite numbers, duplicate JSON keys, duplicate IDs, mismatched hashes, and unsupported states fail before engine execution. JSON is limited to 5 MiB and 64 nesting levels. IDs retain site-v1 syntax and must also be unambiguous under SWMM's case-insensitive lookup.

The complete model keys for `monsoon.bench-model/1` are:

| Field | Meaning |
|---|---|
| `model_id`, `notes` | Stable identifier and explicit interpretation |
| `site_package_sha256` | Canonical hash of the exact valid site-v1 package |
| `evidence_kind` | `synthetic_fixture` or `supplied_bench_model`, consistent with the site evidence label |
| `completed_job_ids` | Distinct existing site jobs; prerequisites must be included; selected before/after geometry is fixed for the entire run |
| `junction_storage` | Exactly every site junction: `node_id`, `stage_area` pairs of `stage_m`/`area_m2`, `source_id` |
| `link_parameters` | Exactly every link: `link_id`, `roughness_n`, `entrance_loss_coefficient`, `exit_loss_coefficient`, `average_loss_coefficient`, `source_id` |
| `overflow` | Exactly every internal node: `node_id`, `destination: external_absorbing_collector`, `source_id` |
| `losses` | `evaporation`, `seepage`, `leakage`, each `excluded_zero`, plus `source_id` |
| `numerics` | `routing_step_s`, `report_step_s`, `head_tolerance_m`, `minimum_surface_area_m2`, `initial_numerical_storage_tolerance_m3`, `max_trials`, `inertial_damping: NONE`, `normal_flow_limited: BOTH` |

The complete run keys for `monsoon.bench-run/1` are `run_id`, `model_sha256`, `duration_s`, `initial_conditions: {kind: dry_zero_flow, source_id}`, `inflows`, `receiving_stages`, and `notes`. Each boundary row has its exact `node_id` and `points`. An inflow point has `elapsed_s` and `value_m3_s`; a receiving-stage point has `elapsed_s` and `stage_m`. Every declared inflow/outfall boundary must be supplied exactly once. These are prospective/model inputs, not observed response files.

The bounded software envelope includes 20 nodes, 30 links, 1–3600 s horizon, integer reporting intervals of 1–60 s, 0.01–1 s primary routing steps, 50000 primary steps, 100000 refinement steps, at most 10000 report rows, and at most 30000 combined node/link reporting records. Reporting must be an exact multiple of the routing step and end at the horizon. More restrictive dimensional, flow, curve and numerical limits are enforced by the validator. Those limits are implementation bounds, not evidence that every accepted combination is physically suitable or numerically stable.

## Numerical acceptance and accounting

Every public execution runs both the declared step and an automatically halved step, in separate processes. The refinement changes only `routing_step_s`; its run hash is rebound to that model. The internal minimum is 0.005 s. Both attempts, warnings, failures and report files are retained. Each child has a 90-second process limit. No result is silently replaced by the finer attempt.

Each attempt must pass all of these project checks:

- The nominal-dry initialization allowance and complete exact reporting grid.
- Finite outputs, no SWMM warnings/errors, no internal-node nonconverged steps, and no unsupported lateral overtopping.
- An independently integrated volume balance within `max(0.000001 m³, 1% × (actual initial storage + external inflow + receiving backflow))`.
- SWMM routing continuity within 1% when entering plus initial water exceeds 0.000001 m³.
- Engine-applied inflow consistent with the exact prescribed integral within `max(0.000001 m³, 1% of prescribed inflow)`.
- Independently integrated inflow/backflow, outfall discharge and spill consistent with the corresponding SI routing totals.

The paired comparison checks every sampled node stage, every actual-routing-step peak node stage, sampled link flow, sampled signed outfall exchange, sampled spill rate, total storage, per-node cumulative spill, and per-outfall discharge/backflow volumes. Its tolerance is the larger of 2% of the relevant maximum magnitude and these fixed absolute floors: 0.0001 m stage, 0.0000001 m³/s flow, and 0.000001 m³ volume. Stage scaling uses depth above the node invert, not the absolute datum. Either failed child or any failed comparison makes the public result `numerically_unresolved`. These thresholds are source-defined research QA choices; they are not the physical protocol's acceptance criteria or engineering standards. Smaller decision effects require a reviewed, tighter numerical design.

Stored water is the sum of every live node and conduit volume in m³. The independent balance is initial storage plus external inflow plus receiving backflow, minus receiving discharge, node spill, represented losses and final storage. Flow integration uses the actual routing intervals. Signed exchange is split into its positive and negative piecewise-linear portions at zero crossings. Coarse report rows are not used to reconstruct the balance.

The pinned toolkit converts live node/link volume, depth and flow to project units, but its raw routing initial/final storage fields remain internal ft³. Those raw storage fields are retained as diagnostics and are never treated as m³. The signed outfall flow uses outgoing flow when the boundary is supplying water; subtracting the two node flow getters would erase backflow because of an engine bookkeeping update. These mappings were checked against [the toolkit result/volume implementation](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/toolkit.c), [its routing-total conversions](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/massbal.c), and [EPA's outfall accounting](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/node.c), then verified with the installed binary using known-volume and backflow fixtures. Upstream source alone is not treated as proof of a particular local binary.

The installed engine's volume conversion uses the rounded factor 0.02832 m³/ft³, matching its [conversion table](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/swmm5.c). The regression check uses that actual factor when comparing raw storage to the live volume getter; it does not substitute the exact physical foot-to-metre cube and mistake the small rounding difference for a unit mismatch.

## API and retained evidence

```python
from monsoon.bench_model import (
    validate_bench_model, validate_bench_run, build_bench_input,
    run_bench_model, bench_engine_identity, verify_bench_result,
)

contract = validate_bench_run(site_json, model_json, run_json)
result = run_bench_model(site_json, model_json, run_json, output_dir)
integrity = verify_bench_result(result)
```

The validators accept parsed objects, JSON text, or UTF-8 JSON bytes and return structured errors. Contract validity means the bounded model can be attempted. The public execution's `valid` additionally requires both numerical attempts and their agreement to pass. `physical_validation_established`, `engineering_approval_established`, and `operational_activation_allowed` always remain false.

Results contain `site_package_sha256`, `model_sha256`, `run_sha256`, pair `simulation_sha256`, `fingerprint`, `engine_identity` (also available as `engine`), `timeseries`, `diagnostics`, `column_roles`, `step_halving`, structured `errors`, and `files`. The exact source files, toolkit version and native runtime hashes are bound. A loaded adapter whose file has changed rejects execution until restart. Each child checks its worker/source, request/input and runtime hashes before opening SWMM. The supported binary is SWMM 5.2.4 through swmm-toolkit 0.17.0; another version requires separate review.

Each successful pair has 18 files: top `result.json` and `manifest.json`, plus `base/` and `half/`, each containing `model.inp`, `model.rpt`, `model.out`, `request.json`, `worker.log`, `worker-result.json`, `result.json`, and `manifest.json`. Each execution creates a fresh directory; no cache or overwrite is used. The top result file is exactly the returned result. Its manifest uses schema `monsoon.bench-pair-evidence/1` and hashes every other retained file by safe relative path, including both child manifests/results. The `files` mapping has those relative POSIX keys and absolute local values. Failed attempts may have fewer files; whatever was produced is retained.

`verify_bench_result` checks stored-result equality, complete safe file inventory, checksums, child/pair fingerprints and the current loaded engine/source identity. It verifies local consistency, not authenticity of supplied evidence. A hosting service should additionally constrain the directory to its own research area and anchor the manifest hash when it accepts the run; otherwise a later replacement of an entire self-consistent bundle is not distinguished by checksums alone.

## Verified software behaviour and remaining boundary

The targeted tests execute the actual engine on the clearly synthetic rig and its declared variants: a 7 L prescribed pulse; a narrower conduit with a higher upstream stage; rising receiving water with negative exchange followed by positive discharge; 7 L retained below a raised outlet; a zero-forcing closed balance; and an open-channel overtopping case that remains unresolved. They inspect SI node-volume/area relationships, all-water storage, the actual initial floor, all report endpoints, automatic step refinement, artifact integrity, and strict invalid-input rejection. Earlier development attempts with a curve syntax error or nonconverged step were retained; a later passing fixture does not retrospectively change those attempts.

These tests establish bounded software behaviour. They do not establish a built rig, calibrated sensors, measured model accuracy, useful maintenance advice, or any field benefit. In particular, this adapter cannot execute the frozen protocol's equilibrated-control events or an initially wet high-receiving-stage event. The 24-event physical protocol remains unchanged and incomplete; unsupported rows cannot be relabelled cold starts or omitted to claim completion. A reviewed additional initial-state capability and prospective collection plan are needed before those mechanisms can be evaluated.
