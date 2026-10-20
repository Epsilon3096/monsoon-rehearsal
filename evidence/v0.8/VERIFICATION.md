# v0.8 SWMM product verification — 17 October 2026

The explicitly scoped product verification passed. This qualifies the local synthetic rehearsal/review workflow for demonstration; it does not qualify the custom bench solver, establish scheduling superiority, or validate a real drainage site.

## Executed verification

- **580 tests passed**, zero failures, errors or skips, in 588.79 seconds. The declared profile includes 26 test modules and excludes 19 dedicated `test_bench*.py` research modules. All original files remain available in the default full collection. This is not a full research-suite pass.
- The complete source/test/input inventory matched its pre-run freeze, and the verification runner remained unchanged. See `product-20261017-01/source-freeze.json` and `result.json` for exact identities, selected/excluded files, commands, exit codes and artifact hashes.
- The retained original SWMM model passed 144 state/scenario comparisons at 0.5 and 0.25 seconds: 288 requested evaluations, 260 distinct run identities. Checked cache reuse and equivalent pre-restored states are not independent replicates or a cold rerun. Maximum absolute routing continuity error was 0.381930%.
- The existing event-horizon check passed at 180 versus 360 minutes. The imposed-stage D1 diagnostic remains horizon-sensitive and is explicitly not a complete-event loss estimate. No criterion or diagnostic designation was changed for this release.
- All 65 reference queues were reproduced: 28 supported on the original planning grid, 37 inadmissible. The adaptive marginal baseline still ties the robust queue; the adverse H2 results remain unchanged.
- The selected nonempty plan fails five of fifteen required development cases. Its intact failed audit is saved durably; review is refused and no job ticket is issued. The real no-additional-work audit passes, but an attempt to create a job ticket from that empty plan is refused. Full actual-work state transitions are covered by explicitly arithmetic software fixtures, not represented as real approved maintenance.
- Browser inspection verified the four default pages, three historical decision explanations, explicit research opt-in, unqualified-solver warning and return to Rehearse when research tools are disabled. See `browser-check.json`.

The detailed generated numerical/workflow report is [product-20261017-01/VERIFICATION.md](product-20261017-01/VERIFICATION.md). Raw hydraulic files remain in the local checked cache and can be regenerated; this source delivery carries compact evidence rather than the complete cache.

## Product changes

Rehearse, Work window, Work tickets and Evidence are the default workflow. Research tools require an explicit opt-in. Three checksum-bound historical examples explain scenario-level benefit, total-spill reduction with protected-location harm, and numerical uncertainty with a separate resolved harm. Altered or missing source evidence suppresses the examples. They cannot approve or dispatch work.

The verification report now refuses skipped tests and writes to a new reproduction location by default. Scientific source, synthetic cases, thresholds, scheduling rules and approval gates are unchanged. The installed custom solver remains `ae817c13e99ede0aa03dbb00ef3c0d92f3f7e2b718b5a1c9c3a3a36db16ce461`; its original complex-pulse mesh failure and earlier SWMM bench balance failures remain unqualified research.

## What remains unresolved

[DECISION_DIAGNOSIS.md](DECISION_DIAGNOSIS.md) explains why no nonempty queue passes the broader current decision envelope. All five numerically unresolved queues also have resolved protected-location failures elsewhere; a numerical fix alone would admit none. The new cards expose those facts without selecting favourable outcomes for approval.

An operator-nominated intervention, independently justified geometry/boundaries/uncertainty and measured response are the next route to a useful operational claim. A revised policy must earn its result on a separately frozen evaluation with competent baselines. No interview, rig measurement, observed shadow trial, field pilot or scheduling advantage is claimed. Formal competition materials and submission remain separate and pending; see `SUBMISSION_STATUS.md`.

## Delivery check

The source archive's separate `Monsoon_Rehearsal_v0.8_Package_Check.json`, alongside the ZIP in the workspace outputs folder, records extraction integrity, isolated app startup and one fresh SWMM zero-inflow run. It must report `archive_qualified: true` before the ZIP is described as checked. It uses the existing pinned runtime; a fresh dependency installation and complete cold-cache study are not claimed. Full experimental investigation records remain in the original workspace `work/` directories, with historical summaries and original test files retained in the source package.
