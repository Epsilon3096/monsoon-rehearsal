# Observation-conditioned policy experiment v0.3

A prespecified synthetic research comparison on the reused reference topology. It is not measured bench validation, an independent catchment test, or evidence of field/operator superiority.

Protocol SHA-256: `932dca0d0dae352ea7b3b863c796670cc1bfd9c18025fc8bfe60d81b5481fba2`. Implementation freeze: `411ce36a77f88cdd4b22335617aa7b941973b3c2a7bc7393330fe94925911e03`.

| Method | Positive | Tie | Loss | Abstention | Unresolved | Duration overruns |
|---|---:|---:|---:|---:|---:|---:|
| Observation-conditioned finite-grid queue | 0 | 0 | 0 | 10 | 0 | 0 |
| Screened adaptive marginal benefit per crew minute | 0 | 0 | 0 | 10 | 0 | 0 |
| Screened downstream-first heuristic | 0 | 0 | 0 | 10 | 0 | 0 |
| Screened deterministic nominal objective | 0 | 0 | 0 | 10 | 0 | 0 |
| No additional discretionary work | 0 | 10 | 0 | 0 | 0 | 0 |
| Original v0.1 queue (historical unscreened diagnostic) | 3 | 1 | 5 | 0 | 1 | 1 |

Unresolved takes precedence; any protected-prefix harm is a loss even when total spill falls. Otherwise >0.05 m3 reduction is positive, +/-0.05 m3 is tie. Zero-dispatch operational rows are exclusive abstentions; their supported spill ties also appear in the separate paired table. No-work itself is a tie reference.

## Paired comparison with competent baselines

| Baseline | Robust positive | Tie | Robust loss | Unresolved |
|---|---:|---:|---:|---:|
| Screened adaptive marginal benefit per crew minute | 0 | 10 | 0 | 0 |
| Screened downstream-first heuristic | 0 | 10 | 0 | 0 |
| Screened deterministic nominal objective | 0 | 10 | 0 | 0 |
| No additional discretionary work | 0 | 10 | 0 | 0 |

## Scope and limitations

- All results reuse one synthetic topology. Ten designed event rows include observation and duration controls; they are not ten independent catchments, random storms, measured events or statistical replicates.
- Prior reference outcomes and stress failures informed the research question. Inputs and source were locally frozen before outcomes, but no independent custodian or externally blinded seal is claimed.
- The prescribed storage and fixed receiving stage are hypothetical controlled bench inputs. Natural time-varying receiving levels, conservation through work and physical bench response remain unvalidated.
- Observation uncertainty, roughness and restriction ranges are illustrative. All retained development profiles are kept under conditioning, but the finite grid is neither exhaustive nor a probability distribution.
- Every prefix and numerical gate is unchanged. Any protective failure is a loss regardless of improved total spill; errors and overruns remain unresolved.
- Depth-threshold durations are descriptive outputs; the present decision gate protects spill only. Lower total spill does not establish safe depths, damage reduction or crew safety.
- The original queue is a historical diagnostic. There is no invented operator baseline or real operator validation.
- Conditioning on stage/storage is not permission to inspect future forcing or realised durations. Choosers receive only the frozen table, verified completed set, eligible jobs and elapsed time.
- Raw SWMM outputs are retained locally under var and excluded from source bundles. Hashes establish local integrity, not independent attestation.
- If the revised method ties simpler baselines or abstains, report that result and favour the simpler supported policy; no algorithmic superiority is presumed.

The JSON report contains every event, method, completed subset, duration exception, per-node spill/depth/threshold duration, and every checked achieved prefix. Development rejection certificates and policies are in policy-development.json. Full raw numerical outputs are retained under var/policy-v3-swmm and are excluded from release archives.
