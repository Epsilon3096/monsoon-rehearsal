"""Portable, inert HTML briefings from evaluated plans and coherent workflow exports.

This module formats supplied evidence; it never runs a model, selects a policy,
changes approval, or treats a missing result as a successful zero. All supplied
content is escaped and no scripts, remote assets, or executable links are used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math


_CSS = """
:root{color-scheme:light;font-family:Arial,Helvetica,sans-serif;color:#172b35;background:#e9eff1}
*{box-sizing:border-box}body{margin:0;padding:28px}main{max-width:1180px;margin:auto;background:white;padding:36px 42px;box-shadow:0 8px 35px #172b3518}
header{border-top:7px solid #126a70;padding-top:20px;margin-bottom:24px}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#126a70;font-weight:bold}
h1{font-size:32px;line-height:1.1;margin:10px 0 14px}h2{font-size:21px;line-height:1.2;margin:28px 0 12px;border-bottom:1px solid #bdcdd1;padding-bottom:8px}h3{font-size:16px;margin:20px 0 8px}
p,li{font-size:13px;line-height:1.55}p{margin:8px 0}.muted{color:#566b74}.notice{background:#edf7f7;border-left:4px solid #126a70;padding:13px 17px;margin:16px 0}.warning{background:#fff4e9;border-color:#ab5e17}
table{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 18px;table-layout:auto}th,td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #dce5e7;overflow-wrap:anywhere}th{font-size:11px;color:#304d58;background:#edf3f4;overflow-wrap:normal}tr:nth-child(even) td{background:#f8fafb}caption{text-align:left;font-weight:bold;margin-bottom:8px}
.status{font-size:11px;font-weight:bold;white-space:normal}.good{color:#10694f}.bad{color:#9d3428}.neutral{color:#546570}.mono{font-family:Consolas,monospace;font-size:11px;overflow-wrap:anywhere;white-space:pre-wrap}dl{display:grid;grid-template-columns:180px 1fr;gap:8px 18px;font-size:12px}dt{font-weight:bold;color:#3c5661}dd{margin:0;overflow-wrap:anywhere}footer{border-top:1px solid #bdcdd1;margin-top:30px;padding-top:12px}ul{padding-left:21px}.nowrap{white-space:nowrap}
@page{size:A4;margin:14mm} @media print{body{background:white;padding:0}main{padding:0;box-shadow:none;max-width:none}h1{font-size:26px}h2{break-after:avoid}h3{break-after:avoid}thead{display:table-header-group}tr{break-inside:avoid}table{font-size:9px}th{font-size:9px}th,td{padding:5px}p,li{font-size:10px}.notice{break-inside:avoid}header{margin-bottom:18px}dl{font-size:10px;grid-template-columns:145px 1fr}.mono{font-size:9px}}
"""


def _text(value, missing="Not recorded"):
    if value is None or value == "":
        return missing
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _esc(value, missing="Not recorded"):
    return escape(_text(value, missing), quote=True)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value, places=3):
    return f"{value:,.{places}f}" if _finite(value) else "Not resolved"


def _jobs(value):
    return " → ".join(str(item) for item in value) if isinstance(value, (list, tuple)) and value else "None"


def _state_jobs(value):
    return ", ".join(str(item) for item in value) if isinstance(value, (list, tuple)) and value else "None"


def _status(value):
    name = _text(value, "not recorded")
    css = "good" if name in {"supported", "passed", "verified", "closed"} else (
        "bad" if name in {"failed", "inadmissible", "unresolved", "blocked", "revision_needed"} else "neutral")
    return f'<span class="status {css}">{_esc(name.replace("_", " "))}</span>'


def _table(headers, rows, *, html_columns=()):
    """Only internally rendered status cells may bypass escaping."""
    if not rows:
        return '<p class="muted">No records supplied.</p>'
    head = "".join(f"<th scope=\"col\">{_esc(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{item if index in html_columns else _esc(item)}</td>"
                                   for index, item in enumerate(row)) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _facts(items):
    return "<dl>" + "".join(f"<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>" for label, value in items) + "</dl>"


def _list(items):
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>" if items else ""


def _scenario_table(results, definitions):
    rows = []
    for row in results:
        replay = row.get("replay") or {}
        definition = definitions.get(row.get("scenario_id"), {})
        skipped = "; ".join(f"{item.get('job_id', '?')}: {item.get('reason', 'reason not recorded')}"
                            + (f" (requires {_jobs(item['missing_prerequisites'])})" if item.get("missing_prerequisites") else "")
                            for item in replay.get("skipped", [])) or "None recorded"
        rows.append([row.get("scenario_id"), definition.get("title", row.get("title")), _status(row.get("status")),
                     _jobs(row.get("newly_completed_jobs", replay.get("completed_jobs", []))),
                     _number(row.get("total_spill_m3")), _number(row.get("crew_minutes", replay.get("crew_minutes")), 1),
                     skipped, "; ".join(row.get("reasons", [])) or "None recorded"])
    return _table(["Scenario", "Definition", "Status", "Simulated new work", "Total spill (m³)",
                   "Crew time (min)", "Skipped jobs", "Reasons"], rows, html_columns=(2,))


def _audit_gate(snapshot, report):
    if not report:
        return {"valid": False, "approval_allowed": False, "status": "not_recorded",
                "reasons": ["No plan-specific stress audit was supplied."]}
    if not snapshot.get("assurance_requirement"):
        return {"valid": False, "approval_allowed": False, "status": "unverified",
                "reasons": ["This snapshot does not declare a bound stress-audit requirement. A legacy approval is not an audit pass."]}
    try:
        from monsoon.assurance import validate_audit
        candidate = dict(snapshot, assurance=report)
        return validate_audit(candidate)
    except (ImportError, ValueError, TypeError, KeyError) as exc:
        return {"valid": False, "approval_allowed": False, "status": "unverified",
                "reasons": [f"Audit binding could not be validated: {exc}"]}


def _same_episode(snapshot, episode):
    if not episode:
        return False
    if snapshot.get("context_fingerprint") is not None:
        return (snapshot.get("context_fingerprint") == episode.get("context_fingerprint")
                and snapshot.get("state_version") == episode.get("state_version"))
    return any(snapshot == candidate for candidate in episode.get("plans", [])) or snapshot == episode.get("recommended")


def render_briefing(case: dict, episode: dict | None = None, plan: dict | None = None, *,
                    workflow: dict | None = None, assurance: dict | None = None,
                    generated_at: str | None = None) -> str:
    """Return a complete, printable HTML plan/ticket briefing.

    ``plan`` is an evaluated plan, service plan snapshot, or ``get_plan`` record;
    omit it to use ``episode['recommended']``. ``workflow`` is the unmodified
    coherent ``TicketStore.export_manifest`` dictionary. Historical model/job
    definitions come from the saved snapshot, never the current inventory.
    Optional ``assurance`` is a recorded report, not an approval instruction.
    Missing provenance or evidence remains explicitly missing. No inputs mutate.
    """
    if not isinstance(case, dict):
        raise ValueError("A case dictionary is required.")
    episode, workflow = episode or {}, workflow or {}
    chosen = plan if plan is not None else episode.get("recommended")
    if not isinstance(chosen, dict):
        raise ValueError("An evaluated or saved plan is required for a briefing.")
    record = chosen if isinstance(chosen.get("snapshot"), dict) else {}
    snapshot = dict(record.get("snapshot", chosen))
    episode_matches = _same_episode(snapshot, episode)
    inputs = snapshot.get("context_inputs") or snapshot.get("provenance") or (episode.get("inputs", {}) if episode_matches else {})
    source_case = inputs.get("case") or case
    jobs = snapshot.get("jobs") or source_case.get("jobs", [])
    by_job = {job["id"]: job for job in jobs}
    if episode_matches:
        # This also accepts a raw evaluated plan for preview. Saved snapshots
        # remain authoritative and are never filled from a different episode.
        defaults = {"context_fingerprint": episode.get("context_fingerprint"), "state_version": episode.get("state_version"),
                    "provenance": inputs, "deadline_minutes": inputs.get("deadline_minutes"),
                    "travel_minutes": source_case.get("travel_minutes"), "jobs": jobs,
                    "model_version": source_case.get("model_version"),
                    "decision_manifest": episode.get("decision_manifest"), "frozen_fingerprint": episode.get("frozen_fingerprint")}
        snapshot = {**defaults, **snapshot}
    report = assurance if assurance is not None else snapshot.get("assurance")
    gate = _audit_gate(snapshot, report)
    report = report or {}
    protocol = report.get("protocol") or {}
    state = workflow.get("project") or {}
    workflow_matches = not state or state.get("id") == (record.get("project_id") or source_case.get("id"))
    if not workflow_matches:
        raise ValueError("Workflow export belongs to a different project.")
    stale = bool(record.get("is_stale"))
    if state and snapshot.get("state_version") is not None:
        stale = stale or (state.get("version") != snapshot.get("state_version")
                          or state.get("context_fingerprint") != snapshot.get("context_fingerprint"))
    approval = record.get("approval") or {}
    actual_snapshot_hash = (hashlib.sha256(json.dumps(record["snapshot"], sort_keys=True, separators=(",", ":"),
                                                    allow_nan=False).encode()).hexdigest() if record else None)
    approval_matches = bool(approval.get("snapshot_hash") and approval.get("snapshot_hash") == record.get("snapshot_hash") == actual_snapshot_hash)
    approval_label = ("Recorded approval; historical scope only" if stale else "Recorded approval of this snapshot") if approval_matches else "No matching recorded approval supplied"
    current_label = "Historical / stale; further dispatch requires current approval" if stale else (
        "Saved plan; currentness checked against supplied workflow" if state and record else "Currentness not established by this export")
    stamp = generated_at if generated_at is not None else datetime.now(timezone.utc).isoformat()
    title = source_case.get("title", "Monsoon Rehearsal")
    parts = [f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             f"<title>{_esc(title)} — plan briefing</title><style>{_CSS}</style></head><body><main>",
             '<header><div class="eyebrow">Monsoon Rehearsal / portable evidence</div><h1>Plan &amp; work briefing</h1>',
             f"<p>{_esc(title)}</p><p class=\"muted\">Exported {_esc(stamp)}. Use the browser’s Print command to print or save as PDF.</p></header>",
             '<div class="notice warning"><strong>Synthetic research prototype — no field validation.</strong><p>These are finite-scenario model calculations and local research workflow records. A supported or passed result is not a field-safety clearance, calibrated flood forecast, property-loss estimate, or permission to perform real maintenance.</p></div>',
             "<h2>Decision and scope</h2>",
             _facts([("Plan record", record.get("id", "Unsaved evaluated plan")), ("Planning result", snapshot.get("status")),
                     ("Priority queue", _jobs(snapshot.get("queue", []))), ("Approval", approval_label),
                     ("Currency", current_label), ("Deadline after shift start", _number(snapshot.get("deadline_minutes", inputs.get("deadline_minutes")), 1) + " min"),
                     ("Initial crew clock / location", _number(inputs.get("start_minute", (snapshot.get("observed_state") or {}).get("elapsed_minutes")), 1) + " min / " + _text(inputs.get("start_location", (snapshot.get("observed_state") or {}).get("crew_location")))),
                     ("Previously verified jobs", _state_jobs(inputs.get("already_completed", (snapshot.get("observed_state") or {}).get("completed_jobs", [])))),
                     ("Uniform travel per move", _number(snapshot.get("travel_minutes", source_case.get("travel_minutes")), 1) + " min")]),
             "<p>The queue is a priority rule. Only an eligible job whose upper duration bound, travel and required return fit may start. A listed job is not a promise of completion. All clock values below are minutes after shift start; the hydraulic event is a separate simulated period.</p>"]
    job_rows = []
    for position, identifier in enumerate(snapshot.get("queue", []), 1):
        job = by_job.get(identifier, {})
        job_rows.append([position, identifier, job.get("title"), job.get("asset_id"), job.get("description"),
                         _number(job.get("nominal_minutes"), 1), _number(job.get("max_minutes"), 1), _jobs(job.get("prerequisites", []))])
    parts.append(_table(["Priority", "Job", "Scope", "Asset", "Physical intervention", "Nominal min", "Upper min", "Prerequisites"], job_rows))
    parts.append(_facts([("Review actor / time", _text((record.get("review") or {}).get("actor")) + " / " + _text((record.get("review") or {}).get("created_at"))),
                         ("Review notes", (record.get("review") or {}).get("notes")),
                         ("Approval actor / time", _text(approval.get("actor")) + " / " + _text(approval.get("created_at"))),
                         ("Approval notes", approval.get("notes")), ("Approved snapshot SHA-256", approval.get("snapshot_hash"))]))
    parts.append("<h2>Selected planning scenarios</h2><p>Every supplied planning outcome remains visible, including unresolved and inadmissible results. Spill is collector-boundary overflow in m³, not mapped street or property flooding.</p>")
    definitions = {row["id"]: row for row in inputs.get("scenarios", [])}
    results = snapshot.get("scenario_results", [])
    parts.append(_scenario_table(results, definitions))
    schedules = []
    for result in results:
        for event in (result.get("replay") or {}).get("events", []):
            schedules.append([result.get("scenario_id"), event.get("job_id"), _number(event.get("start_minute"), 1),
                              _number(event.get("finish_minute"), 1), _number(event.get("actual_minutes"), 1), _number(event.get("max_minutes"), 1)])
    parts.extend(["<h3>Predicted on-site schedule</h3><p>These duration realisations belong to synthetic scenarios. They are separate from reported work observations.</p>",
                  _table(["Scenario", "Job", "Simulated start", "Simulated finish", "Simulated duration", "Declared bound"], schedules)])
    violations = [row for result in results for row in result.get("protected_violations", [])]
    if violations:
        parts.extend(["<h3>Planning protection failures, including intermediate stops</h3>",
                      _table(["Scenario", "Completed state", "Protected node", "Reference m³", "State m³", "Increase m³", "Tolerance m³"],
                             [[v.get("scenario_id"), _state_jobs(v.get("completed_jobs", [])), v.get("node_id"), _number(v.get("reference_spill_m3")),
                               _number(v.get("spill_m3")), _number(v.get("increase_m3")), _number(v.get("tolerance_m3"))] for v in violations])])
    parts.append("<h2>Plan-specific stress audit</h2>")
    gate_text = "Validated finite stress audit: " + _text(gate.get("status")) if gate.get("valid") else "Audit evidence is not validated for this plan"
    if stale:
        gate_text += ". This plan is historical; this audit cannot authorise further dispatch."
    parts.append(f'<div class="notice{ " warning" if stale or not gate.get("approval_allowed") else ""}"><strong>{_esc(gate_text)}</strong>' + _list(gate.get("reasons", [])) + "</div>")
    parts.append(_facts([("Recorded audit status", report.get("status", "Not recorded")), ("Protocol", protocol.get("label", protocol.get("id"))),
                         ("Evidence class", protocol.get("evidence_class")), ("Protocol SHA-256", protocol.get("sha256")),
                         ("Audit subject SHA-256", report.get("subject_sha256")), ("Audit identifier", report.get("audit_id", report.get("audit_sha256")))]))
    parts.append("<p>The audit tests only its declared finite cases and achieved dry-work stopping states. Previously revealed holdouts are development stress cases when reused. Passing does not establish robustness to untested states, forecast probabilities, field conditions, or a policy advantage.</p>")
    cases = report.get("cases", [])
    parts.append(_scenario_table(cases, {item.get("scenario_id"): item for item in cases}))
    parts.append(_list(protocol.get("limitations", [])))
    worst = {}
    for item in cases:
        for stopping in item.get("states", []):
            for effect in stopping.get("node_comparisons", []):
                node, increase = effect.get("node_id"), effect.get("increase_m3")
                if node is not None and _finite(increase) and (node not in worst or increase > worst[node][0]["increase_m3"]):
                    worst[node] = (effect, item, stopping)
    if worst:
        parts.append("<h3>Worst recorded protected-node effects across stress stopping states</h3><p>Positive change means more spill than no additional discretionary work under matching forcing. The largest recorded increase is retained for each node, including a harmful prefix whose final state later improves.</p>")
        rows = []
        for node, (effect, item, stopping) in sorted(worst.items(), key=lambda pair: str(pair[0])):
            screen = ("unresolved" if stopping.get("status") == "unresolved" or effect.get("gate_stable") is False else
                      "passed" if effect.get("passes") is True else "failed" if effect.get("passes") is False else "unresolved")
            rows.append([node, item.get("scenario_id"), f"{stopping.get('stage', 'state')} {stopping.get('prefix_index', '')}: {_state_jobs(stopping.get('completed_jobs', []))}",
                         _number(effect.get("reference_spill_m3")), _number(effect.get("spill_m3")), _number(effect.get("increase_m3")),
                         _number(effect.get("tolerance_m3")), _status(screen)])
        parts.append(_table(["Protected node", "Stress case", "Stopping state", "Reference m³", "State m³", "Change m³", "Tolerance m³", "Screen"], rows, html_columns=(7,)))
    else:
        parts.append('<p class="muted">No complete stress node-effect records supplied. Missing node effects are not zero and do not establish a pass.</p>')
    if episode_matches:
        parts.extend(["<h2>Baseline comparison record</h2><p>All supplied comparison rows are retained. Tied or worse results remain results. A lower total spill cannot override an inadmissible protected-location outcome. The unweighted scenario mean is not an expected annual loss.</p>",
                      _table(["Method", "Scenario", "Status", "Total spill m³", "Crew min", "Completed state"],
                             [[row.get("method_label", row.get("method")), row.get("scenario_id"), _status(row.get("status")), _number(row.get("total_spill_m3")),
                               _number(row.get("crew_minutes"), 1), _state_jobs(row.get("completed_jobs", []))] for row in episode.get("comparisons", [])], html_columns=(2,))])
    elif episode:
        parts.append('<div class="notice warning">The supplied episode does not match this saved plan’s input fingerprint and revision. Its comparisons were excluded to avoid mixing calculation histories.</div>')
    parts.append("<h2>Reported work and verified condition</h2><p>Reported completion is not hydraulic restoration. Only accepted verification changes the represented physical state. These local records may contain explicitly synthetic test observations; named actors are audit labels, not authenticated identities.</p>")
    parts.append(_facts([("Workflow export time", workflow.get("exported_at")), ("Current project revision", state.get("version")),
                         ("Observed crew clock / location", _number(state.get("elapsed_minutes"), 1) + " min / " + _text(state.get("crew_location"))),
                         ("Currently accepted jobs", _state_jobs(state.get("completed_jobs", []))), ("Unresolved condition", _state_jobs(state.get("unresolved_jobs", [])))]))
    tickets = workflow.get("tickets", [])
    history_plans = {item.get("id"): item for item in workflow.get("plans", [])}
    if record:
        history_plans.setdefault(record.get("id"), record)
    ticket_rows = []
    for ticket in tickets:
        historical = (history_plans.get(ticket.get("plan_id")) or {}).get("snapshot", {})
        saved_job = next((job for job in historical.get("jobs", []) if job.get("id") == ticket.get("job_id")), {})
        exceptions = [name.replace("_", " ") for name in ("duration_bound_exceeded", "deadline_including_return_exceeded") if ticket.get(name) is True]
        ticket_rows.append([ticket.get("id"), ticket.get("plan_id"), ticket.get("job_id"), _status(ticket.get("status")), ticket.get("crew"),
                            _number(ticket.get("start_minute"), 1), _number(ticket.get("finish_minute"), 1), _number(ticket.get("actual_minutes"), 1),
                            _number(saved_job.get("max_minutes"), 1), ticket.get("observed_condition"), "; ".join(exceptions) or "None recorded"])
    parts.append(_table(["Ticket", "Historical plan", "Job", "Status", "Crew", "Reported start", "Reported finish", "Actual min", "Saved bound min", "Condition", "Exceptions"], ticket_rows, html_columns=(3,)))
    for ticket in tickets:
        parts.append(f"<h3>Ticket {_esc(ticket.get('id'))}: evidence</h3>" + _facts([
            ("Approved snapshot SHA-256", ticket.get("snapshot_hash")), ("Completion report", ticket.get("report_evidence")),
            ("Verification record", ticket.get("verification_evidence"))]))
    event_rows = []
    for event in workflow.get("events", []):
        payload = event.get("payload") or {}
        # Context-change events contain the whole model. The compact event
        # ledger points to its fingerprint; it never rewrites historical scope.
        detail = {key: value for key, value in payload.items() if key not in {"inputs", "jobs"}}
        event_rows.append([event.get("sequence"), event.get("created_at"), event.get("entity_id"), event.get("action"), event.get("actor"), detail or "—"])
    if event_rows:
        parts.extend(["<h3>Workflow event ledger</h3>", _table(["Sequence", "Recorded at (UTC)", "Entity", "Action", "Actor", "Recorded detail"], event_rows)])
    engine = inputs.get("engine") or {}
    manifest = snapshot.get("decision_manifest") or (episode.get("decision_manifest", {}) if episode_matches else {})
    parts.extend(["<h2>Model and calculation provenance</h2>", _facts([
        ("Case ID / model version", _text(source_case.get("id")) + " / " + _text(snapshot.get("model_version", source_case.get("model_version")))),
        ("Model source", source_case.get("source", "data/reference_case.json — frozen synthetic reference" if source_case.get("id") == "synthetic-two-branch-v1" else "Source path not recorded")),
        ("Model file SHA-256", source_case.get("case_sha256")), ("Application version", inputs.get("app_version")),
        ("Implementation SHA-256", inputs.get("implementation_hash")), ("Planner source SHA-256", manifest.get("planner_source_sha256")),
        ("Engine / toolkit", _text(engine.get("engine")) + " " + _text(engine.get("engine_version")) + " / " + _text(engine.get("toolkit_version"))),
        ("Hydraulic adapter SHA-256", engine.get("adapter_sha256")), ("Calculation input fingerprint", snapshot.get("context_fingerprint")),
        ("Calculation state revision", snapshot.get("state_version")), ("Frozen decision fingerprint", snapshot.get("frozen_fingerprint")),
        ("Saved snapshot SHA-256", record.get("snapshot_hash")), ("Numerical routing step", _text(engine.get("default_routing_step_s")) + " s")]),
        "<h3>Hydraulic evidence identities</h3>"])
    run_ids = set(snapshot.get("hydraulic_run_ids", []))
    for item in list(results) + list(cases):
        if item.get("run_id"):
            run_ids.add(item["run_id"])
        if (item.get("baseline") or {}).get("run_id"):
            run_ids.add(item["baseline"]["run_id"])
        run_ids.update(stopping["run_id"] for stopping in item.get("states", item.get("intermediate_states", [])) if stopping.get("run_id"))
    parts.append('<p class="mono">' + _esc("\n".join(sorted(str(identifier) for identifier in run_ids)), "No run identities supplied") + "</p>")
    parts.extend(["<h3>Declared model limits</h3>", _list(source_case.get("model_assumptions", [])),
                  _list(episode.get("limitations", []) if episode_matches else []),
                  '<footer><p class="muted">This portable briefing is a readable copy of supplied records. It does not authenticate their authors, embed the native hydraulic files, refresh observations, or grant field authority. Preserve the associated JSON and native input/report/output evidence for reproduction.</p></footer></main></body></html>'])
    return "".join(parts)
