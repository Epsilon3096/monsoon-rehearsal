# From a verified prototype to an observed decision

Working plan, 14 October 2026. The chosen first route is an instrumented bench network, followed by one small, bounded township drainage catchment. No real operator, site survey, sensor observations or engineer approval has been supplied. Software exercises and synthetic comparisons must remain labelled as such.

**Parallel execution update:** software development and bench preparation continue while interviews are sought. An operator gate validates the real problem and operating assumptions; it is not a prerequisite for coding. A campus facilities maintenance operator is the first practical workflow-review target; a civil engineering lecturer supplies separate technical review unless they also hold the actual operational role. `BENCH_BUILD.md` targets assembly/commissioning during 14–17 October, and the preparation tool generates unfilled run sheets without requiring a completed interview. `WORK_WINDOW.md` defines the early-stop audit; interrupted work never automatically becomes pre-work geometry. See `DEVELOPMENT_DECISIONS.md` for the full adopt/adapt/reject record.

## What must be established

| Stage | Concrete deliverable | Evidence needed to close the stage |
|---|---|---|
| Operator decision | Recorded maintenance window, feasible jobs, constraints, baseline captured before showing the model, and reviewed disagreements | A real drainage supervisor or engineer reviews their actual workflow and confirms what the decision changes |
| Physical mechanism | Surveyed geometry, measured restrictions, measured before/after restoration, boundary and initial-state observations, mass balance and withheld response comparisons | Matched physical observations; instrument uncertainty; reproducible model version; adequate agreement at the affected locations |
| Decision advantage | Frozen policy and common-information baselines, prospective inputs, complete paired results including losses and abstentions | New measured or independently representative cases, with a justified sample design; synthetic cases alone establish only their stated experiment |
| Operational preparation | Staged versioned site records, provenance, role checks, immutable review and prospective shadow records | Operator acceptance of the draft data contract, reviewed site model and organisation-specific access/retention rules |
| Shadow then pilot | Prospective model/operator decisions followed by actual observations; reviewed exceptions and stopping rules | An observed shadow trial and responsible site engineer's decision on whether a limited pilot is warranted |

A completed file or a checked box cannot establish physical validity, professional credentials or permission to carry out maintenance. The current software does not activate imported sites in the original engine or issue live work from the shadow workspace.

## 1. Operator review: obtain an uncontaminated comparator

Invite a drainage engineer or maintenance supervisor who actually decides or oversees maintenance. The participant should bring one recent real window with more authorised work than the crew could complete. A window where everything fits, or no work is justified, is useful too and must remain in the record.

Before showing any model ranking, record:

1. Site and asset scope, participant role, date, available crew and equipment.
2. The decision time, known weather/stage information, its availability time, restoration deadline and current stop rules.
3. Candidate jobs, mandatory jobs, access limitations, travel/setup/disposal/verification requirements and duration uncertainty.
4. Their actual priority or branching rule, reasons, expected completed subset, and circumstances that would change it. A static queue is a limited comparator if the operator uses a conditional rule; preserve that distinction.
5. What would constitute unacceptable downstream effects, incomplete restoration, a failed inspection or an unusable recommendation.

Seal the baseline record before revealing the model. Then record disagreements, missing facts, rejected assumptions and proposed changes. Preserve the earlier baseline if the participant changes their view after seeing the model. Ask whether the product would change a real decision or simply duplicate a known rule. Do not present a friendly testimonial as proof of demand or advantage.

Completion requires an accepted, bounded decision problem and data requirements. Until a participant supplies this, the interview workflow is prepared but the interview is not performed. No outreach has been sent by this work.

## 2. Physical investigation: target the failures

Retain the original synthetic model and adverse results. Use a separately versioned measured model for physical validation.

| Existing failure or uncertainty | Measurement that can discriminate the mechanism | Required comparison |
|---|---|---|
| H2 redirects spill to B2 | Initial stored volume, storage depth-area relation, B2 level, storage inlet discharge and receiving stage | No work versus the same verified restoration, with matched measured forcing and initial state |
| Roughness sensitivity changes the protected-location result | Water levels and discharge over several controlled flows in each actual section | Measured response against independently specified geometry and a calibrated roughness range; no single fitted event presented as validation |
| Restriction sensitivity harms the J4 prefix | Actual clear cross-section and obstruction shape, not an assumed percentage capacity | Before condition, intermediate achieved prefix and final condition under the same boundaries |
| Elevated receiving stage and cold-start effects | Receiving-stage time series, all relevant initial water levels, pre-event equilibrium or observed transient | A measured initialisation/spin-up procedure; keep constant controlled stage distinct from an unknown future river/tidal boundary |
| Timing or restoration overruns | Travel, work, restoration, verification and return times; interrupted physical condition | Prospective bound versus actual timing; no unverified job credited as restored |

The bench is a mechanism experiment. Its dimensions, material, sensors and flow range must be selected and surveyed by the experiment team; the synthetic township dimensions are not a ready-to-build physical rig drawing. Do not infer full-scale flood reductions from an unverified geometric scale conversion. Use measured inflows first. Rainfall-runoff calibration is a later, separate uncertainty layer.

