# v0.5 independent implementation review

Reviewed 14 October 2026. The reviewer inspected the implementation without editing its sources, tests, fixtures or frozen scientific records. This is a separate review within the same development team, not external scientific validation.

No unresolved substantive defect was identified in the bounded bench workflow. It is ready for source freeze and project-wide release verification. There are still **zero physical runs or supplied measurements**, and no physical or operational acceptance follows from this review.

The exact reviewed source, fixture, test and runtime hashes are recorded in [bench-review.json](bench-review.json).

## What was checked

The actual SWMM tests cover the 7 L synthetic pulse, complete elapsed-second reporting, explicit compartment and conduit storage, the numerical dry-link water floor, narrower-channel sensitivity, signed receiving backflow followed by discharge, a retained-volume case, and a closed zero-forcing balance. Unsupported lateral overtopping remains unresolved. Every public run uses a primary/refined pair; both attempts and their evidence are retained.

The study checks cover calibration candidates, immutable local records, source/runtime and observation lineage, future event assignment, missing readings, retained failures, ordered validation, tampering, and equal treatment of failed attempts. The UI checks exercise the real model and study path, nested evidence export, stale-artifact suppression, and failed-attempt cache clearing. Most adversarial ledger and clock checks use explicit test doubles; the model, study integration and UI also have actual solver tests. Neither kind supplies physical evidence.

The reviewer also tried 1,200 in-memory substitutions across the input contracts without an uncaught exception. This was an intake robustness check with no engine runs; it is not 1,200 scientific cases.

## Findings resolved before this review

| Finding | Final behavior |
|---|---|
| Sensor renaming or series reordering bypassed response-reuse matching. | Fingerprints use semantic quantity, location, unit, time and value. Suspected matches are retained as unresolved; identical values do not prove reuse. |
| A freeze could use its entry timestamp after lengthy preparation. | A fresh final timestamp and a 60-second measured-event lead are required. |
| Cached export could omit nested pair files or accept changed artifacts. | The accepted manifest is anchored; full inventory, current source/runtime and every exported byte are checked. |
| A failed new exercise could leave an old success visible. | Current-attempt cache is cleared before execution; stored exercise integrity is checked before display. |
| “Water entering” excluded receiving backflow. | Applied inflow and receiving backflow are shown separately. |
| A prescribed-boundary trace used calculated outlet head. | The boundary trace uses the supplied receiving-stage series. |

The first four findings have direct regression coverage. The two presentation fixes were verified by inspection against the worker output roles and backflow behavior.

## Verification record

The first combined run executed 93 targeted cases: **92 passed and one failed** in 32.82 seconds. During that run, the model test file was being updated; application sources did not change. Its new raw/live storage assertion used the exact physical cubic-foot conversion while the toolkit uses the rounded factor 0.02832. The observed values were 0.0000048768 m³ with the exact conversion and 0.000004877343088019509 m³ from the live getter.

The builder corrected the assertion against the [maintainer conversion table](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/swmm5.c) and installed runtime. After the test file was frozen, the reviewer reran the affected model file: **42 passed in 7.84 seconds**, with no file changes during execution. This was a test correction; numerical acceptance criteria and application behavior were unchanged.

After that review, the root refined the narrow-screen metric layout and added visible reasons for unresolved response records, with one additional missing-reading UI parameter case. The reviewer inspected those changes and updated their hashes. The root reported **8 final UI/demo cases passed in 26.08 seconds**. The model, worker and study application sources remained unchanged.

The final corpus contains **94 distinct targeted cases**: 42 model, 44 study, 7 UI and 1 demo. This is coverage across separate scoped runs, not a claim of one green combined 94-case invocation. The reviewer ran the earlier 93-case corpus and its affected model-file rerun; the final 8 UI/demo result was reported by the root. Reruns are not new cases. The failed pre-freeze invocation is retained in the JSON report. The root also stopped an earlier project-wide run before the last UI change, retained its log, and restarted under the final freeze; this review does not claim that suite has completed.

The v0.4 delivery manifest still matches all **141 historical data/evidence files** and **13 selected historical sources**. The original v0.4 archive remains:

`334e34cc6217b160ac4ceb2f37f7141b7661278058097764dda6b435e18078e5`

## What the result supports

The product can now turn an explicit bounded bench contract into a reproducible simulation and preserve the distinction between calibration and later response checks. It records assumptions, numerical failures, source lineage and response errors for review.

It does not establish a built apparatus, measured accuracy, genuine experimental prospectivity, a useful maintenance recommendation, or scheduling superiority. The earlier v0.3 result remains unchanged: all four screened policies abstained on all 10 events and tied no work on all 10. The original harmful diagnostic remains part of the historical record.

## Limits that remain

- Only fixed geometry and nominal dry/zero-flow starts are supported. Wet resets and equilibrated controls remain unsupported, so the unchanged 24-event physical protocol is incomplete.
- Predictions use prescribed boundary curves. Actual measured inflow and receiving-stage reproduction are not checked; forcing mismatch can contribute to the reported response errors.
- Explicit storage geometry, absorbing collectors and zero losses remain model assumptions. Physical escape paths, receiving-tank storage, leakage and model-form suitability need independent assessment.
- Step refinement and conservation are numerical checks. Their fixed floors may hide smaller effects, and they do not establish laboratory or field fidelity.
- Local hashes, timestamps and immutable records do not authenticate an external clock, an observer or a measurement. Response uncertainties are retained but do not yet drive physical acceptance.
- The demo uses the same solver plus declared 1 mm and 10 mm offsets. It verifies record sequence and arithmetic; it cannot independently validate hydraulics.

The next software gate is the root-owned project-wide verification. The next scientific gate is reviewed physical preparation and prospective measured collection within a supported model scope.

