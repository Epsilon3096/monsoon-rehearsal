# Prospective bench validation: protocol and measurement workflow

No rig measurements, operator-reviewed site survey, completed experiment or physical validation have been supplied. The implemented deliverable is a prospective protocol plus a strict measurement importer and quantitative checker. The bundled observations and predictions are invented arithmetic fixtures. Their exact agreement is deliberate and proves no hydraulic behavior.

Start with a supervised instrumented bench network. Use a small township catchment later, once an operator has accepted the data contract, the site boundary and the observation plan. This document does not authorise real drainage work, entry into drains, pump installation in public waterways or an unsupervised field experiment.

## What is frozen now

`data/templates/bench_protocol_v1.json` contains project acceptance thresholds, six mechanism families, twenty-four planned validation event IDs, partition rules and uncertainty rules. Its freeze timestamp is **2026-10-14 09:49:32 UTC**, before any measured results supplied to this project. Its canonical SHA-256 is:

`cc7f5c8eb301f0be18aa54d43a93420d54dbf5237aa8d520acc994063ea83d26`

`monsoon.measurements.load_protocol()` verifies this exact identity. The protocol is pending laboratory and operator review. It is a proposed project standard, not an EPA tolerance or an engineering certification. If instrument capability, the review or the intended decision effect requires a different tolerance, preserve this version and register a new protocol **before collecting new validation events**. Do not relax a threshold after seeing a failure.

| Acceptance quantity | Frozen threshold |
|---|---|
| Maximum adjacent sample interval | 5 seconds; target collection interval 1 second where instruments permit. |
| Event water-balance residual | Greater of 0.0005 m³ (0.5 L) or 3% of initial storage + external inflow + receiving backflow. |
| Stage time-weighted RMSE | 0.010 m at every monitored node. |
| Flow time-weighted RMSE | 0.000020 m³/s (0.020 L/s) at each inflow, signed outflow and spill channel. |
| Total-storage time-weighted RMSE | 0.0005 m³ (0.5 L). |
| Per-location integrated spill error | Greater of 0.0005 m³ or 10% of measured spill at that location. |
| Measurement uncertainty | Expanded absolute instrument uncertainty, coverage factor 2; positive timestamp uncertainty; conservative combined bounds. |
| Mechanism coverage | Four independent validation runs per mechanism: two current/restored pairs, each reset separately. |

An error passes only when its absolute-error **upper** bound is within tolerance. It fails when its absolute-error **lower** bound exceeds tolerance. Overlap is unresolved. A very uncertain sensor therefore cannot create a pass merely by reporting zero observed error. All per-location checks are retained; a bad branch cannot be averaged away by a favorable total.

For RMSE, the checker uses the trapezoidal integral of squared sample errors divided by the actual event duration, followed by the square root. Instrument uncertainty plus a conservative timing contribution from the largest adjacent observed/predicted slope forms its error bound. This is a declared piecewise-linear sampling approximation; it cannot bound unobserved fast oscillations. Refine sampling or declare the result unresolved when the apparatus cannot support that assumption.

## Proposed apparatus and survey freeze

Construct a recirculating, transparent, low-energy laboratory network under the laboratory supervisor's procedures: two branches joining a shared trunk, a separately connected storage tank with its designed outlet fixed, a controlled receiving reservoir, and separately caught overflow at each protected location. Keep source supply and receiving reservoir outside the measured control volume. Include receiving-water backflow in the instrumented boundary.

The reference model guides the topology, not a claim of geometric or dynamic similarity. A practical starting design for laboratory review uses approximately 1–2 m bench reaches with 0.05–0.10 m clear widths, a 5–15 L storage compartment, adjustable receiving level and prescribed branch inflows within about 0–0.3 L/s. These are proposed construction ranges, not a surveyed experiment or a frozen test geometry. The laboratory must select dimensions and instrumentation together, then measure and freeze the as-built package before collection. Do not tune geometry until a preferred policy appears beneficial.

The reproducibility record must include:

1. Surveyed endpoint coordinates, actual lengths, inverts, crest/ground levels, widths, heights and slopes, all in one local metre grid and a permanently marked vertical datum. Measure storage stage–area/volume and every wetted compartment, including links. Identify collectors and overflow destinations explicitly.
2. Four separate removable restrictions corresponding to distinct authorised interventions: shared trunk, Branch A reach, Branch B reach and storage inlet. Record the physical dimensions and uncertainty of current/restored inserts, fixed outlet geometry, fastening method and photographs. No generic percentage-capacity multiplier.
3. Bench-specific model inputs, solver identity, numerical settings, receiving-stage control, measured initial water distribution and a complete control-volume boundary inventory. Generate a new model; do not overwrite the original synthetic reference.
4. Calibration certificates or traceable calibration runs for every stage, flow, total-storage and spill instrument. Retain original readings, uncertainty budget, coverage factor, date, drift checks and valid interval. Zero checks alone do not establish scale accuracy.
5. A witnessed run sheet binding exact geometry/version, initial state, prescribed inflow/receiving-stage traces, restoration subset, event IDs, paired runs, stopping conditions, reset procedure and analysis window. Hash the run sheet and sources with the model-freeze evidence. The supplied template does not establish that this witnessed freeze occurred.

