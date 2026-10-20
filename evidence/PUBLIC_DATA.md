# Public evidence acquired on 13 October 2026

The project now has a separate public-source evidence packet. Every acquisition used an anonymous public HTTPS request: no account, access request, terms acceptance, or message to an organisation was needed. The files remain separate from the frozen reference model and assurance protocol. They do not establish field calibration or a maintenance benefit.

## What is available now

| Source | Downloaded material | Appropriate use and limits |
|---|---|---|
| METMalaysia through Malaysia’s official Open API | Seven exact Selangor state forecast records covering 13–19 October 2026 and four records from the national warning response. | Regional context and ingestion testing. Forecast phrases and temperatures are not rainfall intensities, inflow hydrographs, scenario probabilities, or an approved crew deadline. One “No Advisory” record has both validity fields missing; the saved response is not a live warning declaration. |
| JPS/DID Public Infobanjir | 246 published Selangor rainfall-table rows: daily accumulations for 7–12 October, accumulation since midnight on 13 October, and the latest one-hour accumulation. Raw page/response bytes, a CSV preserving cell text, and a quality summary are included. | Real reported observation data for acquisition and quality checking. This is one public snapshot, not a complete event hyetograph or calibrated catchment record. Selangor was an illustrative public-data selection; no pilot catchment was selected. |
| US EPA dynamic-wave QA package | Original archive with 20 test packages, 20 SWMM input files in total, and historical comparison data; hash inventory and the unchanged EXTRAN1 inputs extracted. | An external software-comparison resource. The unchanged EXTRAN1 input is incompatible with the installed 5.2.4 engine’s input grammar: its legacy `NORMAL_FLOW_LIMITED NO` setting produces ERROR 205. The native failure and input remain preserved. No implicit compatibility patch or favourable result was substituted. |
| US EPA application examples | Original manual/data archive, an inventory of 13 input files, and the unchanged Example 2 surface-drainage input. | An external example that can run on the installed engine. It uses kinematic-wave routing and US customary units, so it is not evidence validating the prototype’s dynamic-wave intervention model. |

Sources: [MET API documentation](https://developer.data.gov.my/realtime-api/weather), [official API access guide](https://developer.data.gov.my/quickstart), [JPS Selangor rainfall page](https://publicinfobanjir.water.gov.my/hujan/data-hujan/?state=SEL&lang=en), and the [EPA SWMM download catalogue](https://www.epa.gov/water-research/storm-water-management-model-swmm). EPA’s [QA report](https://nepis.epa.gov/Exe/ZyPDF.cgi?Dockey=P10089TF.PDF) describes the old-versus-new model comparison data; those data are not Malaysian measurements.

## JPS quality findings and units

The captured table contains **86 rows without a station ID**, **five duplicated nonempty station IDs**, and **11 nonnumeric rainfall cells**. Some paired IDs identify F2/non-F2 versions; others name different stations. The import preserves all rows and flags the ambiguity. It does not merge stations, substitute zero for missing values, or choose an undocumented ID interpretation.

All rainfall value columns are accumulated depth in **mm**. The last-one-hour column is a depth over that window; it is not an instantaneous rate. The six daily totals cannot supply a within-event rainfall pattern. The published update stamps range from 03:15 to 22:45 on 13 October 2026, so the table is not a synchronous network observation. Timestamps are retained exactly as published because the captured response does not specify their offset.

The raw response has irregular HTML row closures. Parsing uses the explicit source row-number cells, requires 13 cells per row and the six dated headers, and checks unique source row numbers. Missing and duplicated station identifiers remain visible in [the quality summary](../data/public_evidence/jps/summary.json). The [CSV snapshot](../data/public_evidence/jps/jps_selangor_rainfall_snapshot.csv) contains exact published cell text, including missing-value markers. The HTML is stored as inert `.html.txt` source so opening the evidence does not execute third-party page scripts.

These observations would require station metadata, calibration/QC information, matching measurement intervals and a justified relationship to the chosen catchment before hydraulic use. Rainfall depth cannot be assigned directly to the existing model’s prescribed flow inputs, which are in m³/s.

## External engine check

The unmodified EPA `Example2-Post.inp` completed on the installed EPA SWMM 5.2.4 engine. It retains the supplied 15-second routing step, 12-hour horizon, kinematic-wave routing and native CFS/feet units. Its report records runoff continuity error **−0.077%** and routing continuity error **−0.034%**. This is a compatibility smoke check, with no acceptance threshold selected from its result. It does not constitute calibration, an independent engine comparison, or a planner advantage.

The [successful example manifest](../data/public_evidence/epa/application_example2_run/run_manifest.json) records the engine identity and input/report/output checksums. The [historical QA failure manifest](../data/public_evidence/epa/extran1_run/run_manifest.json) and native report preserve the unsuccessful unchanged EXTRAN1 attempt. Both outcomes remain part of the packet. The two original EPA archives and their member inventories permit later, separately specified benchmark work without changing the reference case.

## Provenance and reuse

- [JPS/EPA acquisition manifest](../data/public_evidence/manifest-jps-epa.json): source URLs, publishers, retrieval timestamps, file sizes, SHA-256 checksums, units, transformations and access limitations.
- [MET acquisition manifest](../data/public_evidence/met/met_manifest.json): exact query, region, dates, response metadata, checksums and missing warning-validity fields. An initial partial district query is preserved separately as provenance; the final display uses the exact state query.
- [EPA QA member inventory](../data/public_evidence/epa/archive_inventory.json) and [application-example inventory](../data/public_evidence/epa/application_inventory.json): original archive and model-member hashes.

These are publicly readable downloads. No dataset-specific unrestricted redistribution licence was established for the JPS/MET responses or every user-contributed EPA QA input. The packet retains source attribution and states that limitation; public access is not represented as a blanket reuse licence. No claim of agency endorsement is made. Confirm the relevant dataset terms before public redistribution or commercial use. The [EPA disclaimer page](https://www.epa.gov/web-policies-and-procedures/epa-disclaimers) itself cautions that individual documents may have different conditions.

## What still needs site access or another decision

1. Select the pilot site and obtain maintenance/model-use authority from its owner.
2. Obtain surveyed drainage connectivity and geometry, levels/datum, outfall boundary records, asset condition and authorised intervention descriptions.
3. Obtain quality-controlled interval rainfall and paired flow/level observations for that site, with sensor metadata and timestamps.
4. Collect operator-reviewed job-duration, travel/access and maintenance-baseline evidence; measure restored geometry or hydraulic response.
5. Freeze a separate site validation protocol before calibration/evaluation and prospective shadow use.

Those records cannot be recovered from the downloaded regional weather table or by interpreting a tutorial catchment as the user’s site. This packet makes the available evidence concrete while keeping those remaining requests explicit.
