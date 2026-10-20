# v0.7 verification status — custom-solver qualification stopped

Following the user's 17 October strategy reassessment, no further custom-solver experiments are planned for this delivery. The project will concentrate on its existing EPA SWMM planner and useful decision evidence. This scope decision does not change any test, excuse a failure, accept v0.7, or validate the earlier complex SWMM bench models. The results below remain retained research evidence. Independent challenges remain unexposed; no replacement release profile has yet been verified.

Status at 17 October 2026: **water-accounting checks and all twelve hydraulic benchmarks pass, but the latest isolated correction fails the fixed mesh comparison in the forty-second original pulse prefix. It is not accepted.** No v0.7 release or physical validation is claimed.

The separate conservative bench engine records actual shared face transfers and receiving-boundary exchanges. It does not apply a residual correction to EPA SWMM or change the original scheduling model and policy findings. Its supported scope and unchanged qualification rules are in `CONSERVATIVE_BENCH.md` at the project root.

## Latest complete original trial

Candidate core SHA-256: `ae817c13e99ede0aa03dbb00ef3c0d92f3f7e2b718b5a1c9c3a3a36db16ce461`.

| Original case | Every-endpoint water accounting | Time comparison | Mesh comparison | Qualification |
|---|---|---|---|---|
| Seven-litre pulse | Pass, all three runs | Pass | **Fail** | Unresolved |
| Receiving-stage reversal | Pass, all three runs | Pass | Pass | Pass within declared scope |

An independent replay of the retained transfer histories checks all **285,881 endpoints**, local inventories, equal-and-opposite shared transfers, exact supplied inflow, gross receiving exchanges, phase budgets, final arrays, settings and input/source identities. The largest cumulative water residual is **7.789992609308349 × 10⁻¹⁷ m³**. The water limit remains **1 mL or 1% of initial plus gross incoming water**, whichever is larger; cancellation at the final endpoint cannot excuse a failure earlier in the run.

The pulse fails the `L1` channel's reported midpoint-flow mesh comparison: **4.539523439609655 × 10⁻⁶ m³/s** maximum difference against the unchanged **4.0103291098856415 × 10⁻⁶ m³/s** limit. Here `L1` is the channel identifier. The time comparison passes at **94.0% of its limit**; its narrow margin remains visible. No report samples were filtered, moved or omitted.

The complete retained attempt and independent review are under the workspace's `work/v07-original/attempts/20261016T110957416739Z-parallel-originals-72604e8d`. Earlier numerical, timeout and interrupted attempts are retained separately. The current production source remains unchanged while an isolated reconstruction correction is investigated.

## Latest isolated correction

Experimental energy-metric secant candidate `7ebe5f5707492775a2319e5cb5586cf9c6c9f7382d4201372b3622b3308514e0` passes **12 of 12 unchanged hydraulic benchmarks**, 71 method controls and all 48 unchanged workflow controls. Attempt: `work/v07-analytic/jump-combined-attempts/20261016T155740Z-isolated-energy-secant-7a5b5857`. Slow-right depth/discharge/frame-discharge refinement ratios are approximately 0.4723/0.6721/0.6721; slow-left ratios are 0.6031/0.6131/0.6133, all below 0.8. Fine frame-discharge errors are approximately 0.002564 m and 0.003360 m against the unchanged 0.00390625 m bound. Every endpoint water check passes; maximum jump residual is approximately 2.92e-17 m3.

These absolute moving-jump errors are larger than the preceding candidate's errors; this is a pass of all fixed criteria, not uniform accuracy improvement. The new ten method tests include one transparently retained, observed-output arithmetic-assertion amendment: separate stored momentum magnitudes replace their cancelled difference in a roundoff scale. The coefficient, runtime guards and all original physical criteria are unchanged. The initial nine-pass/one-failure result is retained. An independent review verifies all 71 exact cases, the separate ten/61 result files, source/runtime identities and the amendment history.

The correction remains isolated. Its forty-second original pulse prefix completes all three runs and passes the time comparison, but **fails the mesh comparison**: L1 midpoint flow differs by 9.848663135127801e-6 m3/s at 25 seconds against 4.007250855048463e-6 allowed. The independent audit verifies all 32 comparison metrics and all 57,705 water-accounting endpoints; maximum cumulative water residual is 6.201636426617085e-17 m3. Run times are 209.03, 414.15 and 402.26 seconds, within the unchanged 600-second worker bound. Attempt: `work/v07-core/prefix-attempts/20261016T160211302076Z`; audit: `work/v07-review/prefix-review-7ebe-01/review.json`.

The full original pulse/reversal, untouched challenge cases and final release checks remain pending. A benchmark pass does not override this complex-case failure. Saved-state analysis is investigating the jump position and the corrected-to-HLL stencil transition; reports and acceptance criteria remain unchanged.

### Preceding candidate, retained adverse result

The strict convex-admission candidate `d4f9fc164c5230268363e6c29aa2bd4ad161fd0ea464e7f6a9c0a82b19a5d706` passes 61 prospective method checks and the 48 unchanged workflow checks. It passes **11 of 12 hydraulic benchmarks**. The remaining slow-right moving-jump error decreases from 0.0011254726765561917 m on the coarse grid to 0.0009488418235509022 m on the fine grid, a ratio of approximately 0.8431 against the unchanged maximum of 0.8. Absolute accuracy and endpoint water checks pass, but this candidate is not qualified or installed.

The retained attempt is `work/v07-analytic/jump-combined-attempts/20261016T151217Z-isolated-convex-admission-strict-363968bb`. The original twelve hydraulic test bodies and numerical criteria are unchanged. A separately documented amendment to a synthetic coupling fixture changes only its eligibility markers; all numerical assertions remain intact, the original entropy failure is retained, and an added negative control requires its rejection. This distinction is explicit in the 61-check evidence.

The next investigation concerns the consistency of corrected fluxes and their wave decomposition. The original full pulse/reversal trial has not been rerun with this isolated candidate. No holdout or release acceptance follows from its method and workflow passes.

## Work remaining before release acceptance

1. Pass the unchanged analytical controls and prospectively registered additional hydraulic-jump controls with a justified correction.
2. Pass a fresh complete original trial and its independent audit without changing numerical budgets, reporting or limits.
3. Freeze the candidate, then execute and report every independent challenge, including explicit unsupported-input rejections.
4. Complete full regression, original planning/baseline/ticket checks, current-source browser export checks, evidence collection and isolated package verification.

The independent challenge inputs remain unexposed to the corrected candidate. No completed challenge evaluation or final v0.7 regression is claimed in this status document.

## Submission implications

The working planning, comparison and traceable-ticket software is substantially developed. A stronger scientific claim still needs measured bench responses and a useful decision against competent alternatives. The existing reference tie, protected-location failure and all-abstention policy result remain unchanged. Operator evidence and later observed shadow operation remain unperformed. Numerical qualification alone cannot establish physical accuracy, scheduling advantage or a competition placing. See `NEXT_STAGE.md` for the practical evidence sequence.
