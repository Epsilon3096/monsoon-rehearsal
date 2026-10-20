# Plan-specific development assurance

Version 0.2 adds a separate evidence gate for a priority queue that was already chosen from the planning scenarios. The audit never searches for a new queue, calls the hindsight oracle, repairs a failed queue or substitutes a successful scenario for a failure. The original synthetic case and its 0.05 m³ protected-node spill tolerance remain unchanged.

This is development evidence. H1 and H2 were prespecified for the first prototype, have already been revealed, and are not fresh independent validation. New sensitivities use the same synthetic network. Passing does not establish measured intervention behaviour, calibrated uncertainty, crew safety or field effectiveness.

## Frozen protocol

`data/assurance_protocol.json` was saved before the first v0.2 stress evaluation. Its final pre-evaluation freeze is **2026-10-13 14:35:35 UTC**, with SHA-256 **6dc5857a0c31d17639012b2dcefe4f21b4b5d473f56f39f2433a6aac4f495b23**. Before any stress result was computed, its numerical contract was strengthened to require step halving and a doubled horizon. Parameter values, scenario membership and decision tolerances were not changed after reveal.

The required cases are the selected planning scenarios plus these eleven development cases:

| Case | Fixed change and purpose |
|---|---|
| H1 | Original double-pulse forcing and durations; now explicitly labelled revealed |
| H2 | Original plateau and initially filled storage; known adverse outcome remains required |
| S_FLOW_LOW / S_FLOW_HIGH | P1 branch peaks −20% / +20%, retaining timing and branch ratio |
| S_ROUGH_LOW / S_ROUGH_HIGH | P1 conduit roughness −20% / +20%; tests faster transfer as well as lost conveyance |
| S_RESTRICTION | Remaining blocked widths ×0.75; restored widths do not change |
| S_STORAGE | P1 initial storage depth 1.5 m within the unchanged 2 m store |
| S_STAGE | P1 receiving stage 100.6 m, 0.2 m above P4; the cold-start assumption is explicit |
| S_DURATION_BOUND | P1 hydraulics with each job's existing maximum duration realised |
| S_COMPOUND | The high-flow, high-roughness, tighter-restriction, filled-store, elevated-stage and maximum-duration corner |

These are illustrative engineering sensitivities rather than measured uncertainty bounds. A single interaction corner does not establish the worst possible combination. No occurrence probabilities, return periods or statistical confidence interval are assigned.

## Scientific gate

The audit uses the existing `planning._Evaluator` and its causal dispatch. A job starts only when its declared maximum work time, travel and return reserve fit. Its realised duration is read after dispatch. Every achieved completed-work prefix and final state is compared with **no additional discretionary work under that same hydraulic scenario and the same verified starting state**. No work therefore retains any previously verified restoration; it does not restore an empty network or reset the clock.

Each represented hydraulic state requires three actual engine runs: 0.5 s routing over 180 minutes, 0.25 s routing over 180 minutes, and 0.5 s routing over 360 minutes. All must pass the existing engine validity checks and identify the same forcing, model, restoration state and engine. Per-node and total spill must agree under step halving within the larger of 0.05 m³ and 2% of the larger absolute spill. The extended horizon must change spill by at most 0.05 m³ per represented node and in total. Each protected-node pass/fail decision must be unchanged by step halving. A classification flip is unresolved even when the aggregate convergence criterion passes.

`passed` means every required case and reached state resolved and passed. `failed` records resolved protected-node worsening. `unresolved` means at least one required calculation, numerical check, replay or evidence item could not support a conclusion. Unresolved takes precedence at the overall level; any separately established harmful prefixes remain visible in the violation list. Failed or unresolved audits cannot authorise work for this envelope. A lower total spill never offsets harm at one protected location.

Every harmful state names its scenario, node, prefix number, whether it is a prefix or final state, restored jobs, raw run and baseline IDs, baseline spill, resulting spill, increase, tolerance and excess above tolerance. Scheduling skips come directly from the shared replay and retain their reason codes. The audit does not recommend a replacement queue based on stress outcomes.

