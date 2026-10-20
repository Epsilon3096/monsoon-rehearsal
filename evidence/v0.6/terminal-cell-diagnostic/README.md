# Terminal-cell diagnostic: support for an accounting mechanism

This single, predeclared synthetic diagnostic supports a specific explanation for the large transient water-balance discrepancy. **Every case still fails the unchanged numerical conservation criteria.** It implements no repair, changes no release qualification, and establishes no physical validity.

The source investigation preceded the experiment. Its unchanged note is retained as [source-investigation-before-experiment.txt](source-investigation-before-experiment.txt); statements there about no rerun describe that earlier, read-only phase. The subsequently authorized three-case experiment is recorded here.

## Predeclared controls and execution

[protocol.json](protocol.json) was written before any of these native executions. Its SHA-256 is `c302c79e18b5129b2e6f0a9c04f39264a43a385f96042404e4bbbc71f1c1d979`. All three input files, numerical settings, predicted residuals, support criteria, runtime hashes and diagnostic worker source hashes were fixed at that point. Each case ran once, with no retries, tuned parameters or additional cases. [execution-start.json](execution-start.json) and the individual attempt records preserve that local order; this is not independently witnessed preregistration.

The original terminal channel is 0.8 m long, 0.08 m wide, and 0.25 m deep, descending from invert 0.02 m to 0 m. Cases represent this same reach with one, two or four equal conduit elements. Total length, bed profile, cross-section, roughness, zero losses, upstream A/S geometry, L1, stage forcing, 120-second horizon, 0.01-second routing step, all other options and initial conditions remain fixed. The one-element input is byte-identical to the retained adverse probe.

The two- and four-element cases add one and three ordinary junctions at interpolated invert elevations. They have no declared physical storage or ponding. These are deliberate changes to **numerical discretization and the number of nodal continuity equations**, not claims of an identical discrete model. The unchanged minimum numerical surface-area setting still applies. All inserted nodes retained exactly zero live node volume throughout; their link-contributed area was below the minimum only at the initial sample. Their subsequent effective area therefore came from adjoining conduit portions. This rules out an added physical reservoir in these executions, but does not imply subdivision leaves the numerical dynamics unchanged.

## Result

Each case completed all 12,001 endpoints with no native warning or reported nonconverged internal-node step. [summary.json](summary.json) retains full results, including original numerical failures.

| Terminal elements | Predicted residual at 50 s | Observed residual at 50 s | Difference from prediction | Endpoints failing unchanged conservation |
| --- | ---: | ---: | ---: | ---: |
| 1 | -1.920 L | -1.914449922 L | 0.2891% | 8,723 |
| 2 | -0.960 L | -0.955166534 L | 0.5035% | 8,412 |
| 4 | -0.480 L | -0.475447335 L | 0.9485% | 7,791 |

The one-element result reproduces the retained probe's 50-second residual to approximately 2e-17 m³. Native and independently integrated residuals agree within 1.24e-16 m³ across these runs. At 50 seconds the getter reports downstream terminal surface areas of 0.032, 0.016 and 0.008 m², exactly the predicted half-element areas.

All cases meet the predeclared mechanism-support rule: completion without warning/nonconvergence, baseline reproduction within 1e-9 m³, negative residuals and agreement with the inverse-element-length predictions within 5%. **That 5% band only discriminates the proposed mechanism.** Numerical qualification still uses `max(1 mL, 1% of initial plus gross entering water)` at every endpoint, without alteration; all three cases remain unresolved under it. The worst residual-to-tolerance ratios are approximately 883.25, 280.75 and 100.16.

## Explanation supported, with limits

The [EPA 5.2.4 conduit calculation](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/dwflow.c#L258-L267) stores volume from both end areas while carrying one link-flow value. Its [surface-area calculation](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/dwflow.c#L425-L435) assigns half the wetted rectangular link area to each end. [Interior-node continuity](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/dynwave.c#L550-L647) uses those areas but skips the imposed outfall depth. [Outfall exchange](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/node.c#L409-L440) uses the accumulated link flow, whereas [system storage](https://github.com/USEPA/Stormwater-Management-Model/blob/v5.2.4/src/solver/massbal.c#L592-L617) retains the whole terminal conduit.

For a wet constant-width terminal element, this suggests a boundary-associated storage contribution `W = B × L_terminal × y_outfall / 2` whose imposed change is not represented by the reported terminal link-flow continuity. Consequently the reported cumulative residual should contain approximately `-ΔW`. The observed near-halving with terminal element length strongly supports this discrete control-volume/flux-accounting explanation. It does not identify every smaller residual or validate an adjusted boundary flux.

The diagnostic quantity `R + ΔW` is retained only to inspect that mechanism. At 50 seconds it is approximately +5.550, +4.833 and +4.553 mL; it is **not** a corrected acceptance result. Dry-end clamps, critical-depth substitutions, iteration tolerance, spatial approximation and changing hydraulic regimes remain possible contributors. Per-step flow-class labels are not exposed by the toolkit getter; the trace instead retains live end areas, depths and Froude numbers, and the native report retains aggregate flow-class statistics.

The inspected source is the public **EPA v5.2.4 tag**. The installed engine is the hash-pinned **OWA swmm-toolkit 0.17.0 binary identifying as SWMM 5.2.4**. This exercise does not prove that the public tag exactly matches every instruction in that binary. Its experimentally observed scaling supports the proposed mechanism despite that provenance limitation; it is not evidence of physical hydraulic accuracy or a general solver defect.

## Retention and unchanged release

Each case retains its exact input, request metadata, start record, native report/output, compressed trace of every actual routing endpoint, result and worker log. The execution summary confirms unchanged release-freeze files, runtime bytes and original adverse input. No production source, test, input fixture, original evidence, acceptance tolerance or focused release review was edited.

[execution-manifest.json](execution-manifest.json) preserves the original execution inventory. [manifest.json](manifest.json) additionally binds this interpretation and the prior source note. Literal paths retain the original workspace; this is an evidence archive, not a portable restored study or independent authenticity attestation. It must not be used to overwrite or requalify the original adverse results. A future stage still needs a reviewed numerical treatment, spatial and temporal checks, appropriate boundary-flow semantics, and independent physical observations.
