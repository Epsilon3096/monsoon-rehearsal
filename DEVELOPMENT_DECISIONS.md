# Development decisions after the Gemini suggestions

**14 October 2026.** This is a strategy and evidence review of the four supplied suggestions. It adds decisions for the next development pass; it does not change frozen models, protocols, numerical tolerances, policies or results. No interview, laboratory measurement, site approval, purchase or outreach is recorded as completed by this review.

The strongest current proposition is an inspectable maintenance decision and evidence workflow. The software can compare feasible work, show location-specific consequences and refuse an unsupported plan. A superior scheduling algorithm, measured flood reduction and operator demand remain unproved. The next work should strengthen those missing links while useful software development continues.

## Adopt, adapt or reject

Confidence below describes confidence in the decision given the available evidence; it is not a probability of commercial success or hydraulic accuracy.

| Suggestion | Decision and confidence | Application to this project |
|---|---|---|
| Do not let an operator interview stop all building. | **Adopt — high.** | The prototype, frozen comparisons and research workspace already exist. Continue software contracts, instrument integration, record preparation and bench development in parallel with arranging a genuine review. An interview remains necessary to establish the real decision, credible comparator and user value; it is not a prerequisite to writing every line of code. |
| Simplify crew work using a fixed cutoff and evaluate the resulting geometry. | **Adapt — high within a declared scope.** | Use a common deadline, conservative start bounds and the actual verified completed/restored subset. This supports the current dry, pre-event research model only when its initial-state and boundary assumptions remain defensible. A clock cutoff alone does not validate the hydraulic state. |
| Treat unfinished work as the original condition with complete accuracy. | **Reject — high.** | Not crediting an unverified restoration is necessary, but does not prove that the real asset is unchanged. Disturbed restrictions, temporary works or released stored water could leave another condition. Record the condition as unresolved unless an unchanged, intermediate or restored state is independently verified and represented. |
| Build and measure a repeatable rig early. | **Adopt — high for the approach; apparatus adequacy remains to be reviewed.** | Start measurement and geometry development now. Use repeatable, measured inserts, fixed outlet geometry, synchronized boundary/response measurements and independently reset runs. Treat commissioning and calibration as development. Preserve separately frozen validation events; a working display or a visually convincing flow demonstration is not validation. |
| Lead with downstream-first as a universal gold standard that can waste three hours, while this system finds the highest-impact jobs. | **Reject as an evidence claim — high. Adapt the communication goal.** | No independently validated operator baseline or measured wasted time has been supplied. Three hours is the reference work window, not demonstrated waste. The revised method ties the equally screened downstream, marginal and nominal methods because all abstain. Lead confidently with demonstrated product capabilities and state the benefit hypothesis separately. |

## What the results actually say

The original robust queue tied the adaptive marginal baseline in all four planning cases and both revealed holdouts. In H2 it reduced total model spill but increased B2 spill from **280.776902 to 810.771811 m³**, an increase of **529.994908 m³**. That makes the policy inadmissible under the unchanged location safeguard. Downstream-first was supported in that H2 comparison. These results do not support dismissing that heuristic as incompetent. See [original holdout evidence](evidence/holdouts.json) and [recorded verification](evidence/v0.3/VERIFICATION.md).

The v0.3 observation-conditioned policy, screened marginal method, screened downstream-first method and screened deterministic nominal method each abstained in **all 10 designed rows**. Their paired spill comparisons are **10 ties, 0 wins and 0 losses** against one another and no additional work. Eight rows have valid synthetic observations; two deliberately test missing/stale observations. Every possible first job failed a protected-location check somewhere in each valid observation context, without exhausting the computation budget. No nonempty sequential queue survived that screen. See [policy results](evidence/v0.3/policy-results.json) and [interpretation](evidence/v0.3/policy-interpretation.md).

