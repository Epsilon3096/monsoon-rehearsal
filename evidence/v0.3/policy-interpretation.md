# What the v0.3 policy experiment established

The observation-conditioned research policy did **not** earn a demonstrated benefit. It abstained in all ten designed evaluation rows, as did the equally informed, equally screened marginal, downstream-first and deterministic nominal baselines. All four therefore tied no additional work on spill, completed jobs and crew time. Retain the simpler screened policy as the practical reference; this experiment provides no reason to promote a more complex ranking method.

The ten rows comprise eight rows with valid synthetic observations, including a duration-overrun control, and two missing/stale-observation controls. The latter test refusal when information is unavailable. These are ten designed cases on one reused topology, not independent storms, catchments, measured rig trials or a statistical sample. No operator baseline or field measurement was invented.

## Why the policies abstained

Observations prescribed initial storage and a controlled, fixed receiving stage with illustrative uncertainties of ±0.03 m and ±0.02 m. Conditioning retained all eleven distinct unobserved forcing/roughness/restriction profiles from the earlier planning and development envelope. Each profile was crossed with all four observation-error corners and the nominal/upper-bound duration vectors; a nominal centre was also included. That gives 89 decision-grid rows but only 45 distinct hydraulic configurations per valid observation context.

All four possible first jobs had a numerically resolved protected-location failure in each valid observation context. The unchanged tolerance is 0.05 m³. Every nonempty sequential queue must begin with one of these jobs, so no nonempty queue could pass the required first-prefix screen. No candidate was rejected because the computation cap was exhausted, and no failed case was removed to admit a job.

| Context | First job | First rejecting profile | Node | Spill increase, m³ |
|---|---|---|---|---:|
| LOW | J1 | P1, storage 0.09 m, stage 99.36 m | A1 | 0.204800 |
| LOW | J2 | Revealed H1 forcing, storage 0.09 m, stage 99.36 m | B2 | 2.285776 |
| LOW | J3 | P1, storage 0.09 m, stage 99.36 m | B2 | 28.141131 |
| LOW | J4 | Higher roughness, storage 0.15 m, stage 99.36 m | A1 | 0.088020 |
| HIGH | J1 | Tighter restriction, storage 1.34 m, stage 100.22 m | B1 | 0.069912 |
| HIGH | J2 | P2, storage 1.34 m, stage 100.22 m | J | 46.695790 |
| HIGH | J3 | P1, storage 1.34 m, stage 100.22 m | B2 | 24.851556 |
| HIGH | J4 | P1, storage 1.34 m, stage 100.22 m | A1 | 1.390007 |

The full first-rejection certificates, numerical run identities, observation validation and frozen policies are in [policy-development.json](policy-development.json). These are finite-grid findings under the unchanged synthetic hydraulic assumptions. Small increases remain failures under the frozen tolerance; the experiment did not relax that tolerance.

## The historical queue remains diagnostic

The original J4 → J1 → J3 → J2 queue was replayed without the new screen. It recorded three admissible positive spill comparisons, one tie, five protected-prefix failures and one unresolved duration overrun. A failure remains a loss even where total spill decreases. The largest recorded protected-node increase was 718.637339 m³ at B2 in V3-E03.

In V3-E08, J4 took 96 minutes against its 85-minute bound. Its restoration was left unverified and no final hydraulic score was assigned, although the crew's simulated return was still before the deadline. A duration-bound violation is an exception even when there is no deadline overrun. Any node metrics attached to that unresolved row describe the last verified no-work state, not the unknown physical state following the unverified intervention.

The original queue also runs as a historical diagnostic in the missing/stale-observation controls. Those results must not be interpreted as permission to dispatch without observations. The four screened operational methods issued no work in those controls. Because all operational methods abstained, this hydraulic panel does not demonstrate their performance after a nonempty duration overrun; separate arithmetic contract tests exercise that closure rule.

## Freeze, integrity and computation

- Protocol SHA-256: `932dca0d0dae352ea7b3b863c796670cc1bfd9c18025fc8bfe60d81b5481fba2`.
- Exact implementation/source freeze: `411ce36a77f88cdd4b22335617aa7b941973b3c2a7bc7393330fe94925911e03`, saved at 2026-10-14 09:57:42.567862 UTC.
- First evaluation-start marker: 2026-10-14 09:57:46.833874 UTC, before the first new SWMM outcome. All decision policies were subsequently selected from the frozen development grid before any evaluation event was replayed.
- Recorded completion: 2026-10-14 10:05:51.850070 UTC; measured computation time 485.004915 seconds.
- Development: 184 distinct state/hydraulic pairs, 552 numerical run IDs. Evaluation: 28 distinct state/hydraulic pairs, 84 numerical run IDs. Total: 212 physical state/event pairs and 636 numerical configurations, not 636 independent samples.
- Twenty-one policy contract tests passed before the implementation freeze. Six supplementary tests subsequently checked reporting, immutable evidence, computation limits, development/evaluation separation and invariance to changed future inputs. They changed no frozen implementation, input, threshold or result.

[policy-review.json](policy-review.json) records the later local source/checksum verification and raw-run inventory. This is a local integrity check, not independent peer review. No policy or protocol amendment was made after outcomes were seen. The separately designed evaluation inputs were visible in the protocol; there was no external custodian or independently blinded seal.

## What this changes next

The result supports careful refusal and transparent consequence reporting. It does not establish flood reduction or justify adding ranking complexity. The immediate unresolved issue is the physical and observational basis for the uncertainty envelope: measured condition, initial-state control, stage evolution, restoration response and an operator-reviewed work decision. A measured bench or site study must address those questions before claiming that narrower uncertainty admits useful work. Do not remove troublesome uncertainty merely to produce a positive recommendation.

The hypothetical bench assumes that initial storage is prescribed at event release and downstream stage stays fixed. Those controls, natural stage evolution and conservation during maintenance have not been physically validated. Per-node depth and threshold-duration metrics are available in [policy-results.json](policy-results.json), but the current decision safeguard protects spill only. Abstention can still leave a flooded baseline and does not establish safe depths or crew safety.
