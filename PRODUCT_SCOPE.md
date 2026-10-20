# Monsoon Rehearsal v0.8.1 product scope

This is a local synthetic drainage-planning and review prototype. It helps a reviewer inspect achievable maintenance, compare consequences and retain the reasons a plan can or cannot proceed. It is not a surveyed township model or a claim of a superior optimiser.

## The demonstration

1. Launch `Start.cmd`. The default pages are Rehearse, Work window, Work tickets and Evidence.
2. In Rehearse, keep the four planning scenarios and 180-minute deadline; run the rehearsal. Compare the robust queue with the adaptive marginal and downstream-first alternatives. The marginal baseline ties the robust queue in the original planning cases.
3. Audit the selected plan. The decision appears above the controls. Inspect the audit's own case and achieved prefix, including baseline spill, resulting spill, signed change and the permitted increase. The reference recommendation fails the broader screen; save its blocked draft and export the briefing. Work tickets must refuse review/approval/dispatch for this plan. Selecting no additional work changes the candidate only: that candidate needs its own audit and review. Approval of an empty queue creates no work tickets and does not remove existing flood risk.
4. Use Work window to inspect the consequences of an earlier stop. Unverified or disturbed work does not automatically count as restored or unchanged.
5. Open Evidence for the comparisons, model assumptions and adverse results. The full positive ticket state machine is verified with explicitly arithmetic software fixtures; it is not a measured maintenance operation or a hydraulically approved nonempty plan.

The product contribution being demonstrated is transparent consequence review with scheduling constraints and traceable decisions. A useful operational benefit and a scheduling advantage both remain unproved.

## Research boundary

Show research tools is an explicit opt-in. The validation workspaces remain available for research records and inspection. The custom conservative bench solver is experimental and unqualified: its water accounting passes, but its complex-pulse mesh accuracy fails. Earlier complex SWMM bench balance failures also remain failures. Neither is part of the v0.8 supported demonstration claim. No numerical tolerance or approval gate is relaxed by this scope change.

The full historical test collection remains available. `pytest-product.ini` declares a separate product regression scope by excluding `test_bench*.py`; this is not a passing full-research-suite result. It still includes real SWMM numerical tests, unchanged planning and audit tests, ticket tests, work-window tests, source/evidence binding, public-data checks, and non-bench research record regression. Each execution records its selected and excluded files. Research navigation isolation is tested explicitly.

## Reproduce the product checks

From this directory with the pinned environment:

```powershell
python -m pytest -c pytest-product.ini -q --junitxml=var/reproduction/pytest.xml
python -m monsoon.verify --output var/reproduction
```

Use a fresh output directory for a separately retained attempt. Verification uses isolated workflow records and never completes a ticket in the interactive workspace. Raw engine outputs may be reused only through the existing checked content-addressed cache. Zero skipped tests are required for a passing verification summary.

## Remaining evidence

The existing stress model admits no nonempty queue across its required envelope. The next scientific task is to determine whether intervention assumptions, downstream constraints and available observations support useful work in a defensible scope. Any revised model or policy needs a separately declared evaluation with equally informed baselines and all adverse cases retained. Do not remove inconvenient uncertainty or protected locations to manufacture a winning queue.

Operator feedback, independent hydraulic measurements and observed shadow use remain external work. They are separate from a runnable hackathon prototype. Presentation, video, team/eligibility records and organiser submission fields are outside this code package and have not been submitted.
