# v0.6 native filename portability addendum

15 October 2026. This addendum records a packaging defect found after the original [focused review](REVIEW.md), its narrow filename-handling repair, and new numerical evidence. It does not change any hydraulic setting, balance tolerance, physical claim or previously recorded adverse result. The original review remains a historical report of its then-current source. Its exact bytes, source pins and JUnit record are preserved in [portability-history](portability-history/manifest.json).

## Observed failure and bounded repair

The isolated package smoke produced a numerically successful primary/refined audit but failed the existing artifact-integrity barrier. Each expected `model.out` path was 266 characters; the native output was instead written as `mo` at a 259-character path. The original input, report and native results were retained. The [preserved failure inventory](portability-history/package-audit-failure/preservation-manifest.json) includes both truncated outputs and the pre-fix audit sources. A numerical success without the required output file cannot qualify the replay.

The two new workers, `_bench_balance_worker.py` and `_bench_initialization_worker.py`, now pass `model.inp`, `model.rpt` and `model.out` to SWMM as local names. Their parent already launches each worker inside its isolated attempt folder. An explicit working-folder equality check ensures that the opened input is the same file whose bytes were checked. This changes filename handling only: the input bytes, artifact destinations, runtime, routing steps, solver settings, storage accounting and acceptance thresholds are unchanged.

The prepared-result verifier also requires the exact complete 18-file inventory for a successful pair. A self-consistent inventory containing a renamed native output cannot substitute for the expected files. The audit verifier already enforced the required eight filenames per successful child within the bounded 18-file tree; that existing gate rejected the original package failure. Failed attempts may still retain incomplete files for inspection, but cannot become qualified successes.

The historical `_bench_worker.py` and its parent adapter remain byte-identical. Their absolute-path limitation is **not repaired by this change**. For Windows deployments that invoke those legacy parent runs, set `MONSOON_DATA_DIR` to a short writable directory, for example `C:\monsoon-data`, before starting the application, and keep the generated native paths short. The new workers still require Windows to accept their working directory for process launch. A separate deliberately overlong-directory test failed before worker startup with `WinError 267`; its logs and incomplete artifacts are retained separately from the native filename-truncation evidence. The repair therefore does not claim arbitrary-length Windows path support.

## Native regression and unchanged scientific outcomes

The audit's [focused JUnit result](portability-balance-review/audit-tests.xml) records **14 passed in 12.98 seconds**, with zero failures, errors or skips. The new native regression creates 267-character `model.out` paths inside 257-character working directories, including spaces in the path. Both attempts retain the exact required filenames and pass full artifact verification against the unchanged parent. All input bytes, diagnostics and report samples equal those from the corresponding short-path audit. The [path-regression summary](portability-path-regression/summary.json) and [complete retained inventory](portability-path-regression/manifest.json) include the passing original parent, short audit and long audit, plus the separate unlaunched overlong-directory failure. Copies preserve historical absolute paths; their archive manifest binds exact copied bytes without claiming that relocation rewrites or restores live path identity.

The preparation owner separately verified its corresponding long-path case, exact input and numerical equality, complete native export, working-folder guard and required-file inventory barrier. Its current evidence is indexed by [prepared-bench-evidence.json](prepared-bench-evidence.json). Aggregate regression, browser checks and package smoke belong to the final integration record, not to this addendum's 14-test result.

Three fresh primary/refined pairs and additive audits are retained under [portability-balance-review](portability-balance-review/manifest.json), with the exact current audit/legacy source snapshots. The [summary](portability-balance-review/summary.json) compares each case to the preserved pre-portability evidence: both inputs, all diagnostics, every report sample and qualification outcomes are identical in all three cases. The bundle contains 118 files including its top manifest, with 3,426,385 payload bytes excluding that manifest.

| Synthetic case | Historical pair gates | Current cumulative audit | Change from earlier numerical records |
| --- | --- | --- | --- |
| Original 7 L pulse, original geometry | Pass | Reject | None |
| Rapid receiving-stage cycle, original geometry | Pass | Reject | None |
| Analytical compartment, elevated dry outlet | Pass | Pass | None |

The original [cumulative review](cumulative-balance-review/summary.json), [native phase probe](native-phase-review/summary.json) and [terminal-cell diagnostic](terminal-cell-diagnostic/README.md) remain unchanged historical evidence. The terminal-cell mechanism gains no additional scientific support from this filename repair; its numerical qualification failures remain failures. No real observations, physical calibration, independently validated hydraulics, engineering approval or operational activation are established.

The [refreshed reviewed-source pins](reviewed-source-sha256.json) bind the final portability sources; [the prior pins](portability-history/reviewed-source-sha256.json) remain preserved. This is a same-development-team review and regression exercise, not external certification.
