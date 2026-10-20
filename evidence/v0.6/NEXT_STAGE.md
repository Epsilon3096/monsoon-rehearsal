# Next stage after v0.6

This is a proposed investigation sequence, not a completed experiment or a frozen physical-validation protocol. The current source and adverse evidence remain the reference.

## 1. Resolve the complex bench accounting discrepancy

**Follow-up already completed during v0.6:** the [terminal-cell diagnostic](terminal-cell-diagnostic/README.md) tested one predeclared 1/2/4-segment representation of the same physical reach. The observed residuals closely followed the predicted boundary-associated half-element storage term. This provides strong support for a specific discrete accounting mechanism, while all three cases still fail the unchanged conservation budget. The next work is a reviewed numerical treatment and its independent checks, not repeating this diagnostic or treating subdivision as a repair.

Start from the retained original pulse and rapid receiving-stage cases in `cumulative-balance-review/`, and the independent routing-step probe in `native-phase-review/`. Reproduce their failures before changing anything. The successful simple storage compartment is a control; it cannot replace the failed flowing cases.

Review how the pinned runtime represents water and flux at the terminal conduit/outfall boundary. A boundary/storage discretization explanation is a hypothesis. Establish whether the discrepancy belongs to the exported volume definition, the model boundary representation, the integration convention, or the engine calculation. Do not subtract a fitted correction or exclude a compartment merely to make a residual vanish.

Before examining a new parameter sweep, record its geometry, forcing, time-step grid, diagnostic quantities and unchanged acceptance thresholds. Begin with a single flowing conduit, then add storage and the receiving-stage cycle one change at a time. Compare live water, native cumulative totals and independently integrated signed boundary exchange at every routing step. Account explicitly for numerical initial water. Keep all attempted configurations and their failures.

Closure requires a documented mechanism and tests that reproduce the original failure, catch it under the old implementation, and verify the correction without relaxing the budget. Repeat both time steps, preparation/evaluation accounting, original adverse cases, analytical controls, and evidence-integrity checks. Until then, the affected predictions remain numerically unresolved.

## 2. Collect independent observations in parallel

Commission and survey the actual apparatus, record the common datum and storage curves, calibrate sensors, quantify measurement uncertainty, and preserve raw logs. Acquire an operator's maintenance baseline before revealing the planner's answer. Neither task is completed by a synthetic fixture or an online reference dataset.

Select the supported initial-state scope before collection. v0.6 boundary replay supports cold starts. Its continuous wet-preparation capability is separate; combining the two requires an explicit contract and review. Preserve the original 24-event protocol and prospectively register any narrower physical experiment rather than silently treating this release as its completion.

## 3. Establish calibration and withheld accuracy

Use actual supplied boundary traces and separately measured responses. Record all calibration attempts and the reason for manual model selection. Define physical acceptance criteria and their uncertainty treatment before freezing future validation events. A complete calibration-response record is not proof that errors are acceptable.

Freeze the model, processing recipe and future event assignments before collection. Receive boundary inputs, seal predictions, then receive responses through the ledger. Missing, invalid, interrupted and adverse records remain visible. Same-solver synthetic responses cannot count as independent validation.

## 4. Test decision benefit, then operational use

Only after the relevant hydraulics are supported, freeze a new policy evaluation with the same information and constraints for every competent baseline. Preserve the original baseline tie, H2 protected-location failure and later all-abstention result. A lower aggregate spill cannot excuse worsening at a protected location.

Require demonstrated useful decisions on new evaluation cases before making a scheduling-benefit claim. Use an observed shadow trial to compare proposed decisions with the operator's actual process. A responsible engineer's review and site-specific operating controls precede any supervised pilot; no field activation is created by this release.