Measure total water retained inside the entire control volume independently of the solver. Suitable laboratory approaches include a calibrated weighed rig or separately calibrated volume measurements accounting for all wetted components; the laboratory must document the uncertainty and any shared sensors. Measuring only the storage tank omits water in channels and fails the inventory requirement. Measure signed exchange at the receiving boundary rather than silently treating negative outflow as zero. Spill collectors must stay outside the retained-volume measurement and be separated by location so they are not counted twice.

EPA's hydraulic reference distinguishes external inflow and receiving-head boundaries, requires initial heads/flows, and describes dynamic-wave treatment of storage, backwater and reverse flow. Those mechanisms motivate these measurements; EPA does not supply this project's acceptance thresholds or validate its rig. [EPA SWMM Reference Manual Volume II, sections 2.3 and 3.1](https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=P100S9AS.txt). The project's pinned SWMM version remains separate from the newest available distribution. [EPA SWMM documentation catalogue](https://www.epa.gov/water-research/storm-water-management-model-swmm).

## Mechanisms and experimental sequence

Use prescribed measured inflows first. Rainfall-runoff calibration is a separate experiment, with separate parameters and evidence. Bench tests target the physical uncertainty exposed by the original failed recommendation; they do not erase H2 or convert revealed development cases into holdouts.

| Mechanism / IDs | Controlled comparison and required observation |
|---|---|
| `H2_risk_transfer`, `BENCH-VAL-H2-01`–`04` | Reproduce the declared stored-water/receiving-stage challenge. Freeze the candidate restoration subset from the existing H2 audit and its physical mechanism before collection. Compare current/restored states with separate Branch A, Branch B and trunk spill. Preserve any transfer of harm or absence of the hypothesised effect. Test material intermediate subsets during development; a full policy needs its own later prefix evaluation. |
| `roughness`, `BENCH-VAL-ROUGH-01`–`04` | Use a measured, repeatable surface/lining condition and fixed geometry. Calibrate plausible roughness only on development/calibration runs; hold the value fixed for these runs. Observe branch stages, outflow and spill. |
| `restriction`, `BENCH-VAL-RESTRICT-01`–`04` | Use measured removable insert geometry. Compare fixed current/restored sections; photograph and remeasure each reset. Preserve storage outlet settings. |
| `receiving_high`, `BENCH-VAL-STAGE-01`–`04` | Prescribe a high receiving-stage trace, record the actual trace and signed boundary flow, and retain backflow in the balance. Begin from the recorded initial state. |
| `cold_start`, `BENCH-VAL-COLD-01`–`04` | Deliberately record a non-equilibrated initial distribution under the lab plan. Compare the whole transient; do not trim the initial spill to obtain a favorable result. |
| `equilibrated_control`, `BENCH-VAL-EQUIL-01`–`04` | Establish the lab-defined stable initial heads/flows under the same receiving boundary, record equilibration and compare the response. Distinguish its initial state from the cold start. |

For each family, odd IDs (`01`, `03`) are current state and even IDs (`02`, `04`) are restored state. Pairs are exactly `01/02` and `03/04`; each pair shares the frozen prescribed forcing identity. Actual inflow and stage are measured each run, so imperfect forcing reproduction remains visible. Reset the network independently before every event, document the reset and retain both repeats. Run order within the laboratory schedule should be assigned before outcomes are observed; timestamps must be nonoverlapping. Repeated deterministic calculations are not these independent physical resets.

Before validation, collect distinct `BENCH-CAL-*` events covering the apparatus's operating range, inspect residuals and fit only the parameters supported by those data. Record every calibration event ID in the model lineage. Freeze the complete model and its source evidence after calibration ends and before any validation event starts. Freeze validation labels, forcing, state and analysis windows before collection. The importer requires model-freeze and protocol hashes, separate event IDs and raw-file hashes, nonoverlapping windows, and the correct pair assignments. It cannot independently prove that a supplied timestamp or modelling history is truthful; a custodian must inspect the retained records.

Use the frozen model with the **observed input boundary series** to predict withheld responses. Do not fit parameters, choose a new initial state, change the window, delete samples, swap mechanism labels or choose a restoration after reading validation outcomes. An input inflow replay or imposed outfall-stage replay is labelled `boundary_replay_not_independent_response`; its agreement is not response validation. Local stages, total retained volume, receiving exchange and spill remain independent response checks to the extent their instruments and model lineage support that claim.

