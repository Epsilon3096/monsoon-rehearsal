# Monsoon Rehearsal v0.5

Added a separate imported bench model and calibration/freeze/withheld-response ledger. The original hydraulic study, four-job scheduler and prior adverse findings are unchanged.

**672 tests passed, zero failures/errors/skips.** The full-suite source/test/input freeze, original-model numerical and ticket verification, synthetic bench roundtrip, browser check and independent review are retained here. The source bundle contains the compact evidence and fixtures. Current raw runs, databases, credentials and the Python environment are excluded.

The bench adapter runs real SWMM, includes node and conduit storage, retains the numerical initial water volume, integrates signed receiving-water exchange and checks two time steps. Only nominally dry starts and fixed geometry are supported; unresolved conservation, nonconvergence, unrepresented overtopping or step disagreement prevent numerical acceptance. This does not establish physical accuracy.

Study predictions run internally against the exact model and engine. Calibration precedes an immutable local freeze; withheld assignments and response contracts are fixed before measured collection. No automatic fitting or physical acceptance is performed. Error calculations use declared forcing; actual measured boundary replay and mismatch checks remain future work. Local times/hashes do not establish evidence authenticity or professional authority.

The separate practice exercise uses the same solver plus known 1 mm and 10 mm offsets. Its passing result verifies software lineage/error arithmetic only. The complete original 24-run physical protocol remains unsupported because wet/equilibrated starts are absent. There are still no actual operator interviews, measured experiments, observed field shadow trials or pilots.

Next: actual rig survey and sensor calibration, reviewed initialization and boundary accounting, real calibration responses, prospectively frozen independent response events, an actual operator baseline, then a new policy evaluation and observed shadow trial. No new scheduling advantage or prize outcome is claimed.

All 141 historical data/evidence entries checked from the v0.4 manifest, v0.3 frozen source hashes and prior archives remain unchanged. Separate package smoke checks use the existing pinned runtime, not a fresh dependency installation.
