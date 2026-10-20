# Monsoon Rehearsal v0.6 — original model and plan assurance regression verification

Generated 2026-10-15T13:41:04.665161+00:00.

This records software and numerical verification on a frozen synthetic catchment. No physical rig, site survey, field inspection, forecast connection, or measured flood-risk reduction is represented.

## Executed checks

- Automated tests: **802**; failures **0**; errors **0**.
- EPA SWMM 5.2.4: **144** state/scenario pairs, **288** requested evaluations at **0.5 and 0.25 seconds**, representing **260** distinct run identities. Equivalent pre-restored diagnostic states and cached results reuse evidence; these are not independent replicates.
- Maximum absolute routing continuity error across both steps: **0.381930%**.
- Step-halving spill tolerance: max(0.05 m³, 2% of the larger magnitude), per protected node and total.
- Horizon check: **passed** for event adequacy at 180 vs 360 minutes. Full per-state diagnostics are in `horizon.json`; D1 remains sensitive to the imposed-stage cold-start transient and is not claimed as a complete-event total.
- The initial 1-second step failed the declared convergence tolerance in a high-tailwater diagnostic. Refining the numerical step globally to 0.5 seconds resolved it; geometry, forcing, policy, and tolerance were not tuned to the ranking.
- Real selected-plan stress audit: **failed**. Its blocked draft is durable, review is refused, and no ticket is issued: **passed**.
- Real no-additional-work audit: **passed**. Review and approval refer only to its empty queue; an attempt to issue a job ticket is refused: **passed**.
- Full approval → ticket → assignment → start → report → verification → close → observed-state replan is covered by explicitly labelled arithmetic software fixtures in the automated tests. Those metrics and inspections are not real SWMM or field evidence.
- Verification uses an isolated database; the interactive workspace is not altered. The original v0.1 evidence remains historical and is not upgraded into a passing v0.2 audit.

## Planning result and limits

The exact search evaluated 65 priority queues across four planning scenarios: 28 supported, 37 inadmissible, 0 unresolved.

The selected priority queue is **J4 → J1 → J3 → J2**, with worst-scenario modeled node spill **0.538489 m³**. A priority queue is scanned for the next eligible fitting job; it is not a promise to finish all jobs.

**The adaptive marginal baseline ties the robust queue in every planning scenario. This case does not establish an optimisation advantage over that strong baseline.**

## Previously revealed frozen-policy holdouts

| Method | Scenario | Status | Node spill (m³) | Completed jobs |
|---|---|---|---:|---|
| no_work | H1 | supported | 123.816961 | none |
| no_work | H2 | supported | 1219.608507 | none |
| downstream_first | H1 | inadmissible | 95.537320 | J1 |
| downstream_first | H2 | supported | 1036.264122 | J1, J2 |
| marginal_benefit | H1 | supported | 0.007195 | J2, J4 |
| marginal_benefit | H2 | inadmissible | 810.771811 | J3, J4 |
| robust | H1 | supported | 0.007195 | J2, J4 |
| robust | H2 | inadmissible | 810.771811 | J3, J4 |
| deterministic_nominal | H1 | inadmissible | 0.007195 | J2, J4 |
| deterministic_nominal | H2 | supported | 893.072220 | J2, J4 |

**H2 makes the robust and adaptive marginal policies inadmissible under the location-level screen.** A smaller total spill cannot override worsening at a protected node. The result is retained without retuning. Every completed prefix is screened, so a plan with a harmless final state may still fail because of an earlier achieved state.

The hindsight oracle is separately labelled and is never an operational competitor. These are prespecified within-network synthetic holdouts, now revealed, not an independent field trial. v0.2 explicitly includes H1/H2 with the declared stress cases as development evidence; a software-verification pass must not be read as approval of a candidate that fails those cases.

## Evidence

`verification.json` pins source and model hashes. `hydraulics.json` lists every original state/scenario comparison. `planning.json` contains all queues, rejections, baselines and frozen policies. `holdouts.json` preserves every revealed outcome and oracle. `baseline-comparisons.csv` is the compact comparison table. `selected-plan-audit.json` retains the real candidate's failures; `workflow-blocked.json` proves its refusal. `no-work-audit.json` retains the passing empty-queue audit. `workflow.json` contains both immutable plans and their events, with no work ticket or physical observation. `pytest.xml` records the separate arithmetic workflow exercises and the remaining automated tests.

Raw SWMM inputs, reports, binary outputs, manifests and logs remain under `var/hydraulic_runs/` on the machine that ran verification. Absolute cache paths are machine-local and can be regenerated. The source archive includes the compact evidence, not the entire raw cache.

## Still required before real-world use

Surveyed geometry and initial conditions; site calibration; bench/field intervention validation; operator-reviewed baseline; travel and duration data; real forecast integration and calibration; production dispatch authentication and authorisation; additional catchments and independent holdouts. Dynamic wet-work transition modelling is required only if that scope is added; the MVP retains verified pre-event states. v0.3 research records have local authenticated roles, but the legacy demonstration ticket workflow remains separate. No first-prize or field-safety guarantee is made.
