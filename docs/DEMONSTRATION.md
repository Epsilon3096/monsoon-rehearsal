# Three-minute live demonstration

This is an interactive walkthrough, not a video. Open **Demonstration** in the sidebar. All examples are synthetic and read-only.

1. **0:00–0:50 — Maintenance benefit.** Two branches feed storage and a restricted terminal reach. Select T1: restored width reduces modelled spill from 481.2 m³ to 0.0 m³. Show T2–T4, then the zero-inflow control. Downstream-first chooses the same one job. No scheduling superiority or real flood reduction is claimed.
2. **0:50–1:20 — Work before rain.** With 120 minutes, the bounded 65-minute occupation fits. With 50 minutes, skip the job, even though its synthetic actual duration would have been shorter. Travel and return matter.
3. **1:20–2:10 — Catch transferred harm.** On the original four-job network, show the H2 record: less total spill but greater B2 spill. This blocks approval. Return to the maintenance case and select C_BACKWATER: the event-horizon check is unresolved, so it does not receive a benefit score.
4. **2:10–3:00 — Operational workflow.** Explain rehearsal → exact-plan stress audit → review → approval → tickets. The demonstration cannot write a ticket. Show the blank operator review packet and state that review and physical validation are pending.

For live computation, use **Rehearse → Run rehearsal → Audit selected plan** separately; cold SWMM runs take longer. Preserve the expected adverse result. The service's ticket lifecycle is tested with explicitly synthetic workflow fixtures; there is no field-approved nonempty reference queue.

Evidence: [maintenance rationale](MAINTENANCE_CASE.md), [prospective protocol](../data/benchmarks/outlet_restoration_v1.json), [recorded results](../evidence/v0.9/maintenance-benchmark/results.json), [original decision diagnosis](../evidence/v0.8/DECISION_DIAGNOSIS.md).
