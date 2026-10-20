# What will most improve submission quality

The product already connects a drainage model, achievable-work scheduling, explicit alternatives and traceable work records. The next major improvement is evidence that those decisions are useful. Passing numerical and software checks alone cannot establish that claim.

## 1. Measure the supported bench system

Review the apparatus against `CONSERVATIVE_BENCH.md` before collecting results: rectangular channels, measured bed elevations and dimensions, explicit compartment volumes, one terminal channel per outfall, and represented spill collectors. Survey the entire stage–area curve, including dead storage and changes of area. Record roughness assumptions and instrument uncertainty separately from measured geometry.

Use a common clock. Independently measure the supplied inflow, receiving-water level, compartment and channel water levels, collected spill and cumulative exchange at the receiving boundary. A rising receiving level can add water to the rig; a discharge-only collection bucket cannot measure that input. Arrange a measured receiving reservoir or an appropriate bidirectional measurement method. Include retained channel water in the inventory. Do not use the numerical residual as an estimated boundary flow.

Demonstrate reset repeatability and a water balance before fitting model parameters. Use calibration events for development, then freeze the model, forcing/replay recipe, measurement error rules and genuinely new validation events before collecting those responses. Preserve every failed or interrupted run. The original 24-event protocol remains historical and incomplete; register any justified scope revision prospectively rather than marking unperformed events complete.

The separate conservative engine is not yet connected to the calibration/withheld-response ledger. That integration must retain its source/runtime identities, exact input histories, numerical qualification and full state at a preparation/evaluation split. It must not silently replace the older SWMM engine inside a frozen study or credit synthetic responses as measurements.

## 2. Establish a useful scheduling decision

Obtain a baseline decision from a facilities or drainage maintenance operator before showing the model's recommendation. Record the actual jobs, dependencies, access and equipment constraints, likely durations, completion/condition verification, stop-and-return rule and the reason for the operator's order. A lecturer's engineering review is useful but does not establish an operator's workflow or site authority.

Investigate why the existing recommendation fails at a protected location. Use the calibrated physical response and reviewed operating constraints to decide whether to revise the model, the policy or the intended claim. Keep the reference marginal-baseline tie and the ten-event all-abstention result visible. A policy that safely refuses every available action has not demonstrated a useful scheduling advantage.

After development, freeze a revised policy and a new evaluation before revealing outcomes. Compare with equally informed downstream-first, adaptive marginal, the operator's baseline and no-work. Report every event, protected-location failure, abstention and computation failure. Benefit must be earned on feasible work actually completed and verified before the deadline. Do not select only events in which the proposed method wins.

## 3. Observe operation before considering a pilot

Run a prospective shadow window: seal the model's decision and the operator baseline before work; let the authorised operator retain control; observe actual timing, condition verification, stop decisions and available information. Record discrepancies without retroactive information or replanning credit. A shadow trial establishes workflow evidence; it does not by itself isolate a causal reduction in flooding.

Use those records, engineering review and site authority to decide whether a supervised pilot is appropriate. Field activation and unsupervised dispatch remain closed. The shadow trial and pilot are separate from delivering an honestly labelled hackathon prototype.

## Submission assessment

Software completeness is substantially ahead of physical and operational evidence. The highest-value next work is a measured bench comparison and a defensible useful decision against competent alternatives. A larger feature list will not substitute for either. No competition placing can be guaranteed, and this document does not assert that an operator, experiment, trial or submission has occurred.
