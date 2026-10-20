# Monsoon Rehearsal — prototype verification

**Historical v0.1 report.** The current v0.2 report is `evidence/v0.2/VERIFICATION.md`. Its mandatory development audit blocks the original nonempty recommendation. The original results below remain evidence of the earlier numerical/software checks; earlier approvals are not a v0.2 audit pass.

Generated 2026-10-13T14:20:25.058742+00:00.

This records software and numerical verification on a frozen synthetic catchment. No physical rig, site survey, field inspection, forecast connection, or measured flood-risk reduction is represented.

## Executed checks

- Automated tests: **137**; failures **0**; errors **0**.
- EPA SWMM 5.2.4: **144** state/scenario pairs, **288** requested evaluations at **0.5 and 0.25 seconds**, representing **260** distinct run identities. Equivalent pre-restored diagnostic states and cached results reuse evidence; these are not independent replicates.
- Maximum absolute routing continuity error across both steps: **0.381930%**.
- Step-halving spill tolerance: max(0.05 m³, 2% of the larger magnitude), per protected node and total.
- Horizon check: **passed** for event adequacy at 180 vs 360 minutes. Full per-state diagnostics are in `evidence/horizon.json`; D1 remains sensitive to the imposed-stage cold-start transient and is not claimed as a complete-event total.
- The initial 1-second step failed the declared convergence tolerance in a high-tailwater diagnostic. Refining the numerical step globally to 0.5 seconds resolved it; geometry, forcing, policy, and tolerance were not tuned to the ranking.
- Full plan → review → approval → ticket → assignment → start → report → verification → close → replan: **passed**.
- Actual observations use an isolated verification database and synthetic evidence; the interactive workspace is not altered.

## Planning result and limits

The exact search evaluated 65 priority queues across four planning scenarios: 28 supported, 37 inadmissible, 0 unresolved.

The selected priority queue is **J4 → J1 → J3 → J2**, with worst-scenario modeled node spill **0.538489 m³**. A priority queue is scanned for the next eligible fitting job; it is not a promise to finish all jobs.

**The adaptive marginal baseline ties the robust queue in every planning scenario. This case does not establish an optimisation advantage over that strong baseline.**

## Frozen-policy holdouts

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

The hindsight oracle is separately labelled and is never an operational competitor. These are prespecified within-network synthetic holdouts, now revealed, not an independent field trial.

## Evidence

`evidence/verification.json` pins source and model hashes. `hydraulics.json` lists every state/scenario comparison. `planning.json` contains all queues, rejections, baselines and frozen policies. `holdouts.json` preserves every outcome and oracle. `baseline-comparisons.csv` is the compact comparison table. `workflow.json` records the immutable plan and audit events; `replanning.json` starts from the verified condition and observed clock. `pytest.xml` contains executed test results.

Raw SWMM inputs, reports, binary outputs, manifests and logs remain under `var/hydraulic_runs/` on the machine that ran verification. Absolute cache paths are machine-local and can be regenerated. The source archive includes the compact evidence, not the entire raw cache.

## Still required before real-world use

Surveyed geometry and initial conditions; site calibration; bench/field intervention validation; operator-reviewed baseline; travel and duration data; dynamic wet-work transition modeling; real forecast integration and calibration; authenticated roles; additional catchments and independent holdouts. No first-prize or field-safety guarantee is made.

## Final interface layout check

All five UI acceptance tests passed again after placing the full priority queue on its own line to prevent visual truncation. The hydraulic, planning and workflow sources did not change. Results are recorded in `evidence/pytest-ui-final.xml`; the final app source hash is in `verification.json`. Dependency consistency and Windows launcher syntax also passed.
