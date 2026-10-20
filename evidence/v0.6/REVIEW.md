# v0.6 focused assurance review

Review date: 15 October 2026. Scope: the new continuous preparation adapter, the separate frozen measured-boundary replay workflow, and the additive exact-input cumulative balance audit. This is software and scientific-claim review, not physical validation. No apparatus, actual observation, participant, calibration certificate or external witness has been supplied.

Status: the bounded review and the audit's 13 focused tests are complete. The audit gate closes the identified intermediate-conservation acceptance defect in new replay qualification; it does not repair the adverse hydraulics or change historical results. No additional blocking issue was found in the reviewed causal receipt ordering, numerical gates, evidence retention, or displayed claim boundaries. Aggregate release tests and browser verification belong to the integration record and are not claimed here.

The review was conducted by a separate implementation agent within the same development effort. After identifying the numerical issue, that agent implemented the new audit; another agent reviewed its water budget and path protections. This is not an external expert review, independent laboratory replication, professional certification or independent validation of the hydraulic solver.

## Acceptance boundaries

1. A prepared simulation must use one continuous dry-start history and one fixed geometry. The event begins by retaining the live water distribution and flows, including conduit water. Neither node-depth assignment nor a restart may erase preparation history.
2. Preparation and event water balances must be separate, contiguous and additive. The event's initial storage is the preparation's final storage. An interval or signed zero crossing at the split must be counted once. Numerical initialization water remains visible.
3. The primary and half-step simulations must both pass the full-history checks and agree at the common event boundary. A preparation warning, unsupported lateral escape or nonconverged step cannot be hidden by a later stable event.
4. Reproducible preparation is not automatically equilibrium. An optional stationary-state assertion requires a predeclared constant-forcing window and explicit state-range tolerances, measured on actual routing steps. Passing these numerical conditions is still not evidence of physically observed equilibration.
5. Model parameters, geometry, input-processing recipe, complete boundary inventory, sign conventions, time windows, response inventory, units, datum, instrument declarations and uncertainty limits must freeze before future measured input collection. The actual measured forcing values can arrive later; the recipe cannot adapt to them.
6. Boundary inputs and withheld responses need separate receipts. Only the frozen internal engine may generate predictions. Imposed inflows and receiving stage cannot be credited as independent response agreement. A completed response-error calculation does not establish small error or physical acceptance.
7. A failed or missing accepted receipt consumes its assigned stage and remains inspectable. Later favorable data cannot replace an unfavorable run. Schema mistakes must not create a pathway to hide a documented numerical or evidence failure.
8. Stored raw bytes, every prediction artifact, frozen source/runtime identity and local receipt order must remain linked. Local consistency is not authentication, independent witnessing or proof that an external observer did not already know an outcome.

## Deliberate scope separation

The measured-boundary replay owner has selected **cold-start replay only** for this bounded stage. The preparation adapter separately simulates a prescribed continuous history. These capabilities do not compose into measured prepared-state replay in v0.6. The complete physical protocol's equilibrated-control family, independently reset current/restored pairs and physical acceptance therefore remain uncompleted. Documentation and demonstrations must retain this distinction.

The original policy's H2 failure, later all-abstention/tie results and absence of demonstrated maintenance benefit remain unaffected. A new hydraulic wrapper cannot retrospectively validate them.

## Primary-source checks

