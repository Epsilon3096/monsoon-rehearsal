# Prototype integration contracts

Implementation owns `outputs/monsoon-rehearsal`. Runtime is `work/runtime/venv/Scripts/python.exe` relative to chat root. All three agents share this checkout. Edit only owned modules; communicate contract changes first.

Use ordinary JSON-serialisable dictionaries at module boundaries; validate inside modules. No credentials or field data. All case data are explicitly synthetic, all jobs discretionary, one crew, dry pre-event maintenance with restored fixed states. Upper duration bounds include all on-site occupation. Route travel is separate; default uniform 10 minutes including depot access and return. Common deadline is minutes after shift start.

## Case owned by hydraulics

`monsoon.case.load_case() -> dict` returns:
- id, title, description, model_version, evidence_status='synthetic'
- jobs: list of dicts with id J1..J4, title, asset_id, description, nominal_minutes, max_minutes, downstream_rank (0 first), prerequisites list, cost_rm (illustrative).
- nodes: list of dicts id,label,x,y (schematic coordinates),kind.
- links: list of dicts id,from_node,to_node,job_id optional.
- scenarios: list dicts id,title,phase (planning|holdout|diagnostic), description, hydraulic (dict of engine forcing/geometry settings), durations (dict Jid: realised on-site minutes).
- default_deadline_minutes=180, travel_minutes=10, protected_nodes list, epsilon_m3=0.05, tie_m3=0.05.
Planning and holdout scenarios must be distinct IDs/families, no performance-target tuning. Root UI lists planning only. Jobs should initially use nominal [90,45,60,75], max [100,55,70,85] minutes (can adjust with notice). Field truth isn't known to policy.

## Hydraulics owned by hydraulic implementation agent

`monsoon.hydraulics.run_state(completed_jobs, scenario, cache_dir, routing_step=1.0, horizon_minutes=180, force=False) -> dict`
`monsoon.hydraulics.engine_info() -> dict`
Job IDs are an iterable. Each run uses pinned actual EPA SWMM via toolkit or PySWMM, isolated subprocess/private directory. Return run_id, status (succeeded|invalid|failed), valid bool, completed_jobs, scenario_id, engine_version, total_spill_m3, nodes dict keyed ID (spill_m3,max_depth_m,duration_above_threshold_min), diagnostics dict (continuity_error_percent,inflow_m3,outflow_m3,initial_storage_m3,final_storage_m3; extra terms as needed), files dict (input,report,output,manifest paths), cache_hit bool, timeseries list (minutes plus node depth columns prefixed depth_ and flow columns if useful), errors list. Invalid/failed runs must not have fabricated good scores. Reuse physical identical state/forcing independent of scenario label/durations. Agent adds hydraulic tests and evidence verification function/report if useful.

## Scheduler owned by planning implementation agent

`monsoon.planning.enumerate_queues(job_ids) -> list[tuple]`
`monsoon.planning.replay(queue,jobs,deadline_minutes,travel_minutes=10,actual_durations=None,already_completed=(),start_minute=0,start_location='DEPOT') -> dict`
Result: status (supported|unsupported), completed_jobs (newly completed), events list (job_id,depart_minute,start_minute,finish_minute,actual_minutes,max_minutes), finish_minute (including final return), crew_minutes, skipped list, reasons list. Prerequisite set includes already_completed. Start gate uses upper bound and required return; actual duration only revealed after selection. Retain/reconsider deferred jobs. Bounds violations unsupported, not favourable.

`monsoon.planning.evaluate_episode(case, scenarios, hydraulic_fn, deadline_minutes=180,already_completed=(),start_minute=0,start_location='DEPOT',operator_queue=None) -> dict`
Enumerate remaining job queues; hydrate achieved states union existing verified jobs. Same start rules all comparators. Return recommended plan dict or None; alternatives list; comparisons list (method,queue,scenario_id,total_spill_m3,status,completed_jobs,crew_minutes,run_id); plans list of dicts (id,queue,admissible,status,worst_spill_m3,mean_spill_m3,worst_crew_minutes,scenario_results,reasons); baseline definitions; counts. Per-location no-worsening versus no discretionary additions. Invalid required scenario makes whole plan unresolved. Operator baseline labelled user-entered, never expert unless supplied. Strong downstream-first, marginal hydraulic benefit per time, deterministic nominal, no additional work. Hindsight held separate diagnostic API if useful. Use lexicographic minimum-relative tie bands. Scheduler agent owns tests.

## Tickets owned by workflow implementation agent

`monsoon.tickets.TicketStore(db_path)` durable SQLite. Use a case/project state version and input fingerprint; plans/approvals immutable. APIs may be designed by agent then documented quickly for root UI. Need save/review/approve/assign/start/report_completion/verify/close; verified completion changes physical state exactly once and invalidates stale plans. Support failed verification and uncertain condition without falsely clearing; schema versioned events and traceable manifest. Track realised times/crew location for replanning. Validate actors, state transitions, times, prerequisite order, matching approved snapshot. Single-user research prototype has named actors, NOT production authentication. Agent owns ticket tests and API doc.

## Root ownership

Root owns app.py, application service/integration, CLI verification/report, README, dependencies, launcher, packaging, UI tests, and overall acceptance. Maintain current claim limits. No mock simulator substituted for EPA SWMM.