The historical unscreened queue remains a diagnostic: three admissible positives, one tie, five protected-prefix losses and one unresolved duration overrun. Those occasional positive outcomes do not become evidence that the new operational policy is superior. The experiment uses one reused synthetic topology, with zero measured events and zero independent catchments. Its 636 numerical configurations are convergence and reproducibility evidence, not 636 experimental samples. See [local integrity review](evidence/v0.3/policy-review.json).

This weakens the algorithm-led story materially. The product may still be valuable through clearer consequences, controlled approval, traceability and fewer unsupported decisions. That workflow value is a hypothesis requiring users and measured tasks; a test suite alone cannot establish it.

## The cutoff contract

The static-geometry simplification is a useful restricted experiment. It must be expressed as a condition on the physical state, not as a guarantee created by a deadline.

| Condition at the cutoff | Treatment |
|---|---|
| Job never started; unchanged condition remains supported by the observation contract | Retain the verified pre-work geometry, with appropriate uncertainty. |
| Job completed and its restored condition accepted | Apply the measured/reviewed restoration state. Reporting completion alone gives no hydraulic credit. |
| Job started, then the original condition was demonstrably reinstated and verified | A return to pre-work geometry may be represented only with that evidence. Reassess initial water conditions and timing as well. |
| A supported intermediate condition is measured and verified | Use a separately defined and tested intermediate model state. Do not interpolate restoration from percent effort. The present binary reference does not establish this extension. |
| Work was interrupted, restoration is unverified, or the asset was disturbed without a supported state | Mark the condition unresolved. Preserve the record and block supported replanning or approval of additional work that depends on it. Do not substitute unchanged geometry. |

The modelled hydraulic event must follow the represented restoration phase. Travel, setup, work, verification, disposal/restoration and return must be covered without double counting. The dispatch gate uses known bounds; the actual duration is revealed after dispatch. Exceeding a duration bound is an exception even if return still occurs before the overall deadline. The original diagnostic demonstrates exactly that distinction in V3-E08.

“Dry work” does not mean “all water is absent.” Storage, background flow, receiving-stage changes or intervention history can make a future initial state differ from the state observed before work. The v0.3 bench research assumes prescribed initial storage and a controlled fixed receiving stage; it does not establish those controls in a real apparatus or natural catchment.