The [EPA SWMM 5.2 User's Manual, §11.7.2](https://www.epa.gov/system/files/documents/2022-02/storm-water-management-model-users-manual-version-5.2.pdf) describes startup runs and state retention using hot-start files. This supports preserving the hydraulic history; it does not establish this project's geometry transitions, stationary-state tolerances or measured validity. The v0.6 approach instead keeps preparation and evaluation in one fixed-geometry simulation.

The [EPA hydraulic reference, §§2.3.2 and 3.1](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P100S9AS.txt) treats node heads/link flows as initial state and hydraulic head and discharge as dynamic variables. Reviewing total storage alone would therefore miss a different or still-transient distribution of water and flow.

The pinned [EPA SWMM 5.2.4 source, `swmm_step`](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/swmm5.c) returns elapsed time in decimal days and zero at completion. New routing-step sampling must preserve that mapping, exact endpoint treatment and unit checks from the existing adapter. Source inspection complements, rather than replaces, checks against the installed runtime.

## Material finding: final cancellation hid intermediate nonconservation

An invented rapid receiving-stage cycle on the unchanged original three-node geometry passed the historical final whole-run and time-halving gates while retaining a large intermediate discrepancy. The imposed receiving stage rises from 0 to 0.06 m over 20 seconds, holds until 50 seconds, and declines to zero at 90 seconds; external prescribed inflow is zero and the run ends at 120 seconds.

The direct installed-engine probe in [native-phase-review/summary.json](native-phase-review/summary.json) independently compares elapsed engine time, native cumulative routing totals, live storage in every node and link, and integrated signed boundary flows. Its native input, report, output, probe code and hashes are retained in [native-phase-review/manifest.json](native-phase-review/manifest.json).

| Observation | 0.01 s routing step | 0.005 s routing step |
| --- | ---: | ---: |
| Live total storage at 50 s | 7.937933643 L | 7.937653485 L |
| Cumulative balance residual at 50 s | -1.914449922 L | -1.915509918 L |
| Whole-run residual at 120 s | +0.000475630 L | -0.001616344 L |
| Maximum day-clock/count disagreement | 1.42e-14 s | 1.42e-14 s |

Native and independently integrated residuals agree at the split to about 1e-17 m³. The raw native final-storage value, converted using the pinned runtime's 0.02832 m³/ft³ factor, agrees with live node-plus-link storage. These observations rule out the preparation split, omitted live storage, day/second mapping and this unit conversion as explanations for the large discrepancy. They do not identify its physical or numerical cause. Halving the routing time step does not remove it. A possible boundary/storage discretization explanation remains a hypothesis, not a repaired or validated mechanism.

The [OWA toolkit source](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/toolkit.c) exposes live node/link volumes; [its mass-balance implementation](https://raw.githubusercontent.com/OpenWaterAnalytics/Stormwater-Management-Model/develop/src/solver/massbal.c) distinguishes stored volume units and includes a small-absolute-residual cutoff in its percent-error calculation. This is upstream source context, not proof of the installed binary's exact source revision. The local probe separately establishes that the pinned binary reports a tiny 1e-6% error at the 50-second split despite the retained discrepancy. Therefore that native percentage alone cannot qualify these bench-scale runs.

## Closure in the new numerical qualification

`bench_balance_audit.py` executes both exact original `.inp` byte streams in separate worker processes. It does not rebuild another model or alter the historical pair's 18-file bundle. Each actual routing endpoint checks native cumulative accounting and independently integrated signed boundary accounting against all live node and link storage. Both use the existing budget `max(1 mL, 1% × (initial water + gross incoming water))`. Gross receiving backflow is retained even after earlier discharge; net exchange cannot replace that budget. Nominally dry numerical water remains visible. Report samples, worst excursion, violation count, native reports, inputs, requests, outputs, runtime/source identity and hashes are retained in another bounded bundle.

The preparation owner separately applied the same every-endpoint principle to whole-history, preparation and event ledgers. The event retains the complete live state; preparation and event balances cannot cancel one another into acceptance. The optional constant-forcing stationarity window checks all node/link states on routing steps, and both time steps must pass. Stationarity remains a numerical claim.

The final current-source [cumulative review summary](cumulative-balance-review/summary.json) and [manifest](cumulative-balance-review/manifest.json) retain three fresh native pairs plus audits, including adverse results. They contain 116 files and 3,408,277 payload bytes excluding the top manifest.

| Synthetic case | Historical pair gates | New cumulative audit | Evidence |
| --- | --- | --- | --- |
| Original 7 L pulse on the original geometry | Pass | Reject; primary worst residual/tolerance = 10.37753, 4,926 violating endpoints | [Audit](cumulative-balance-review/original-pulse/bench-balance-audit-sypegctq/result.json) |
| Rapid tailwater cycle on the original geometry | Pass | Reject; primary worst ratio = 883.24607, 8,723 violating endpoints | [Audit](cumulative-balance-review/rapid-tailwater/bench-balance-audit-iyyas4rr/result.json) |
| Analytical 0.1 m² compartment, elevated dry outlet, 7 L then 2 L pulses | Pass | Pass; 16,001 primary and 32,001 refined endpoints, zero violations, worst ratio below 0.02941 | [Audit](cumulative-balance-review/analytical-compartment/bench-balance-audit-v0c1lmg9/result.json) |

The positive geometry deliberately gives a bounded analytical storage check. The owner tests independently require approximately 0.007 m³ in compartment A at event start and 0.009 m³ at event end, with stages near 0.11 and 0.13 m on its declared datum. The elevated outlet remains hydraulically dry. It establishes neither wet-conduit/backwater accuracy nor accuracy of the original flowing fixture. The new separately named fixtures and preserved adverse candidates make that scope explicit; no tolerance was relaxed to rescue a failed case.

## Replay, receipt and claim review

The reviewed replay code derives forcing only from the boundary receipt under a frozen recipe. Its schemas bind SI units, datum, sign, complete input inventory, source and uncertainty declarations, bounded clock uncertainty, integer knots, maximum gap and exact response grid. Missing input readings, extrapolation, gap filling, time shifting, inferred conversion and receiving-stage scoring are excluded. Planned targets do not become forcing. Declared uncertainty is retained but not propagated into a physical acceptance test.

The boundary reservation commits before engine execution. The native prediction and additive audit seal before the public response API can accept a response receipt. A killed execution leaves an inspectable pending reservation; public recovery closes it unresolved rather than rerunning it. Bounded malformed or missing raw JSON consumes its assigned stage; unsupported/unbounded transport objects are refused before receipt. Cross-partition semantic response reuse suppresses residuals. Hashes and the local clock cannot authenticate an instrument, prove external blindness or establish that a human did not know future outcomes.

The replay now requires `prediction_qualified`, including the cumulative audit, before residuals or calibration freeze eligibility. The UI and same-solver demonstration honor this gate. The demonstration explicitly manufactures responses from its own sealed solver output with known offsets and labels the exercise circular. The UI distinguishes a numerical stationary state from physical equilibrium and retains failed attempts. The ZIP export retains exact raw receipts and both artifact bundles, checks source/runtime lineage, and describes its literal historical paths rather than claiming a portable restored database.

Cross-review also found that a changed runtime after study creation could previously admit a calibration that later could not be exported under one consistent lineage. The final replay revision checks the creation lineage before a new boundary reservation and before freeze; verification checks creation lineage even before a freeze exists. A distinct independent regression is retained in `tests/test_bench_cross_assurance.py`. The owner reports its pre-fix reproduction and post-fix pass; this review inspected the final guard and test rather than claiming another execution of that test.

## Executed targeted verification and preserved history

Executed: `python -m pytest tests/test_bench_balance_audit.py -q` with JUnit output; **13 passed in 10.25 seconds**. [The retained JUnit record](audit-tests.xml) records zero failures, errors or skips. Tests cover every routing endpoint and exact report grid; unchanged parent files and byte-identical inputs/requests; final-cancellation rejection in both adverse native cases; mixed-sign gross incoming water; refusal to write inside a parent bundle; unqualified parent refusal; changed artifacts, wrong parent and loaded source; absent physical claims; and retained second-attempt timeout failure. No full suite or server control was performed by this review agent.

The three final evidence runs each verified local artifact integrity separately from numerical qualification. Thus a rejected audit may have valid retained bytes; integrity is not hydraulic acceptance. Current audit and inherited adapter source snapshots accompany the final native evidence. Earlier development audit attempts remain historical work products and are not represented as current-lineage qualifications.

All **166 existing `data/` and `evidence/` entries** in the v0.5 delivery manifest were rehashed after this work and remain unchanged; see [historical-data-check.json](historical-data-check.json). Original policy files and the original bench adapter/worker retain their historical bytes. The original H2 failure and later all-abstention/tie outcomes remain failed or unresolved as originally recorded.

The final reviewed source pins are recorded in [reviewed-source-sha256.json](reviewed-source-sha256.json). The immutable audit identity is `1.0.0`, with `bench_balance_audit.py` SHA-256 `68c0e7f9afd9ee42507a1abdc3f3c50f045b7a9870afce4a9b0a9a1b3abddeae` and `_bench_balance_worker.py` SHA-256 `46d390c00679b98e08787a2d0ebbe3f1b60be84e10fd5f8851f872d1aabebe7a`. The installed engine is SWMM 5.2.4 through swmm-toolkit 0.17.0; individual runtime hashes are in the retained audit identity. Physical validation, engineering approval and operational activation remain false.