## Interfaces and integrity

`audit_plan(case, episode, plan, hydraulic_fn)` evaluates one planning-admissible frozen queue. Use `assurance_hydraulics.checked_state` as its callback. A plain hydraulic result without the required numerical evidence becomes unresolved. Invalid or altered decision provenance is rejected before the first hydraulic callback.

`assurance_requirement()` returns the current schema, protocol ID and protocol hash. A reviewable snapshot includes this requirement, its original `provenance`, `decision_manifest`, `frozen_fingerprint`, queue, job definitions, deadline, travel time, input fingerprint, model version and observed-state version. `snapshot_subject(snapshot)` and `subject_hash(snapshot)` derive the canonical audit identity; they give the same result before and after the ticket store stamps matching `context_inputs` and `observed_state`.

`validate_audit(snapshot)` returns `required`, `valid`, `approval_allowed`, `status` and `reasons`. It verifies current identities, protocol, case, queue, deadline, observed state, raw artifact hashes and numerical evidence. It then rebuilds every required scenario and prefix report with the common planner from the saved raw metrics. Removing a failed case or harmful prefix and recomputing an outer checksum therefore does not create passing evidence. Malformed objects return a blocked result rather than throwing into the workflow. `verify_files=False` supports offline inspection only and can never permit approval.

The subject binds the selected queue to the full model and jobs, original planning manifest and frozen decision identity, exact decision inputs, deadline and travel, observed completion/time/location/version, protocol, planner source, assurance source, numerical-adapter source, and engine/native/interface/adapter hashes. It also binds all ten canonical scientific plan fields, including its displayed aggregate scores, scenario results, reasons and plan identifier; copying an audit onto altered displayed planning evidence is rejected. Evidence retains every raw run's input/report/output/log/request/result manifest, checksums and complete request identity.

These checks establish local integrity, not a cryptographic signature or role authentication. An actor who controls the application, database and all artifacts can manufacture evidence. The reference interface still uses named audit labels rather than authenticated operational authority.

## Verification boundary

The assurance unit suite uses tiny arithmetic hydraulic doubles and explicitly labelled artificial raw files. They test prefix harm, missing numerical evidence, step-classification flips, horizon failures, stale identities, queue/input binding, tampering and missing results. They do not supply hydraulic evidence. Real-engine development results are recorded separately under `evidence/`.

The first reference audit retains **J4 → J1 → J3 → J2**, selected before the new stress calculations. It passes ten of its fifteen required cases and fails five, with no unresolved case. H2 increases B2 spill by 529.994908 m³ in the final achieved state. S_ROUGH_HIGH increases A1 spill by 0.334793 m³. S_RESTRICTION increases A1 spill by 2.313124 m³ after the first job and 11.033295 m³ finally. S_STAGE increases confluence J spill by 0.065366 m³ at a prefix. S_COMPOUND increases J spill by 49.944085 m³ at a prefix and 502.326096 m³ finally. Every increase is compared against the unchanged 0.05 m³ tolerance; these failures are not explained away by lower total spill. See `evidence/assurance-reference.json` for the exact metrics and raw run identities.

A subsequent requested **development census**, explicitly declared after the reference audit had been revealed, assessed all 28 original planning-admissible queues. Only no additional work passed; 22 nonempty queues failed and five were unresolved. No nonempty queue passed. The unresolved queues reach J1+J2 in S_STAGE: node T spill is 0.901553 m³ at 0.5 s versus 0.829429 m³ at 0.25 s, a 0.072124 m³ difference above the 0.05 m³ convergence tolerance. No routing step, tolerance or stress case was changed to turn these into passes. The census produces no replacement recommendation. Its queue freeze, compact outcomes and shared raw evidence index are `evidence/assurance-census-freeze.json`, `evidence/assurance-development-census.json` and `evidence/assurance-census-runs.json`.

Any later choice informed by these now-revealed stress results is method development. A genuine performance claim needs separately frozen, independently acquired events, mechanisms or catchments, followed by appropriate measured validation. Passing this finite audit cannot close those scientific gaps.