EPA describes dynamic-wave routing as a coupled mass/momentum calculation that represents storage, backwater and reverse flow. Its initial-depth inputs and hot-start files explicitly describe hydraulic state. **Our inference:** merely choosing a completed subset, stopping a crew or loading a restart cannot establish that a changed-geometry transition preserves the relevant water state. Continuous wet-work modelling would need separate conservation, restart and measured-transition checks. [EPA SWMM 5.2 User’s Manual, sections 3.4.5, 11.7.2 and storage properties](https://www.epa.gov/system/files/documents/2022-02/storm-water-management-model-users-manual-version-5.2.pdf).

## Start the rig early, with measurements as the deliverable

Use the existing [physical validation plan](PHYSICAL_VALIDATION.md) and [frozen prospective bench protocol](data/templates/bench_protocol_v1.json). The apparatus dimensions and instrument choices still need laboratory review and an as-built survey. A new measured bench model must have a separate identity from the frozen synthetic catchment. This review does not alter the prospective acceptance thresholds or its planned validation events.

The immediate practical deliverable is a reproducible measured configuration: surveyed inverts, sections and storage volume relation; repeatable restriction inserts; fixed and recorded outlet settings; sensor calibration and uncertainty; measured inflow, signed receiving exchange, all collector spills and retained water; synchronized clocks; and a documented reset. Collect actual receiving-stage and initial-state observations rather than assuming the control achieved its target.

Commission the measurement chain and check mass balance before asking the rig to discriminate policies. Develop roughness and intervention representations from calibration runs, then freeze the model before withheld response measurements. Compare current, intermediate where supported, and restored conditions by location. Preserve failed resets, missing readings, saturation and adverse effects. A rerun is another recorded event, not a replacement for an inconvenient result.

Assign run order before examining outcomes, using a suitable randomized or blocked design agreed with the laboratory. Independently reset repeated runs and distinguish those repeats from re-reading the same trace or rerunning a deterministic solver. Randomization of treatment order and explicit replication are established experimental-design tools; their suitability and analysis still depend on this apparatus. [NIST/SEMATECH experimental-design handbook](https://www.itl.nist.gov/div898/handbook/pri/section3/pri331.htm).

Model configuration, sensitivity and uncertainty assessment, and comparison against observations are separate activities. Validation should use different conditions or periods from fitting, with error assessed against the intended use. **Project decision:** keep calibration and validation event identities separate and do not narrow uncertainty or select a favourable restoration after viewing validation results. [EPA configuration and calibration guidance](https://www.epa.gov/n-steps-online/mechanistic-modeling-configuration-calibration).

A bench result can support the tested apparatus and envelope. It cannot by itself establish full-scale township flood reduction, rainfall-runoff accuracy, an operator's work procedure or commercial savings. The miniature rig is not automatically a dynamically similar scale model.

## Campus operator and lecturer reviews answer different questions

| Participant | Useful evidence they can supply | What their involvement alone cannot establish |
|---|---|---|
| Campus estates/facilities drainage supervisor, maintenance engineer or contractor who actually plans the work | A real work window; candidate and mandatory jobs; crew/access/restoration constraints; actual conditional priorities; records; missed assumptions; whether the tool changes a decision | SDP practice, demand across townships, physical model validity or permission for another organisation's pilot |
| Lecturer or laboratory researcher with relevant hydraulics/modelling expertise | Technical critique, instrument/experiment design, initial-state and boundary review, calibration/uncertainty review, laboratory supervision within their role | An authentic operational comparator, customer demand or site authority merely because of academic expertise |
| A person who genuinely holds both roles | Both contributions, recorded with the corresponding responsibilities and evidence | Automatic independence of all reviews or automatic authority beyond that person's remit |

A campus operator is a sensible accessible first collaborator if their maintenance decision matches the product's scope. Capture their baseline before revealing the model; retain a real adaptive rule if that is what they use rather than forcing it into an inferior static queue. Record cases where everything fits, no work is appropriate, the simple rule is adequate or the product adds no value. Preserve the pre-disclosure record and later disagreements through the existing [operator/shadow workflow](OPERATIONS.md).

No source confirming a briefing statement attributed to **Dr Su Ki**, or a specific campus endorsement, was available to this review. Do not present that attribution as verified. The campus route can be justified on its own practical merits; a later supplied recording, slide or official transcript can establish what was actually said.

## Scientific and product claim ledger

| Claim | Status on 14 October 2026 | What can be said, or what would establish it |
|---|---|---|
| The prototype computes feasible queues under declared crew-time constraints. | **Implemented and tested within the reference contract.** | It enumerates 65 four-job queues and uses bound-gated causal dispatch. It does not guarantee real job durations or completion. |
| The prototype inspects achieved prefixes and rejects supported location-level harm. | **Implemented and demonstrated on synthetic evidence.** | Per-location checks, numerical gates, failure records and refusal are visible. This is not a universal no-harm guarantee. |
| Model output, review, tickets, reported completion and accepted restoration are traceable. | **Implemented software capability.** | Demonstrate the recorded workflow and stale/tampered-evidence refusal. Distinguish arithmetic workflow fixtures from real physical completion. |
| Initial-state observations can unlock useful nonempty work while preserving uncertainty. | **Tested hypothesis without demonstrated benefit in v0.3.** | All four screened policies abstain. New measured evidence or a separately registered evaluation is required; do not manufacture a positive case. |
| The revised ranker outperforms competent downstream/marginal/nominal policies. | **Not established; current comparison ties.** | Use equally informed and constrained baselines in new cases, report losses and abstentions, and prefer the simpler method when it suffices. |
| An unfinished job leaves the original hydraulic condition unchanged. | **Unsupported as a general claim.** | Require observed and verified restoration/unchanged condition or retain an unresolved state. |
| The hydraulic model predicts actual restoration effects accurately enough for the intended decision. | **Pending measured corroboration.** | Independent response observations, uncertainty and a reviewed model for the actual bench/site are required. Numerical convergence alone is insufficient. |
| The product saves planning time or improves decision clarity. | **Product hypothesis.** | Observe representative users performing matched tasks; record time, errors, disagreement, refusal comprehension and existing-tool comparisons. Do not invent a time saving. |
| The product reduces flood damage, saves money or is ready for live township dispatch. | **Not established.** | Requires the appropriate site, causal/value evidence and responsible operational approval. Node spill is not property damage. |
| The idea has competition or named expert endorsement. | **Unverified unless an actual source is supplied.** | Retain exact, attributable evidence and distinguish an opinion from a technical or operational approval. |

This separation follows the general distinction between code verification, comparison with observations, uncertainty assessment and suitability for a specific application. None substitutes for all the others. [EPA guidance on development and evaluation of environmental models](https://www.epa.gov/sites/default/files/2015-04/documents/cred_guidance_0309.pdf).

## Confident wording that the evidence supports

**Short product line:** “Rehearse the maintenance window. Inspect the consequences. Require evidence before approval.”

**Functional description:** “Monsoon Rehearsal links achievable drainage-maintenance schedules to inspectable hydraulic comparisons, location-level checks and a traceable review-to-verification workflow.”

**Evidence sentence:** “The prototype runs real SWMM calculations and preserves failures. In its latest frozen synthetic comparison, the revised policy and three screened alternatives all chose no additional work; scheduling superiority and field benefit remain to be established.”

**Future benefit hypothesis:** “We are testing whether better condition evidence and clearer consequence review help teams make useful maintenance decisions within their available work window.”

Use “best under the declared finite model, objective, constraints and resolved evidence” only where that precise optimisation claim has been established. Avoid the unrestricted phrase “highest impact.” Avoid universal “gold standard,” “three hours wasted,” “100% accurate,” “floods prevented” and “field-ready” claims without their respective evidence.

## Parallel work and the gates that remain

| Track to advance now | Reviewable next output | Gate it must respect |
|---|---|---|
| Software | Clear cutoff/physical-state reporting; explicit unresolved interruption handling; evidence capture and comparison export; instrument-import exercises using clearly labelled fixtures; regression checks | Existing completion reporting must not silently become hydraulic restoration. Preserve frozen v0.1–v0.3 results and source identities. Imported files remain staged until separately reviewed. |
| Bench | Reviewed apparatus/measurement specification, surveyed reproducible geometry, calibrated acquisition, recorded commissioning/reset procedure and distinct calibration runs | Review instrument capability and freeze the as-built model and validation design before withheld measurements. Any revised protocol is a new version, not an edit to a failed outcome. |
| Operator | One actual decision walkthrough and undisclosed baseline from a person responsible for that work; explicit assumptions and acceptance criteria | No invented interview or queue. Keep academic critique separate from operational evidence. The user arranges contact; none has been sent here. |
| Evidence analysis | Per-location measured-versus-modelled response, uncertainty and failure explanation; a new prospective comparison only when justified | Do not reuse revealed cases as unseen validation or count numerical refinements as independent events. Retain equal information and constraints across methods. |

These tracks can proceed concurrently. Field deployment still depends on an accepted site/data contract, surveyed and calibrated model, credible observation and work-state handling, operator-reviewed comparisons, prospective shadow evidence and the responsible site's approval of any pilot. A deadline, completed interview, laboratory demonstration or passing software test cannot alone satisfy those gates. See [validation plan](VALIDATION_PLAN.md).

There are also legitimate reasons to narrow or change the product. If operators seldom face consequential discretionary choices, a priority optimiser may address the wrong problem. If measured uncertainty still leaves every first job unsupported, adding a more elaborate ranking algorithm will not make work admissible; investigate model suitability, observation quality and authorised intervention scope. If a simpler rule is sufficient, use it. Retain an assurance/record product only if users demonstrate value in it. If neither scheduling nor workflow value emerges, rescope rather than constructing favourable scenarios or polishing an unsupported claim.
