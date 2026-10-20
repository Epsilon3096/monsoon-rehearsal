# v0.8.1 decision-interface verification — 17 October 2026

The agreed interface improvements are implemented and verified. This release improves the synthetic consequence-review prototype. It does not fix or qualify the separate custom hydraulic solver, establish a scheduling advantage, or validate a field site.

## Verification

- **634 product-profile tests passed**, with zero failures, errors or skips. The frozen profile includes 31 modules and retains the same 19 excluded dedicated bench-research modules. This is not a full research-suite pass.
- Source, tests and inputs matched the pre-run freeze; the verification runner remained unchanged. Exact commands, identities and outputs are in `product-20261017-05/result.json` and `source-freeze.json`. The source-bound collection includes every original 622 case plus all newly collected cases, with exact coverage across disjoint shards.
- The original SWMM numerical, scheduling, baseline and approval-gate verification passed. The cache-I/O change changed the adapter fingerprint; results carrying the old fingerprint cannot count as cache hits for the new adapter. Within-run checked cache reuse is not a new physical experiment or a claim that every invocation was cold. Detailed outcomes remain in `product-20261017-05/VERIFICATION.md`.
- New UI checks cover the empty queue's own audit/review/approval without tickets; the actual H2 audit independent of planning-scenario selection; exact prefix results; matching scenario/reference spill changes; stale controls; and verified-work replanning. Positive job transitions use explicitly arithmetic software fixtures. The H2 refusal uses real SWMM results.
- Live browser inspection at 546 × 668 pixels confirmed the failed reference audit (5/15 cases), H2/B2 baseline 280.7769 → result 810.7718 m³, independently audited empty-plan wording, and a matching signed diagram/table. No work was approved or dispatched in the live workspace. See `browser-check.json` and `screenshots/`.
- Byte comparison against v0.8 and review of the adapter diff confirm that the scientific inputs, hydraulic calculations, scheduler, numerical criteria and approval logic are unchanged. One legacy UI test now expects the new wording and warning level; its absence check is stronger, rejecting any success indicator after a queue change or stale inputs. The first full attempt retained 621 passes and one obsolete-copy failure. A second attempt stopped on missing temporary-folder parents in the parallel test harness. The third retained 621 passes and one Windows sharing-lock error while publishing a completed run's cache index. The fourth attempt retained 619 passes and 13 historical-replay test failures: the new adapter correctly failed the old study source-identity gate, while the tests still assumed the old identity. Mocked guard tests now explicitly supply the recorded identity, retain all original guard assertions, and add independent current-source and engine-refusal checks. The product replay gate and historical records remain unchanged. All adverse attempts remain retained. The cache fix adds bounded retries only for Windows sharing/lock errors; an exhausted optional index cannot invalidate the independently sealed run, and failed runs remain failed. Ten injected-error tests cover this behavior without running an engine. All collected cases were rerun in the final attempt across disjoint process shards. See `change-audit.json`. No numerical or approval criterion was weakened.

## Changes

The selected-plan verdict and audit actions precede details. Audit cases are separate from planning scenarios and show baseline, result, change, allowance and achieved prefix. Failed states are selected first by default. Optional traces must match the exact audited run and file checksum. Missing values remain unavailable.

No additional work is an explicit candidate with its own audit. Unknown physical condition and stale context remain blocking. Absolute spill and signed-change diagrams include symbols, labels, an accessible table and the complete modelled restoration state, including previously verified jobs. The original planning-search summary is clearly separated from the selected plan's audit decision.

Cache-index publication now tolerates brief Windows sharing locks, with five attempts and at most 150 ms backoff. The sealed private result and its manifest remain the source of evidence. Unrelated I/O errors still propagate.

The strict v0.3 recorded replay refuses this changed runtime. Its historical reproduction requires the preserved v0.8 source and matching environment; the current release does not claim a new reproduction of that research study.

## Remaining limits and next work

The revised Gemini reply corrects its main earlier reasoning errors, but proposes an unexecuted diagnostic rather than a demonstrated solver repair. Custom-solver research remains paused. Actual-transfer water accounting passes while complex-pulse mesh accuracy remains unqualified; the earlier SWMM bench failures remain retained too.

No nonempty queue passes the broader original decision envelope, the marginal baseline still ties the original planning result, and operator/physical evidence is absent. The next substantive improvement needs an independently justified maintenance intervention and measured or operator-reviewed site conditions, then a prospectively frozen comparison. More interface polish or solver search alone does not establish useful maintenance benefit.

The v0.8 archive remains unchanged. The separate v0.8.1 package check must report `archive_qualified: true` before its ZIP is described as verified. It checks exact extraction and isolated UI startup in a path with spaces using the installed pinned runtime; it does not claim a fresh dependency installation or a new cold hydraulic study.
