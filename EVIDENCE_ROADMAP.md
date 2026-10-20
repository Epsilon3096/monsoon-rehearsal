# Evidence and next build priorities

Research status: 13 October 2026. Project scope remains the product and its validation. Slides, video, registration and submission are separate later tasks.

## Do we need evidence before submitting?

Yes: enough evidence to support the claims made in the proposal. A completed field pilot is not listed as a prerequisite in the public programme guidance reviewed today. Its judging rubric includes research, validation, prototype and demonstration quality; feasibility and measurable potential impact also matter. The public schedule gives proposal submission on **23 October 2026** and final submission on **11 November 2026**. Check any additional briefing or organiser-specific instructions before the actual submission.

Source: [official programme guidance and schedule](https://www.simedarbyproperty.com/universityhackathon/). This is a practical reading of the published guidance, not an organiser ruling. No application or submission has been made by this work.

The submission can truthfully demonstrate an executable model, fair comparisons, numerical checks, traceable tickets and refusal to approve an unsupported plan. It cannot yet claim measured flood reduction, site readiness, superiority over a competent adaptive scheduler or a guaranteed prize. The original robust queue ties the adaptive marginal baseline in all four planning cases and both revealed holdouts. It fails a protected-location check in H2 despite lower total spill. The new development audit also exposes parameter sensitivities. Preserve those findings.

## What public evidence can establish

See `evidence/PUBLIC_DATA.md` and `data/public_evidence/` for acquired files, source URLs, retrieval dates, checksums, quality issues and external-engine checks.

| Evidence | Useful now | Does not establish |
|---|---|---|
| Official METMalaysia general forecasts and warnings, accessed through data.gov.my | A working public-data adapter, dated regional context and warning record handling | Numeric rainfall intensity, a calibrated inflow hydrograph, storm-arrival probability or a safe work deadline |
| Public JPS rainfall observations | Data-quality and station-matching work, observed regional rainfall context | An event hydrograph for the unsurveyed synthetic catchment, a drainage geometry survey or causal maintenance benefit |
| Official EPA example/QA models | External model compatibility and numerical regression checks with separately recorded failures | Calibration of our township model or proof that our scheduler outperforms alternatives |
| Our frozen synthetic reference and development sensitivity cases | Software correctness, scheduling consistency, numerical adequacy, risk transfer and transparent refusal | Independent physical validation or representative frequencies of real storms |

Public downloads are useful evidence, but collecting more unrelated files will not replace matched observations of rainfall, downstream water level, asset condition and response. Public weather context remains outside the frozen synthetic hydraulic inputs. Never convert phrases such as thunderstorms into an invented millimetres-per-hour series. Daily rainfall totals cannot recover an unobserved five-minute storm pattern.

## Next, in priority order

### 1. Validate the operational decision with a drainage operator

The unresolved product question is whether the operator actually faces consequential choices among achievable maintenance subsets, and what they use today. Arrange a focused review with a township drainage engineer or maintenance supervisor. The user will make access requests later; no outreach has been sent.

Ask them to walk through a recent real maintenance window: available crew, authorised jobs, access, restoration deadline, downstream condition, current prioritisation, late work, and evidence required for closeout. Ask for their proposed order **before** revealing our ranking. Record disagreements and counterexamples, including occasions where no discretionary work is appropriate. Do not imply that SDP currently schedules poorly without this evidence.

Completion criterion: a reviewed workflow and baseline, a bounded candidate site, named decision inputs and approved model boundaries. A testimonial alone is insufficient.

### 2. Resolve the physical uncertainty behind failed recommendations

Use a surveyed small catchment or an instrumented bench network to measure initial storage, receiving-water stage, restrictions and restoration effects. Check the mechanism first with measured inflow and outflow, then tackle rainfall-runoff calibration separately. Keep the designed storage outlet fixed unless a separately authorised engineering design changes it.

The current pre-event work model needs physically credible initial states. Its elevated-stage diagnostic includes a cold-start boundary transient; it is not a calibrated tidal event. A site model should define spin-up/initialisation from observations and use measured boundary time series. Retain the original model and results as regression evidence; create a new version for these changes.

Completion criterion: before/after interventions mapped to measured geometry, mass balance and depth/flow response checked against observations, with uncertainty and instrument accuracy reported. Use withheld measured events for validation; do not calibrate and claim validation on the same event.

### 3. Make a revised policy earn its benefit on a new frozen evaluation

The present queue passes its four planning cases but fails the wider development envelope. This supports abstention, not relaxing the safeguard. A useful next policy may condition decisions on **actually observed** storage level, receiving-water level and verified asset condition, while maintaining a defensible uncertainty envelope. Observation-based conditioning must not use future event outcomes or remove difficult cases after seeing the answer.

Before tuning the next version, freeze an evaluation protocol with independent catchments/events or measured rig trials. Include realistic cases where downstream-first is correct, where the marginal baseline is correct, ties, harmful intermediate work states, duration overruns and no-work decisions. Freeze operator, downstream-first, marginal-benefit and deterministic baselines under equal constraints and information. Separate development cases from unseen evaluation cases.

Measure per-location spill and threshold duration, total spill, completed jobs, crew time, deadline failures, abstention rate and computation time. Report paired outcomes by independent event/catchment. Numerical step changes are convergence checks, not extra independent samples. Quantify uncertainty when the dataset supports it; a handful of designed examples does not justify population-level performance claims.

Completion criterion: reproducible, honestly reported comparison including losses and ties. If the method only ties a simpler baseline, use the simpler policy and position the product around traceability, consequence inspection and refusal of unsupported work. Do not add algorithmic complexity merely for the pitch.

### 4. Add site import and operational controls after the data contract is settled

Implement versioned drainage-network and job imports with units, coordinate reference system, vertical datum, connectivity, duplicate-ID and missing-value checks. Show a human-readable change review before a new model becomes active. Keep missing observations as unknown values with clear consequences; do not silently substitute a plausible number.

Add authenticated reviewer/dispatcher/inspector roles, attachments with provenance, backup/restore, permission checks and concurrent-user tests before shared operational use. Multiple crews, variable travel and access windows come after the exact small-case reference still matches the expanded solver. A web deployment alone does not make the system field-ready.

### 5. Run an observed shadow trial, then consider a supervised pilot

First run recommendations without directing real work, comparing the operator's actual plan with the model's recorded decision using only information available at the time. Inspect false confidence, refusal frequency and missing inputs. Only a responsible site engineer can define the operational work envelope and approve a live pilot. Keep work-site safety controls outside an inferred flood score.

Completion criterion: timestamped shadow decisions, observed outcomes, accepted maintenance constraints and explicit stopping/exception rules. Estimate commercial value from measured planning effort, crew use and operational costs; do not monetise uncalibrated node spill as avoided property loss.

## Data request specification for later

Prefer a small, complete, well-documented site package to a large collection of mismatched records. Ask for whatever is available first, with omissions recorded. The following is a draft request scope for the user to send, not a message already sent.

| Route | Access status | Request to prepare |
|---|---|---|
| [myMETdata](https://mymetdata.met.gov.my/) via [METMalaysia's official FAQ](https://www.met.gov.my/en/info/soalan-lazim/) | Formal data request; supply and fees depend on category and availability. The FAQ lists a student/government remission route. | Historical rainfall for the selected site's relevant stations, event dates, time resolution and quality metadata. The FAQ lists hourly/daily products; verify whether finer resolution exists for the chosen station. |
| [JPS hydrological data guidance](https://www.water.gov.my/index.php/pages/view/857) | Application forms and station inventory; research/academic terms apply. Public InfoBanjir snapshots are a different evidence source. | Matched historical rainfall, water level and discharge, including station availability, units/datum and quality flags. Use the official guidance to identify the current application route. |
| [JPS geospatial data portal](https://data.water.gov.my/home) | Registered request. The portal lists a lecturer/educator category requiring supporting documents. | Catchment and relevant river/drainage GIS where held. Use university support if needed; do not assume this includes SDP's private as-built asset survey. |
| SDP/site drainage operator | Owner permission and availability required | As-built drainage survey, storage/outlet details, job records, restrictions and verified conditions for one bounded pilot area. |

The public open forecast route already used is [data.gov.my's no-token API](https://developer.data.gov.my/quickstart). There is no need to register for a separate MET API just to reproduce these public snapshots. No accounts, paid orders, personal documents or requests were submitted. Select the site and observation period before requesting an expensive or mismatched archive.

| Request | Required fields and units | Why it matters |
|---|---|---|
| Drainage asset network and survey | Stable asset/node IDs; endpoints; coordinates and CRS; invert and ground levels in metres with vertical datum; measured dimensions/sections; lengths; slopes; connections; storage level-area relation; outlet/control details | Builds the hydraulic network and distinguishes a restriction from designed detention |
| Condition and restoration records | Asset ID; observation date/time and timezone; measured sediment/debris/restriction; photos and inspection method; approved before/after geometry; inspection uncertainty | Defines what maintenance physically changes and the confidence in it |
| Rainfall, water level and flow | Station ID/location; timestamp/timezone; sample interval; quantity and unit; incremental versus cumulative rainfall; water-level datum; quality flags; missing periods; sensor/calibration history | Aligns boundary conditions and response without inventing storm patterns; preferably event-scale records at 5–15 minute intervals where available |
| Maintenance work orders | Job ID and asset ID; job type; assignment/start/finish/restoration/verification timestamps; travel, setup and disposal times where recorded; crew/equipment; access/prerequisites; interruptions and reason; actual quantities | Tests duration bounds, achievable subsets and the operator baseline |
| Flooding/overflow observations | Date/time; observed location; measured depth or level and reference datum; duration; photos; confidence; whether sensor, inspection or reported observation | Separates measured response from modelled node spill and supports event validation |
| Operational constraints | Work and restoration deadlines; weather stop rules; access permits/windows; crew qualifications and equipment; protected locations and acceptable thresholds; closeout evidence requirements | Defines authorised decisions and review rules |
| Cost and workflow evidence | Crew/equipment/disposal costs; planning time; repeat visits; current prioritisation procedure; anonymised identifiers if needed | Supports a defensible value estimate and usability assessment |
| Use and publication permission | What may be analysed, retained, shared with judges, shown publicly or redistributed; preferred attribution | Keeps the evidence package aligned with the data owner's permitted use |

## Readiness ladder

- **Executable prototype:** achieved for the stated synthetic scope; verify the current release report for exact checks.
- **Submission evidence package:** software results and dated public context can be assembled now; additional field access need not prevent a proposal submission. Claim limitations must remain prominent.
- **Validated decision advantage:** not yet established. Needs operator-reviewed baselines and unseen or measured evaluation.
- **Field pilot:** not yet ready. Needs site data, calibration, operating rules and responsible engineering review.
- **Production:** later; needs authenticated operation, maintenance, monitoring and operational assurance in addition to scientific validation.

The most valuable next investment is matched operator and physical evidence. More interface features should follow the findings from that evidence.
