# Version 0.9.0 verification

Publication follow-up: archived webpage identifiers were subsequently redacted. The original package-byte comparison below predates that intentional change; application code, observations and numerical results remain unchanged. See [the cleanup record](../../SECURITY_REDACTION.md) and `publication-cleanup-tests.xml`.

Verified on 20 October 2026 in the pinned Windows environment.

- **652 product tests passed**, zero failures, errors or skips. Profile: `pytest-product.ini`.
- **23 focused demonstration/navigation tests passed** in the working copy and again in a fresh Git archive. These are subsets, not additional unique product tests.
- **36 native EPA SWMM runs** retained for the new benchmark: four positive comparison cases pass, zero-inflow control passes, high-backwater control remains unresolved.
- Maximum absolute native routing and independent volume-balance residual: approximately **0.03705%**. The original 1% numerical limits remain unchanged.
- **837 original package files compared**: no file missing; only documentation, interface, version labels and navigation expectations changed. Existing hydraulics, scheduling, checks and adverse evidence match the original package byte-for-byte.
- Dependency check: `python -m pip check` found no broken requirements.
- Browser review: benefit screen, adverse B2 screen and unresolved backwater screen inspected. The walkthrough cannot approve or dispatch work.

The complete product regression includes hydraulic calculations, scheduling, baseline comparisons, plan-specific audit enforcement, ticket lifecycle, stale-evidence and UI tests. Experimental bench tests remain outside the unchanged product profile; their earlier failures remain failures. This is not a passing full-research-suite result.

## Reproduce

```sh
python -m pytest -c pytest-product.ini -q --junitxml=var/reproduction/product-tests.xml
python -m monsoon.maintenance_benchmark --output var/new-benchmark-attempt
```

Use a fresh benchmark output directory. Do not overwrite the recorded attempt or replace adverse cases. The independent new attempt preserves its own native inputs and outputs.

The JSON record binds source files and test-report hashes. The benchmark manifest binds all raw evidence. Git stores evidence bytes without newline conversion so a fresh checkout passes the same integrity checks.

## Remaining external evidence

Actual operator feedback, surveyed/calibrated site response and an observed shadow trial are pending. The fictional practice conversation is not validation. Downstream-first ties the new one-job example; adaptive marginal ties the original planning result. No scheduler superiority or field benefit is claimed. Video remains on hold.