For each run: verify calibration/zero and collector readiness; record the installed state and measured initial storage; start synchronized acquisition; execute the predeclared forcing; observe the complete declared window and recession; account for final retained water and all collector volumes; preserve unedited data, photos, notes and failure records. If an instrument drops out, changes range, saturates, loses datum or exceeds its calibration interval, preserve the failed record and diagnose it. A later repeat is a new event; do not silently replace an unfavorable run.

Current code requires every sample to include every declared sensor, including predicted values. Null is a missing observation and blocks all event arithmetic, rather than allowing an attractive partial score. A gap above 5 seconds, duplicate timestamp, unknown sensor, wrong unit/datum, uncovered boundary, unresolved sample order from clock uncertainty, or missing window endpoint also blocks arithmetic. Do not invent observations to fill the upload. If valid collection needs another sampling interval or a different measurement representation, revise the protocol before new validation.

## Measurement file and mass balance

`monsoon.measurements/1` files bind `dataset_id`, site ID and canonical site hash, evidence kind, vertical datum, protocol ID/hash, offset-aware receipt time, frozen model identity/lineage, control-volume evidence, sensors, events and notes. Read `data/templates/synthetic_measurements_v1.json` for the exact field structure. It is an arithmetic example, not a real dataset or a run sheet for all twenty-four experiments.

Sensors use stable IDs and quantities `inflow_m3_s`, `outflow_m3_s`, `spill_m3_s`, `stage_m` and `storage_m3`. Units are exact. Stages use the site datum. The entire control volume has one total-storage sensor at `SYSTEM`; other sensors reference surveyed nodes. Inflow, receiving outflow and spill sensors cover the declared boundary inventories exactly, with no duplicate counting sensor. Stage is required at every node including the receiving outfall. Each calibration entry includes record ID, evidence hash, validity interval, positive expanded absolute uncertainty and coverage factor 2.

For complete adjacent observations at times `t[i]`, the checker integrates flow by trapezoids using each actual `t[i+1]-t[i]`, with no resampling or extrapolation. Receiving flow is positive outward and negative inward. A sign-crossing interval is split at its linearly interpolated zero when reporting gross outflow/backflow; the signed mass balance uses the signed integral.

`residual = initial retained volume + external inflow − final retained volume − signed receiving outflow − collector spill`

Initial storage, final storage, external inflow, gross outward discharge, receiving backflow, signed discharge, spill, duration and residual are reported separately. The uncertainty bound sums each boundary-flow volume bound, both retained-volume endpoint bounds, timing contributions and the documented unmeasured-loss upper bound. This conservative linear sum assumes no independence between instruments. The model does not infer evaporation, leakage or hidden drains; a declared zero loss bound requires supporting evidence. The receiving reservoir is external, so backflow is a control-volume input rather than unexplained storage creation.

`analyze_measurements(payload, site_package)` returns structured issues or per-event balances and prediction comparisons. An invalid package performs no partial integration. Valid calibration events have diagnostics but never count toward the withheld-event acceptance summary. The overall arithmetic result is `pass`, `fail`, `unresolved` or `no_validation_events`; a failure at any required validation event/location is retained.

`protocol_coverage` reports all missing planned validation IDs. `ready_for_physical_review` means a structurally complete measured claim is available for a reviewer, including failures. It does not mean all thresholds pass. **`physical_validation_established` and `operational_activation_allowed` remain false in every report**, even when all imported arithmetic passes. A supplied label and a complete file cannot prove calibration authenticity, independent execution, model lineage or physical similarity.

## Evidence needed to leave the current state

The next physical milestone needs the accepted bench contract, witnessed survey/run-sheet freeze, instrument records and raw observations, unedited calibration lineage, a frozen bench model, all planned withheld events, rejected/failed runs, and a review explaining uncertainty and per-location results. A successful physical review supports only the tested apparatus, configurations and forcing envelope. It does not establish a universal maintenance policy, rainfall forecast accuracy or township flood reduction.

Then select one small operator-approved township drainage area. Obtain matched survey, condition, initial storage, receiving stage, inflow/rainfall and response observations; preserve a new site/model identity. Review overflow destinations and surface transfers before making flood-exposure claims. Collect calibration and withheld events separately. Begin with observation/shadow decisions; the responsible engineer defines any later live-pilot work envelope. No live pilot is authorised by this bench protocol or by a lower modelled spill score.

The original H2, cold-start, roughness and restriction failures remain available alongside new measurements. If the new data contradict the mechanism, the result is a finding to retain, not a reason to alter acceptance thresholds or hide the run. Arithmetic fixtures and unit tests remain software evidence only.