Record inflow, signed boundary exchange including backflow, all exits/spill and change in stored water over matching intervals. Document unmeasured losses or volume compartments. Reject incomplete records for quantitative balance rather than silently filling gaps. Sensor calibration, resolution, timing, datum and uncertainty are part of the evidence. Predeclare acceptance targets suitable for the decision effect and instruments before collecting validation outcomes.

The detailed measurement contract and procedure are in `PHYSICAL_VALIDATION.md` and `data/templates/bench_protocol_v1.json`.

## 3. Revised policy and frozen comparison

The v0.3 research experiment asks whether observations of initial storage and controlled receiving stage help make a defensible decision while retaining uncertainty about inflows, restrictions, roughness and job durations. It does not assume those quantities become known because they are convenient.

**Executed result:** the revised policy and screened marginal, downstream-first and nominal alternatives each abstained in all ten designed events. Their paired comparisons all tie; no nonempty policy benefit is established. The historical unscreened queue had three positive results, one tie, five protected-location losses and one unresolved duration overrun. Ten designed rows on one reused synthetic network are not ten independent observations. Full frozen results, rejection certificates and computation cost are in `evidence/v0.3/policy-report.md`, `policy-results.json` and `policy-development.json`. Measure the disputed physical effects before expanding the algorithm or weakening its safeguards.

Freeze the complete input contract, implementation, numerical checks, policies, test cases and report rules before examining new outcomes. Preserve the freeze record and every failed/unresolved result. A bug fix after outcomes have been seen needs a declared revision; it does not restore a previously unseen test set.

Use equal information, crew limits, duration bounds and location safeguards for the revised policy and competent alternatives. Show no-work, screened downstream-first, adaptive marginal and nominal comparisons. Preserve the original queue as a historical diagnostic. Until an operator supplies an independent comparator, do not label any invented queue an operator baseline.

Report achieved prefixes, completed jobs, per-location and total spill, timing, deadline exceptions, refusal frequency and calculation cost. Lower total spill cannot compensate for disallowed harm at one protected location. Report ties and losses and keep unresolved numerics separate. A finite grid is not a probability distribution; multiple timesteps are not independent observations. If a simpler method ties, prefer it unless another measurable operational benefit supports the complexity.

## 4. Site intake and operational controls

The supplied schema is a draft for review, restricted to the structures it can check. Validate stable IDs, connections, units, coordinates, vertical datum, geometry, storage relation, observations, intervention scope and provenance. Missing values remain unknown. Unsupported structures or invalid references keep a package in draft. Show a comparison before a reviewer accepts a revision. Acceptance is a recorded data review, not hydraulic calibration or activation.

The authenticated research workspace covers staged packages, attachments, operator reviews and shadow records. It does not retrofit production identity management into the original synthetic ticket demonstration. Local account authentication does not verify an external professional qualification. Backups contain sensitive records and account hashes; keep them private and test recovery to a separate location.

## 5. Prospective shadow trial and pilot decision

Choose a real window before its outcome. Record only information already available at the decision time. Seal the operator plan and model snapshot, their versions and the trial protocol before the event. Later append observed work, timing, levels/spill where measured, exceptions, reasons for divergences and missing observations. Preserve append-only history rather than editing predictions to match what happened.

Shadow recommendations do not direct work. The actual operator continues their approved practice. One observed outcome describes one realised decision; it does not measure the unperformed maintenance counterfactual. Distinguish observed response from simulated alternative outcomes. Any causal benefit claim needs a justified experimental or observational design and uncertainty assessment.

Review every refusal, overrun, missing input and false confidence. Decide whether the data and decision are fit for a next supervised trial. A pilot requires the site's responsible engineer to define and approve its work envelope, permits, competence, stop rules, escalation and recovery, independently of an optimiser's flood score. This software does not grant that approval.

## Immediate external work

1. Nominate the bench experiment lead and one drainage operator; confirm which real decision the system should support.
2. Review the draft data contract and physical protocol before measurement, then survey and instrument the bounded network.
3. Collect separate calibration and withheld validation events, including adverse storage/stage and interrupted-work conditions.
4. Review measured-model results and freeze the next evaluation before revealing its outcomes.
5. Record prospective shadow windows, review them with the operator, and only then consider a supervised site pilot.

## Technical sources

The EPA SWMM 5.2 manual describes the model's objects, simulation options and measured-data comparisons: [SWMM 5.2 User's Manual](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P10145M6.TXT). The hydraulic formulation and initial/boundary conditions are detailed in [SWMM Reference Manual, Volume II](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P100S9AS.txt). Neither source validates this project's invented network.

EPA's general modelling guidance recommends monitored boundaries, comparison with observations, separate conditions for validation, and project-specific consideration of error and uncertainty: [Configuration and Calibration](https://www.epa.gov/n-steps-online/mechanistic-modeling-configuration-calibration). Its illustrative water-quality calibration tolerances are not adopted as drainage acceptance standards here.
