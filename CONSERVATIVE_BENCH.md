# Conservative bench verification

This workspace tests a separate finite-volume bench engine. It does **not** repair EPA SWMM, erase the historical failures, validate a real drainage site, or change the operational scheduling policy.

**Development status, 17 October 2026:** the completed complex pulse and receiving-stage reversal runs pass all water-accounting checks, but the pulse retains one unchanged mesh-accuracy failure. A later isolated correction passes all twelve hydraulic benchmarks, 71 method checks and 48 workflow checks, but its forty-second original pulse prefix fails the unchanged mesh comparison. It is not installed or release-qualified. The independent challenges and final release checks remain pending. See `evidence/v0.7/VERIFICATION.md` for the exact source identities, retained outcomes and accuracy limitations. The method described below remains the installed baseline until a qualified correction is promoted.

## Why a separate engine

The earlier complex bench examples can pass a final balance while failing the stronger balance check during the event. The retained investigation identifies a mismatch between the reported terminal-conduit flow and the control volume used for stored water at a prescribed receiving head. A local wet rectangular diagnostic supports that explanation. A general post-processing correction was not justified; an explicit terminal-junction/outlet alternative also failed its predeclared checks. Both investigations and all adverse outcomes are preserved.

The new method records each actual transfer through a channel face once. Adjacent channels and compartments use equal and opposite transfers. Receiving-water inflow and discharge are recorded at the domain boundary, independently of the resulting stored-water change. No residual is fitted away and no water is deleted to achieve balance.

The channel method uses MUSCL reconstruction with the standard monotonized-central limiter, conservative depth/momentum face states and a single contraction into their local joint Riemann-invariant region. Hydrostatic reconstruction supplies balanced bed-pressure terms, and HLL fluxes use shock/rarefaction wave-speed bounds. Smooth-flow updates use SSPRK2 with exact fixed-depth Manning damping in two split half-steps. A compartment uses a capacity-bounded predictor, followed by one physical spill transfer from its final integrated volume balance. The local reconstruction condition is not a general global invariant-domain or entropy proof; second-order accuracy is not claimed through spill events. The retained independent tests determine qualification within the declared scope.

## Supported model

- Rectangular, prismatic open channels with surveyed lengths, widths, wall heights and bed elevations.
- Exactly zero end offsets and minor-loss coefficients. Circular/trapezoidal sections are rejected before execution.
- Internal compartments have explicit positive stage–area curves. Their volume is the piecewise-linear area integral; stage is its inverse.
- Receiving levels are prescribed reservoir boundaries. Each outfall has exactly one incoming terminal channel and no outgoing channel; a reservoir shared by several channels is rejected by the validated adapter. Compartment and reservoir connections represent mixed storage rather than resolved junction momentum.
- Fixed geometry and a continuous, exactly dry, zero-flow initial state. An earlier forcing period can prepare a wet state; a phase boundary carries the entire state forward without a restart.
- Spill from a full compartment leaves through its explicitly declared absorbing collector. Channel overtopping, pressure flow, surface re-entry, leakage and seepage are outside scope.
- At most twelve nodes, eight channels, 300,000 accepted steps per attempt and 600 seconds per worker. Exceeding a bound is an unresolved attempt, not a truncated success. Private process containment terminates worker descendants on timeout; a Windows virtual-environment launcher cannot leave its real interpreter running after cancellation.

The existing site/model/run contract is reused and bound by hashes. Legacy SWMM iteration parameters remain in the retained source model for provenance, but the new solver uses its own explicit fixed settings. It does not silently adopt SWMM's artificial minimum surface area or initial water film.

## Fixed qualification

Every requested case runs exactly this triple:

| Attempt | Cells per channel | CFL limit | Maximum time step |
|---|---:|---:|---:|
| Primary | 128 | 0.4 | Supplied model step |
| Time refinement | 128 | 0.2 | Half the supplied step |
| Spatial refinement | 256 | 0.4 | Supplied model step |

Both the CFL limit and time-step cap are halved for the time comparison. Changing only the cap could leave a CFL-limited run unchanged. There is no automatic refinement until a pass.

The time-step controller applies the existing 0.9 stability margin to its initial CFL-based trial. It still checks the actual maximum wave speed in both integration stages and rejects any trial exceeding the declared CFL limit. This avoids repeatedly evaluating trial steps that must be rejected; it does not raise the limit or bypass the 600-second budget. This controller revision changes some accepted time steps and is not described as a bitwise-equivalent optimization. The earlier full pulse primary passed, but its finer-time-step attempt reached the unchanged runtime limit; that unsuccessful qualification remains retained.

