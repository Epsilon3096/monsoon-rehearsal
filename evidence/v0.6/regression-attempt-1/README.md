# First full v0.6 regression attempt

The first complete run retained here finished with **796 passed and 1 failed**. The failure was the new UI export assertion in `test_boundary_receipts_responses_and_freeze_in_ui[False]`, which compared entire newly generated ZIP byte streams. ZIP member creation times can change between calls. A controlled clock comparison confirmed that both exports contained the same 89 named files with identical contents while ZIP headers differed.

The assertion was corrected to compare the complete ordered member inventory and every member's exact bytes, with ZIP integrity verification. This retains the intended evidence comparison without depending on ZIP creation timestamps. No production source, hydraulic calculation, tolerance, fixture or scientific result changed. The original test source, frozen identities, log and report are retained here. The final release regression is recorded in the parent directory.
