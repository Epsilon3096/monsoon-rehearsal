# v0.4 implementation review

14 October 2026. A separate review agent inspected the additive early-stop audit, bench preparation generator and their UI. This is a software review, not an independent physical study or professional approval.

Four substantive temporal/input defects were identified during development and corrected before the final source freeze:

| Finding | Correction | Regression coverage |
|---|---|---|
| A verification available by the stop could earn restoration credit although its prerequisite start or completion record arrived later. | Cutoff credit requires the start, separate completion and accepted verification in the known-at-cutoff view. Retrospective/current views remain separate. | Independently delayed start, completion and verification; exact cutoff and next floating-point boundary. |
| An interruption after a reported completion could reuse that earlier completion for restoration credit. | Reject this inconsistent sequence in the one-start/one-completion contract; a later work cycle requires a different supported record. | Start → completion → interruption → accepted verification is rejected. |
| An imported replay could have an impossible maximum-duration dispatch bound while still claiming original supported status. | Check every dispatch bound plus uniform return allowance against its original deadline, using the original scheduling tolerance; check uniform travel consistency. | Impossible maximum duration, return allowance and chronology mutations are rejected. |
| A physical completion/interruption could be recorded after the crew began returning. | Reject later physical work events in this single-window contract. Retain later reports of earlier occurrences through their availability time, and allow later condition inspection. | After-departure/arrival events rejected; exact departure boundary, delayed reports and later inspections retained correctly. |

The reviewer found no additional substantive defects in the bench-preparation or UI scope reviewed. An independent interface check confirmed that editing either observed input hides the stale result/download. Root added a persistent UI regression for the two-input binding and for missing observations staying unresolved.

The work-window module's final targeted run passed 110 cases. Bench preparation passed 23 cases, and the new UI passed five cases. The release's complete test count and numerical regression status are recorded separately in `pytest.xml` and `verification.json`; targeted checks are not additional independent experiments.

All ten pinned v0.3 source bindings and 124 reviewed historical data/evidence files matched their saved identities during review. The original bench protocol remained unchanged. The final packaging step rechecks frozen source/result hashes and all three earlier source archives. No earlier adverse outcome was removed or relabelled.

Residual scope: evidence references and log-coverage assertions are documentary inputs, not independent authentication of physical truth; the audit never authorises work or hydraulics. The blank bench pack makes no claim that a rig, calibration, participant review or validation run exists. Arbitrary wet-work transitions and repeated work cycles remain outside this MVP.
