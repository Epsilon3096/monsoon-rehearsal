# Independent site/measurement agent review of the v0.3 policy study

Reviewed 14 October 2026, approximately 10:08 UTC. Scope: read-only inspection of `monsoon/observed_policy.py`, `monsoon/policy_evaluation.py`, `data/policy_v3_protocol.json`, the relevant dispatch implementation/tests, `monsoon/validation_ui.py`, and the completed frozen development/results records. No SWMM runs were requested, no frozen source was changed, and no new result was substituted into the study. Two API checks used an explicitly unavailable arithmetic sentinel callback only.

The policy/protocol source hashes matched the implementation freeze at review. Protocol identity: `932dca0d0dae352ea7b3b863c796670cc1bfd9c18025fc8bfe60d81b5481fba2`. Freeze identity: `411ce36a77f88cdd4b22335617aa7b941973b3c2a7bc7393330fe94925911e03`. Reviewed result-file raw SHA-256: `d208470c693f01b18276bc9965306688f94f56521a55b355fd803565597d0f02`. Reviewed UI raw SHA-256: `a5532c87d56bb68df5989718183197458aa56fd6d407100c530578cac7e71aa8`.

## Conclusion for the recorded study

No blocking causal-information or unequal-screening defect was found in the frozen `evaluate_experiment` path. The recorded result establishes **no nonempty policy advantage**: all four operational methods abstained in all ten event rows and tied the no-work reference. LOW and HIGH each rejected every first intervention; MISSING and STALE closed dispatch because their observations were invalid. The historical unscreened diagnostic retained three positive outcomes, one tie, five protected-prefix losses and one unresolved duration overrun. These are ten designed same-topology synthetic rows, not independent measured replications.

The result is consistent with the prespecified refusal rules. It is not proof that the revised algorithm is physically safe, useful in the field, or superior to a simpler baseline. The overrun event did not exercise nonempty operational dispatch because all screened methods abstained; the historical diagnostic and separate arithmetic tests exercise the exception logic.

## Finding F1 — replay API does not enforce the declared event binding (P2, not a recorded-study failure)

`monsoon/observed_policy.py:349`–`361` verifies the snapshot, sources, case and protocol, then checks only `phase == "evaluation"` and that the event ID is not a development ID. It does not require the event contents to equal a member of `protocol["evaluation_events"]`, or require the event's `observation_id` to match the snapshot's observation.

Reproduction without SWMM: load the frozen LOW snapshot from `policy-development.json`, then call `replay_observed_policy` with the protocol's HIGH event `V3-E05` and an unavailable sentinel callback. The API accepts it and returns rows for `V3-E05` carrying observation `LOW`; the callback is reached three times. Replacing a LOW event ID with `UNSEALED-REVIEW-SENTINEL` is also accepted and reaches the callback three times. Every sentinel result remains unresolved, so this review did not generate a favorable hydraulic score.

Impact is bounded: `policy_evaluation.py:208`–`209` currently selects the matching snapshot directly from each exact frozen protocol event, so the completed study uses the correct binding. A future direct caller could accidentally evaluate a different event/context while believing the replay guard enforced a sealed evaluation. Before exposing this API beyond the frozen runner, bind the complete event identity and observation identity, or provide a clearly separate research-only replay function. Preserve this study; any scientific-source correction must be disclosed and must not rewrite its original freeze.

## Finding F2 — make the all-abstention result explicit on the results screen (communication follow-up)

`monsoon/validation_ui.py` displays the abstention counts, paired ties, selected jobs, diagnostic flag, underlying JSON and scope limitations. It does not currently state the experiment's central result in a prominent sentence. Add a result-specific statement that all four operational methods abstained in all ten events and no nonempty benefit or algorithmic superiority was demonstrated. This can be a UI-only clarification; no policy threshold, source freeze or numerical result needs to change.

## Checks that support the scoped conclusion

- **Conditioning:** the observation whitelist excludes future hydraulic/duration fields; timestamps, availability, age, units and datums are checked. All eleven retained unobserved development profiles remain, crossed with four storage/stage error corners and nominal/bound durations, plus one nominal centre. The protocol explicitly says finite corners do not guarantee interior worst cases and that observations/boundaries are hypothetical bench controls.
- **Equal information:** operational methods share the same observation-conditioned state table, protected-node screen, numerical gate, job bounds, travel/return allowance and clock. The nominal method differs in its objective, not its safety information. The historical unscreened queue is clearly a diagnostic, excluded from claimed superiority baselines. No real operator plan is fabricated.
- **Causality:** the runner completes all policy selection before evaluation replay. The selector receives eligible jobs, verified completed set, elapsed time and location. `planning.py:150`–`153` reads realised duration only after job selection. The actual evaluation forcing reaches hydraulic scoring, not the chooser.
- **Fail retention:** every scored state must pass the full required development grid. Rejected/unresolved states retain their first rejection certificate and receive no positive score. Evaluation checks every achieved prefix; protected-prefix harm takes precedence over a lower total spill. Duration overruns leave restoration unverified and the outcome unresolved.
- **Metrics:** per-location spill, depth and threshold duration remain available; only spill is protected by the current decision gate. Summary categories distinguish abstention, paired spill ties, loss and unresolved evidence. Designed rows, reused network count, measured-event count and statistical-sample-size limitation are explicit.
- **Data-intake UI:** checks remain tied to the currently uploaded/pasted source. Changed site or measurement input invalidates the displayed calculation. Synthetic arithmetic is labelled, unknowns are not filled, and passing arithmetic is explicitly separated from physical validation and site activation.

This review is source/record inspection, not an independent hydraulic recomputation, physical experiment, operator acceptance, external blind evaluation or production security assessment.

## Post-review adapter for F1 — original study preserved

A separate public adapter, `monsoon.policy_replay.replay_frozen_event(snapshot, case, evaluation_event, hydraulic_fn)`, now guards replay of this **recorded study only**. It is not an API for a new policy, new site, new observation, edited scenario or new evaluation. The original frozen `replay_observed_policy`, runner, protocol, implementation freeze and recorded results were not edited. The recorded runner was already correct because it supplied each exact protocol event with that event's matching observation snapshot.

The adapter snapshots caller inputs once, loads the original protocol/freeze/development records, and validates their pinned identities. It verifies the current frozen source and engine identities, exact canonical event membership, matching event/policy observation ID, exact recorded policy snapshot and matching case before reaching the underlying runner. Altered or re-signed policies are rejected by comparison with the pinned recorded policy set. Missing records, mismatched observations and unlisted or edited events raise `ValueError`; no hydraulic callback is invoked. Object-key ordering does not alter canonical identity.

Recorded policy-set canonical SHA-256: `be97da4d0bf25de9012ac31b077841157e2687d299307da0c1d33ffc4c98e749`. The adapter preserves the original runner's return format and its numerical gates. Local identities establish record integrity, not independent attestation or operational permission. Later studies need a separately registered contract instead of changing these pinned values to make an edited event pass.

Targeted verification: **21 tests passed** in `tests/test_policy_replay.py`, including LOW/HIGH mismatch, unlisted and modified events, re-signed edited policy, changed case/source/engine/protocol/freeze/development records, missing records, malformed inputs, caller mutation after snapshot, and an exact event passed to a mocked original replay. No SWMM computation was run by these tests or this adapter follow-up.
