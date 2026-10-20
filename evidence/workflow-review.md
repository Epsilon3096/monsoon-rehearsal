# Independent workflow review

Reviewed 13 October 2026 against the project blueprint, implementation contracts and ticket API. Scope: approval provenance, state transitions, observations, uncertainty, scheduling consistency, persistence, and independent SQLite connections. This is software verification on synthetic data, not operational or hydraulic validation.

## Findings and disposition

| Priority | Reproduction and consequence | Resolution |
|---|---|---|
| P1 | An old evaluated snapshot could be saved after context changed; saving attached the current version and inputs to old results. | Save now requires the calculation's fingerprint and state version and checks both inside the write transaction. |
| P1 | Work could change between reading state and installing context, after context commit but before its returned state, or during evaluation. Results could inherit the wrong revision. | Context installation checks the observed version, returns its captured state from the same transaction, and evaluation checks that revision again before returning a supported episode. |
| P1 | Opening Work tickets directly after a case, software or engine change did not refresh the calculation identity; unstarted approval could remain usable. | Every application entry registers a durable runtime identity. A change invalidates unstarted approvals, while already-started observations retain their original approved scope. |
| P2 | Separate reads could combine old completed jobs with new readiness, or old project state with new tickets/events in an export. | Composite reads and exports now use a coherent database transaction. Independent commits cannot splice revisions together. |
| P2 | A delayed start could make a later job feasible while the originally first job no longer fitted, without a way to record the new clock. Simply permitting the later job would admit a potentially unevaluated hydraulic state. | `record_delay` records waiting at the actual location, advances the clock, invalidates approval and requires a new rehearsal. The original queue gate remains conservative. |
| P2 | A changed definition of a verified job could prevent application entry before administrative closeout. | Historical scope remains accessible; further planning is explicitly blocked until a separately reviewed model state exists. |
| P2 | Returning controls to earlier values could re-enable Save despite a changed state version; a selected plan dictionary could also retain an old `is_stale` flag after a recorded delay. | The UI checks both fingerprint and version. Plan, ticket and inspection selectors retain stable IDs and resolve current records rather than retaining old dictionaries. |

Historical ticket defaults now read the ticket's saved job definitions, so removing an uncompleted job from the current inventory does not prevent viewing or cancelling its historical ticket.

## Verification

The focused run completed with **50 passed in 1.45 seconds**:

```text
python -m pytest tests/test_tickets.py tests/test_workflow_review.py -q
```

The run used the workspace runtime at `work/runtime/venv/Scripts/python.exe`. Orchestration race tests replace the expensive evaluator and engine identity only; approvals, completion, verification, persistence and competing connections use actual SQLite. Deterministic interleaving hooks test both sides of context installation without relying on thread timing. Existing tests also check competing verifiers, rollback on audit failure, immutable approvals, failed verification, honest duration overruns and prerequisite/order gates.

Schema version 2 adds the durable runtime identity. The additive migration preserves version 1 history. Tests cover reopening the store, unchanged runtime idempotence, runtime changes during active work, and exactly-once accepted restoration.

Final UI acceptance completed with **5 passed in 20.21 seconds**:

```text
python -m pytest tests/test_app.py tests/test_ui_workflow_review.py -q
```

These tests exercise Streamlit through its application testing interface and the actual EPA SWMM-backed service, including validated hydraulic-cache reuse; the solver is not replaced by a test double. They cover rehearsal, saving, review, approval, dispatch, completion reporting, accepted verification, administrative close, durable reopening, changed controls, a deadline round-trip, recorded delay, disabled stale controls, cancellation and fresh approval, failed inspection, revised finish time, and replanning from the observed clock and job location.

No unresolved functional workflow blocker remained in this focused review. The review does not establish production authentication, tamper-proof external audit storage, multi-crew support, residual hydraulic-state modelling, or field validity. The application continues to treat those as outside its declared research scope.
