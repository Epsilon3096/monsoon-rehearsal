# Independent scheduler and evaluation review

Reviewed 13 October 2026 against the project blueprint, integration contracts, scheduler, workflow boundaries, and preserved real-SWMM evidence. No geometry, scenario, duration bound, ranking tolerance, policy objective, or baseline was tuned after holdout evaluation.

The scheduler's central information rule passed: dispatch uses the observed clock, location, completed prerequisites and declared duration bounds. A future job's realised duration is read only after selection. Queue scanning reconsiders deferred prerequisites, reserves travel and depot return, and rejects duration overruns. All operational comparators use the same dispatch gate. The marginal comparator uses a frozen planning-ensemble table, not the realised holdout forcing. Ranking uses successive bands from the attained minimum rather than chained pairwise ties. Invalid intermediate hydraulic states cannot inherit a valid final score.

## Findings and corrections

1. A hydraulic response could omit a declared, non-protected model node while its remaining spills reconciled to its reported total. It now fails closed when any declared model/protected node is absent.
2. A missing, empty or whitespace run identifier could support a recommendation. Such responses now remain unresolved because their required evidence identity is missing.
3. Missing holdout durations caused the diagnostic oracle to raise after operational replay, discarding those comparison rows. Oracle failures now remain explicit diagnostics while operational rows, overruns and abstentions survive. Already completed jobs do not require past duration values.
4. An unresolved oracle candidate could be dropped and the surviving minimum falsely called exact. Any unresolved candidate now prevents an exact minimum/lower-bound claim. A separately labelled best supported option can still be inspected.
5. Frozen policies did not pin the scheduler implementation or their baseline descriptions. New manifests pin the planner source SHA-256 and include baseline definitions in the frozen checksum. Older manifests are preserved as historical evidence, not silently replayed as current pinned decisions.

Validation: **49 planning tests passed**, comprising 32 existing tests and 17 independent adversarial cases. The only existing fixture edits gave three test-double empty states a nonempty `EMPTY` evidence ID. Arithmetic fixtures test software contracts only; they are not hydraulic evidence.

A separate regression replay used the original stored SWMM records: all **65 plans**, all policies, rankings, marginal tables and counts, **24 planning comparisons**, **12 holdout comparisons**, and both original oracle plans/minima were identical after the corrections. This was a planner regression using stored engine outputs, not a new independent hydraulic trial. `planner-integration.json` and `planner-holdouts.json` were not modified.

## Preserved negative result

The robust queue and adaptive marginal baseline tie in hydraulic outcomes and crew minutes in all four planning cases and both holdouts. No advantage over that baseline is established.

In H2, both complete J4 then J3. Total spill falls from **1,219.608507 m³** without work to **810.771811 m³**, but protected node B2 rises from **280.776902 m³** to **810.771811 m³**: an increase of **529.994908 m³**, far above the declared **0.05 m³** tolerance. Both policies are therefore **inadmissible** in H2.

H2's admissible hindsight minimum is **893.072220 m³**. The inadmissible robust outcome must not be described as outperforming the oracle or as negative regret. Regret comparisons require a supported admissible operational result and a resolved oracle. In general, the tolerance-selected oracle plan can differ from the exact minimum scalar; use `exact_minimum_spill_m3` for a valid regret calculation.

## Interpretation and interface limits

Exactness applies to enumeration of locked priority queues in the declared finite scenario ensemble, not to all possible adaptive policies. This reference supports one crew, uniform travel, dry pre-event work and binary verified restoration. Spill no-worsening is relative to the starting state; displayed peak depths and threshold durations are supplementary diagnostics, not enforced absolute engineering limits. It supplies no field-safety, property-inundation, cross-catchment or expected annual benefit claim.

Read-only interface review identified a presentation issue: the comparison chart plotted inadmissible outcomes like supported outcomes while the status table was collapsed. Status should be visible on the chart and beside it. The verification narrative should call H1/H2 prespecified within-network synthetic holdouts, now revealed; they are neither observed storms nor an independent field trial. Their revealed results cannot become fresh unseen evidence for subsequent redesign.
