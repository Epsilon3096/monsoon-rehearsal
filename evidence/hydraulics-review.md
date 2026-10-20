# Independent hydraulic and software review

Reviewed on 13 October 2026 against the frozen synthetic reference, SWMM 5.2.4 and swmm-toolkit 0.17.0. This review checks the implementation and bounded experiments; it does not establish calibration or field performance.

## Defects reproduced and corrected

1. **Stale derived metrics.** Changing the case depth threshold from 80% to 40% reused the old cached threshold and duration because the generated SWMM input was identical. The result identity now includes the complete case snapshot. A single snapshot supplies input generation, derived metrics and provenance. The regression verifies that the threshold and duration both change.
2. **Malformed cache recovery.** Cache JSON containing `null`, an array, or a null `files` object raised an uncaught exception. Cache records now undergo structure, path, manifest, content-hash and saved-result checks before reuse. Incomplete evidence manifests and disagreement between the saved result and cache pointer also trigger a fresh run. Failed evidence is retained in its original attempt directory.
3. **Duplicated geometry constants.** Storage area/invert/depth and outfall invert were duplicated in the generator. The current values matched the frozen case, but a future case edit could have been silently ignored. The generator now uses the existing case fields. A direct engine regression doubles storage area from 300 to 600 m2 in an isolated test and confirms the expected additional 375 m3 at the prescribed initial depth of 1.25 m. The frozen geometry and scenarios were not changed.

The engine identity also records content hashes of installed native binaries and relevant interface files. A version string alone cannot distinguish locally rebuilt or replaced binaries. The adapter version is 1.0.1. The 14 tests in `tests/test_hydraulics_review.py` passed against the final source.

## Water accounting and metric semantics

The worker runs a real SWMM dynamic-wave engine in a private subprocess. Prescribed inputs are flow hydrographs in m3/s, not measured rainfall. The stored flooding statistic is cumulative node overflow in m3; routing-step integration independently agrees with it. Flood duration is converted from engine hours to minutes. Threshold duration is integrated at routing steps rather than from the one-minute plot samples.

The inspected toolkit implementation converts node statistics and routing inflow/outflow/flooding totals to user units but leaves routing-total initial/final storage in internal units. Summing the node and link volume APIs in m3 avoids mixing those fields. The independent domain balance includes initial water, prescribed inflow, receiving-water inflow, discharge, spill and final water. Spill crosses the declared absorbing boundary once; surface re-entry, street depths and property consequences are outside this model.

Large native *node-only* continuity percentages must be interpreted together with conduit storage. For the D1 no-work start-up, independent integration found a summed node-only residual of 139.644 m3 and a conduit-storage increase of 136.220 m3; their difference, 3.425 m3, agrees with the domain residual of 3.420 m3 to integration precision. The report's local residuals therefore cannot be interpreted as that much missing water from the complete domain. They remain visible in the native reports. This check does not substitute for site-specific hydraulic validation.

## Numerical and decision stability

Independent comparison of all 144 completed-state/scenario pairs at 0.5 and 0.25 seconds found every run valid under the declared gates. No protected-node no-worsening decision changed at the 0.05 m3 screening tolerance. The largest protected-node peak-depth difference was 0.000661 m; the largest threshold-duration difference was 0.008977 minute. The largest node spill difference was 1.1384 m3 in D1, within the predeclared relative spill tolerance. The verification callable now records depth/duration differences and explicitly tests no-worsening decision stability in addition to the spill convergence gate.

These checks establish stability for the frozen finite ensemble. They do not establish robustness to unmeasured geometry, uncertain runoff, a different numerical setting or another catchment.

## Recession and initial-state findings

`horizon.json` contains the exhaustive 180-versus-360-minute review: 144 pairs were valid, and all 96 planning/holdout pairs had exactly zero additional spill at every protected node. Remaining water is reported rather than treated as lost. The 16 D1 diagnostic states remained horizon-sensitive and are listed separately.

| D1 state | Spill at 180 min | Spill at 360 min |
|---|---:|---:|
| No completed work, original cold start | 689.59 m3 | 822.75 m3 |
| All four jobs complete, original cold start | 677.95 m3 | 811.78 m3 |
| No work, hydrostatic initial node levels | 0 m3 | 0 m3 |

D1 imposes a fixed 100.8 m receiving stage on a network whose junction initial depths are zero. The early filling surge reaches the trunk-downstream rim. Its residual momentum and continuing boundary exchange make its cumulative spill depend on the observation horizon. The zero-inflow hydrostatic control has the same geometry and receiving stage but initial water levels consistent with that stage; it produces zero flow and spill. The original case has been retained. Its result should be described as a timed cold-start boundary experiment, not inevitable steady tailwater flooding or a complete-event loss.

P4 also uses a non-equilibrated cold start. H2's initial 1.25 m storage depth is prescribed synthetic data, not an observed field level. These details are now explicit in `data/MODEL_NOTES.md`. A warm-up or measured antecedent state is required before applying the mechanism to a site where the receiving stage or storage already existed before the work.

`initial-state-review.json` records four independent hydrostatic controls, with exact native inputs, reports, outputs and manifests copied into `initial-state-runs/`. Those variants are explanatory diagnostics and were not added to the planner's frozen scenario set.

The verification field named `engine_runs` counts requested evaluations: 288 requests for 144 pairs. It does not count independent experiments or necessarily fresh subprocess executions. D2 pre-restores three jobs, so several completed-job labels share one physical input; cache reuse is expected.