At **every actual routing endpoint**, the complete water balance must satisfy:

`abs(initial storage + external inflow + receiving backflow − discharge − spill − current storage) ≤ max(0.000001 m³, 0.01 × (initial storage + external inflow + receiving backflow))`.

The same rule applies continuously within each declared phase, using that phase's actual initial water. The original limit is **1 mL or 1% of initial plus gross incoming water**. Final cancellation cannot excuse an earlier failure. Gross receiving exchanges split the separately applied time-integration stage transfers by sign before summation; net flow is not substituted for gross turnover.

A separate adapter audit reconstructs these budgets from the compressed routing history. It also checks individual channel/compartment water changes, shared transfers, the exact prescribed inflow integral, report-time storage, final cell volumes, phase totals and diagnostic summaries. It checks full inventories and exact times; missing samples are not interpolated away.

The primary/time and primary/mesh comparisons independently retain the earlier **2% relative** limits, with absolute floors of **0.1 mm stage**, **0.0000001 m³/s flow** and **1 mL volume**. All report samples, peak stages and location-specific gross totals participate. All three runs and both comparisons must pass for numerical qualification.

Conservation is necessary, but it is not an accuracy test. Separate, predeclared analytical tests cover an emergent-bed lake at rest, a dry-bed dam-break wave, storage integration/inversion, friction decay and a moving Manning equilibrium. Independent frozen challenge cases test reversals, wet final states, nonzero final inflow, elevation translation, multiple outfalls and variable compartment area. Unsupported geometries count as scope rejections, not successful hydraulic predictions.

Development review found that the original five analytical controls alone could miss unrealistic velocities in an extremely shallow wave tail. A **separate additional** exact-solution check therefore examines every cell at every accepted endpoint: velocity, the joint depth/velocity invariant region, flow direction and water ahead of the theoretical wave front. It omits no positive depth and leaves the original five criteria unchanged. Its provenance explicitly identifies the candidate outputs already observed before this supplementary gate was defined; it is not presented as a blind test of those candidates.

The failed original pulse comparison also prompted four additional exact hydraulic-jump controls: a stationary jump aligned with a cell boundary, the same type of jump inside a cell, and jumps moving slowly in either direction. Their fixed criteria check full-domain depth/discharge errors, refinement, position, outgoing disturbances, every-endpoint physical bounds and water accounting. They were declared before the revised candidates were run, but after the original pulse failure was observed; they are development tests, not independent holdouts. All twelve analytical controls must pass. A smaller coarse/fine discrepancy alone is not proof that both approximations became more accurate.

## Evidence and workflow

Use **Validation → Conservative bench**. Supplied forms start blank; synthetic examples are labelled separately. Provide site, model and run JSON, and optional phase boundaries on the reporting grid. Check the contract, then run the fixed verification triple.

Each attempt retains its exact request, source/runtime identity, worker output and log, full compressed routing trace and independent audit. The complete folder has a manifest. Verification recomputes acceptance from those retained records and checks them against the currently loaded source and runtime. The evidence folder can be copied as a whole; its new location is supplied as `artifact_directory` without rewriting the immutable contents.

Changing inputs invalidates the displayed acceptance. Changed, missing or extra evidence files block reuse/export. A failed run is retained with its failure. No result creates maintenance tickets or activates an imported site.

The point flow displayed at a channel's midpoint is for reporting. Water accounting uses the actual applied interval volumes. Reported spill is the preceding report-interval mean; it is not an endpoint instantaneous measurement.

## Limits of the submission claim

The deliverable is a working planning and evidence prototype with a separate numerical bench method undergoing qualification. It is not yet a physically validated drainage decision system. Real apparatus measurements, operator review and a useful policy advantage on a new frozen evaluation are the main remaining evidence needs. An observed shadow trial is a later operational step; it is not asserted to be a prerequisite for entering the hackathon. The existing reference baseline tie, protected-location failure and later policy abstentions remain unchanged.

Primary method background: [Audusse et al., hydrostatic reconstruction](https://epubs.siam.org/doi/10.1137/S1064827503431090) and [Clawpack's shallow-water Riemann solver documentation](https://www.clawpack.org/riemann_book/html/Shallow_water_approximate.html). These references describe numerical methods; they do not certify this implementation. Exact implementation, development failures and verification outcomes are retained in the v0.7 evidence.
