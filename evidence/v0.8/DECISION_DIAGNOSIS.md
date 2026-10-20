# Why the SWMM product currently recommends no additional work

Read-only assessment of saved evidence and source, 17 October 2026. No engine runs, new scenario selection, scientific-source edits, threshold changes or custom-solver work were performed.

**Conclusion:** a useful consequence-comparison product is already supported, but no nonempty maintenance recommendation passes the current full decision envelope. The immediate obstacle is the combination of the represented interventions and the decision contract, not a lack of scheduling sophistication or a general inability of SWMM to show benefits.

## What is actually failing

`outputs/monsoon-rehearsal/evidence/planning.json` enumerates 65 queues: 28 supported under the original four planning scenarios, 37 inadmissible, zero unresolved. Thus “every action always fails” is incorrect. For example, J4 alone reduces modelled P1 total spill from 54.7758548777 to 0.5384892487 m³ and P3 spill from 364.1994974813 to 188.0693472802 m³, without violating those planning-scenario checks.

The subsequent mandatory screen is broader. `evidence/assurance-development-census.json` covers the complete 28 originally planning-admissible queues across 15 planning/holdout/stress cases. Of the 27 nonempty queues, 22 fail and five are numerically unresolved. **All five unresolved queues also have resolved protected-location failures in other cases.** Fixing their numerical issue alone would therefore admit none. The unresolved cases are S_STAGE spill step-halving failures at T, associated with queues beginning J2 then J1. The empty queue alone passes the full screen.

Resolved examples show more than a borderline tolerance problem:

| Action and case | Protected-location increase | Allowed increase |
|---|---:|---:|
| J2, H1, B2 | 1.9183162084 m³ | 0.05 m³ |
| J4, S_RESTRICTION, A1 | 2.3131242698 m³ | 0.05 m³ |
| J4, S_COMPOUND, J | 49.9440851597 m³ | 0.05 m³ |
| J4 then J3, H2, B2 | 529.994908 m³ | 0.05 m³ |

The last example reduces total spill from 1,219.608507 to 810.771811 m³ while B2 rises from 280.776902 to 810.771811 m³ (`evidence/planner-review.md`, `evidence/holdouts.json`). Lower total spill is therefore not sufficient for acceptance.

## Mechanism and role of the rule

The four jobs restore clear widths. They do not add storage capacity, lower receiving water, or enlarge the designed storage outlet (`data/reference_case.json`; `monsoon/hydraulics.py`). Two branches share downstream conveyance and online storage. It is physically plausible for improved conveyance to move a bottleneck or admit more water to a constrained downstream location. The saved node totals demonstrate redistribution of modelled spill; the specific causal flow path remains an interpretation, not measured validation.

The decision rule requires every protected node to avoid more than 0.05 m³ extra spill in every achieved prefix and every required scenario (`monsoon/planning.py`, `monsoon/assurance.py`). This is a demanding non-worsening contract, not a total-benefit maximizer. Checking prefixes is material because work may stop before the full queue completes. A harmful first job cannot be rescued by a beneficial final combination under this contract.

The v0.3 observation-conditioned study confirms that first-job bottleneck. `evidence/v0.3/policy-development.json` retains all eleven forcing/roughness/restriction profiles, crossed with prescribed observation-error corners: 89 decision rows / 45 distinct hydraulic configurations per valid synthetic observation context. All four first jobs have resolved failures in both LOW and HIGH contexts. Even the smallest first rejection is stable at both steps: HIGH J1 raises B1 spill by 0.0699124382 m³ at 0.5 s and 0.0605208533 m³ at 0.25 s. LOW J4 raises A1 by 0.0880196704 / 0.0878533130 m³. Other certificates reach 46.6957898163 m³. No computation-cap exhaustion caused these abstentions.

All four screened policies consequently abstain in all ten evaluation rows: eight valid-observation rows and two missing/stale controls. The historical unscreened queue has three positive event comparisons, but also five protected-prefix failures, one tie and one unresolved overrun (`evidence/v0.3/policy-results.json`, `policy-interpretation.md`). Those retrospectively favourable events do not authorize a new policy.

## Product decision and one bounded next test

Keep the current full-envelope recommendation blocked. Do not remove adverse cases, enlarge tolerances, select a favourable event after seeing its outcome, or search more queue orderings: all four first jobs already fail in the conditioned study. This is not evidence that drainage restoration or SWMM is fundamentally unsuitable; it is evidence that these four interventions, on this topology, with this information and non-worsening contract, provide no admissible nonempty action.

The next development test should be a **cached-evidence decision explanation**, with no hydraulic reruns: (1) J4/P1 shows the supported scenario-level benefit but the broader approval remains blocked; (2) J4→J3/H2 shows total improvement alongside B2 harm; (3) a J2→J1/S_STAGE record labels numerical uncertainty separately. Require exact saved numbers, action/state/scenario identities, failed-node reasons, and no dispatch-enabling status change. Stop that development step when those three cases are correctly represented; do not use it to claim useful scheduling superiority.

To pursue an actual positive recommendation later, first obtain an operator-nominated decision and evidence that independently justifies its scope: surveyed connectivity and geometry, the physical restoration change, antecedent storage and receiving-stage history, credible inflow/roughness/restriction bounds, and observed response plus work duration. Have the operator and engineering reviewer assess whether the spill-only non-worsening objective matches the real decision. Then prospectively define one baseline/intervention comparison and its acceptance/uncertainty limits before collecting response data. Stop if the intervention still harms a protected location, numerics remain unresolved, or external evidence cannot justify the envelope; do not iterate synthetic settings until a positive action appears.

All numbers above are synthetic model results. An empty recommendation is not a flood-safety claim, and the separate complex-bench SWMM accounting failures remain unchanged.
