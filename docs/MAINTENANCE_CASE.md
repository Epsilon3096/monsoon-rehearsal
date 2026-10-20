# A separate outlet-restoration mechanism benchmark

Declared before the first native simulation on 20 October 2026. This is a synthetic engineering benchmark, not a surveyed site, operator-nominated intervention or validated work recommendation.

## Physical question

Can restoring an obstructed final conveyance reach reduce upstream overflow when the receiving boundary has adequate capacity? Unlike the original interacting two-branch maintenance study, this intervention removes the final represented restriction. It does not send additional water into another constrained modelled reach. The receiving water remains a prescribed boundary: its ecological, downstream flood and discharge-capacity consequences are outside this model and would need review at a real site.

Two short feeder channels enter a 50 m² storage node, which discharges through one 50 m final channel. Restoring its width from 0.10 m to the assumed original 1.00 m preserves its invert, depth, slope and roughness. No new excavation or enlargement beyond the assumed original width is represented. All geometry and obstruction dimensions are invented benchmark inputs, not measurements.

At a 1 m water depth, slope 0.02 and Manning n=0.02, the uniform-flow capacity estimate is about 0.093 m³/s for the obstructed rectangular reach and 3.40 m³/s for the restored reach. This explains the hypothesis before running the dynamic model. It is a screening calculation, not a calibration or proof of unsteady behaviour. Prescribed peaks deliberately exercise a restriction below its original capacity; they are not rainfall forecasts.

## Fixed evaluation

`data/benchmarks/outlet_restoration_v1.json` fixes the topology, dimensions and all scenarios before simulation. Four cases cross distinct hydrographs, antecedent storage, roughness and residual restriction. A zero-inflow control must show no artificial benefit. A high receiving-water control tests the limit of the free-outlet reasoning and stays visible even when it fails. A short work-window control uses the real scheduler to refuse a job that cannot finish and return in time.

For every case, compare the unaltered and fully restored configuration at 0.5 s and 0.25 s routing steps and at 180 and 360 minutes. Keep the existing worker checks: 1% routing and independent volume balance, zero nonconverged nodes, and reconciliation of node overflow with the engine total. For every node and the network total, use the original max(0.05 m³, 2%) step agreement and 0.05 m³ event-horizon agreement. No represented location may increase by more than 0.05 m³ at any of the three configurations. The four declared mechanism cases must each reduce total spill by more than 1 m³ to support the positive-mechanism statement. Retain an unsuccessful result without tuning dimensions or thresholds.

One job is available, so a competent downstream-first baseline selects the same action. A tie is expected. This benchmark cannot establish scheduling superiority. Its only achieved work states are no completed work and the completed restoration. It does not represent physical excavation during a storm. With ten minutes travel each way and a 45-minute upper duration bound, the scheduler needs at least 65 minutes before it may start.

The benchmark has no route to live plan approval or tickets. Passing cases do not change the original reference model's full-envelope failure, establish field safety, or satisfy the missing operator review.

## Reproduction and provenance

Run `python -m monsoon.maintenance_benchmark --output var/benchmark-new-attempt` from the repository. The output must be new. The runner writes its protocol/source/engine freeze before the first calculation, then retains every input, native output, report, log and result with a SHA-256 manifest. All attempts, including failures, should remain available. File hashes establish identity, not independent third-party chronology or physical truth.

Engine capability source: [EPA SWMM documentation](https://www.epa.gov/water-research/storm-water-management-model-swmm), consulted 20 October 2026. EPA documents dynamic-wave routing, open channels, external inflows and backwater. EPA does not endorse this project or supply this benchmark geometry.

## Recorded first attempt — 20 October 2026

The protocol and runner were committed before this attempt. No geometry, scenario or threshold was changed after seeing its output. Raw artifacts are under `evidence/v0.9/maintenance-benchmark/`.

| Case | Restricted spill (m³) | Restored spill (m³) | Comparison outcome |
| --- | ---: | ---: | --- |
| T1 · short pulse | 481.2343 | 0.0000 | Pass |
| T2 · two peaks / antecedent storage | 872.9503 | 0.0000 | Pass |
| T3 · prolonged inflow / residual restriction | 1971.4458 | 0.0000 | Pass |
| T4 · lower inflow | 70.9001 | 0.0000 | Pass |
| C_ZERO · no inflow | 0.0000 | 0.0000 | Null control passes |
| C_BACKWATER · high receiving water | Not qualified | Not qualified | Unresolved event horizon |

All 36 native runs passed the unchanged worker checks. Maximum absolute routing continuity and independent water-balance residual were each approximately **0.03705%**, below the 1% limits. Passing water accounting does not establish event completeness: C_BACKWATER still exceeds the separate 0.05 m³ horizon tolerance at storage and total spill, in both restricted and restored configurations. Its complete raw values remain available as diagnostics.

The 120-minute work window admits M1; the 50-minute window skips it using the 45-minute job bound plus travel and return. Downstream-first ties the candidate because both have the same single action. No field benefit, downstream receiving-water safety or scheduler advantage follows from this result.
