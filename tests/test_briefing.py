"""Independent presentation/evidence regressions; no field validation claims."""
from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
import json
import sys
from types import SimpleNamespace

import pytest

from monsoon.briefing import render_briefing
from monsoon.tickets import TicketStore


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags, self.attributes, self.text = [], [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend((tag, key, value) for key, value in attrs)

    def handle_data(self, data):
        self.text.append(data)


def specimen():
    case = {"id": "example", "title": "Synthetic case", "model_version": "frozen-v1",
            "case_sha256": "frozen-model-hash", "source": "saved/reference_case.json",
            "protected_nodes": ["N"], "travel_minutes": 5, "epsilon_m3": 0.05,
            "jobs": [{"id": "J1", "asset_id": "DRAIN", "title": "Saved restoration scope",
                      "description": "Restore clear width", "nominal_minutes": 10,
                      "max_minutes": 20, "prerequisites": []}],
            "model_assumptions": ["Dry maintenance before prescribed inflow"]}
    inputs = {"case": deepcopy(case), "scenarios": [{"id": "P1", "title": "Selected forcing", "phase": "planning"}],
              "deadline_minutes": 50, "start_minute": 0, "start_location": "DEPOT", "already_completed": [],
              "implementation_hash": "saved-implementation", "engine": {"engine": "EPA SWMM", "engine_version": "5.2.4"}}
    result = {"scenario_id": "P1", "status": "supported", "total_spill_m3": 50, "crew_minutes": 20,
              "newly_completed_jobs": ["J1"], "completed_jobs": ["J1"], "run_id": "R-final",
              "replay": {"completed_jobs": ["J1"], "skipped": [],
                         "events": [{"job_id": "J1", "start_minute": 5, "finish_minute": 15, "actual_minutes": 10, "max_minutes": 20}]},
              "protected_violations": [], "reasons": []}
    plan = {"id": "Q-J1", "queue": ["J1"], "admissible": True, "supported": True, "status": "supported",
            "jobs": deepcopy(case["jobs"]), "deadline_minutes": 50, "travel_minutes": 5,
            "context_fingerprint": "input-123", "state_version": 1, "provenance": inputs,
            "model_version": "frozen-v1", "scenario_results": [result], "hydraulic_run_ids": ["R-final"]}
    episode = {"inputs": inputs, "recommended": deepcopy(plan), "plans": [deepcopy(plan)],
               "context_fingerprint": "input-123", "state_version": 1, "frozen_fingerprint": "decision-123",
               "comparisons": [{**deepcopy(result), "method_label": "Method A"}, {**deepcopy(result), "method_label": "Method B"}],
               "limitations": ["No field benefit established."]}
    return case, episode, plan


def saved_record(plan):
    digest = sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"id": "P-saved", "project_id": "example", "snapshot": deepcopy(plan), "snapshot_hash": digest,
            "state_version": plan["state_version"], "fingerprint": plan["context_fingerprint"], "status": "approved",
            "is_stale": False, "approval": {"snapshot_hash": digest, "actor": "Supervisor", "notes": "Synthetic review"}}


def audit_case(identifier, increase, *, completed=None, stage="prefix"):
    return {"scenario_id": identifier, "title": "Recorded stress", "status": "failed" if increase > .05 else "supported",
            "total_spill_m3": 50, "replay": {"completed_jobs": ["J1"], "crew_minutes": 20,
                                          "skipped": [{"job_id": "J2", "reason": "insufficient_bound_window"}]},
            "states": [{"stage": stage, "prefix_index": 1, "completed_jobs": completed or ["J1"], "run_id": "R-prefix",
                        "node_comparisons": [{"node_id": "N", "reference_spill_m3": 10, "spill_m3": 10 + increase,
                                              "increase_m3": increase, "tolerance_m3": .05, "passes": increase <= .05}]}]}


def test_portable_document_has_no_active_or_external_assets_and_escapes_every_surface():
    case, episode, plan = specimen()
    injected = '</td><script>alert("secret")</script><img src="https://evil.test/x" onerror="bad()"><a href="javascript:bad()">click</a>'
    plan["provenance"]["case"]["title"] = injected
    plan["jobs"][0]["description"] = injected
    plan["scenario_results"][0]["status"] = injected
    plan["scenario_results"][0]["reasons"] = [injected]
    plan["provenance"]["implementation_hash"] = injected
    record = saved_record(plan)
    record["approval"]["notes"] = injected
    workflow = {"project": {"id": "example"}, "tickets": [{"id": "T1", "job_id": "J1", "plan_id": "P-saved",
                "status": "completion_reported", "report_evidence": {"observation": injected}}],
                "events": [{"action": injected, "actor": injected, "payload": {"evidence": injected}}]}
    html = render_briefing(case, episode, record, workflow=workflow, generated_at=injected)
    document = Document(html)
    assert not set(document.tags) & {"script", "img", "a", "iframe", "object", "embed", "form", "link"}
    assert not any(key.startswith("on") or key in {"href", "src"} for _, key, _ in document.attributes)
    assert injected not in html
    assert injected in "".join(document.text)
    assert "Content-Security-Policy" in html
    assert "@media print" in html
    assert html.endswith("</body></html>")


def test_historical_scope_uses_saved_model_and_job_definitions_without_mutation():
    case, episode, plan = specimen()
    record = saved_record(plan)
    original = deepcopy((case, episode, record))
    case["title"] = "New unrelated model title"
    case["case_sha256"] = "new-model-hash"
    case["jobs"][0]["title"] = "Changed current job scope"
    actual_inputs = deepcopy((case, episode, record))
    html = render_briefing(case, episode, record)
    assert "Saved restoration scope" in html and "frozen-model-hash" in html
    assert "Changed current job scope" not in html and "new-model-hash" not in html
    assert "New unrelated model title" not in html
    assert (case, episode, record) == actual_inputs
    assert record == original[2]


def test_mismatched_episode_cannot_relabel_historical_comparisons():
    case, episode, plan = specimen()
    episode["context_fingerprint"] = "different-calculation"
    episode["comparisons"][0]["method_label"] = "Unrelated winning method"
    html = render_briefing(case, episode, saved_record(plan))
    assert "Unrelated winning method" not in html
    assert "comparisons were excluded" in html
    assert "Selected forcing" in html


def test_all_ties_losses_inadmissible_and_unresolved_comparisons_remain_visible():
    case, episode, plan = specimen()
    episode["comparisons"].extend([{**episode["comparisons"][0], "method_label": "Known loss", "total_spill_m3": 80},
                                  {**episode["comparisons"][0], "method_label": "Excluded low score", "status": "inadmissible", "total_spill_m3": 2},
                                  {**episode["comparisons"][0], "method_label": "Failed calculation", "status": "unresolved", "total_spill_m3": None}])
    html = render_briefing(case, episode, plan)
    for label in ["Method A", "Method B", "Known loss", "Excluded low score", "Failed calculation"]:
        assert label in html
    assert "80.000" in html and "2.000" in html and "Not resolved" in html
    assert "inadmissible" in html and "unresolved" in html
    assert "cannot override" in html


def test_forged_approval_hash_does_not_match_mutated_snapshot():
    case, episode, plan = specimen()
    record = saved_record(plan)
    record["snapshot"]["deadline_minutes"] = 500
    html = render_briefing(case, episode, record)
    assert "No matching recorded approval supplied" in html
    assert "Recorded approval of this snapshot" not in html


def test_no_audit_and_legacy_report_never_become_validated_passes():
    case, episode, plan = specimen()
    html = render_briefing(case, episode, plan)
    assert "No plan-specific stress audit was supplied" in html
    fake_pass = {"status": "passed", "approval_allowed": True, "protocol": {"id": "unbound"}}
    html = render_briefing(case, episode, plan, assurance=fake_pass)
    assert "A legacy approval is not an audit pass" in html
    assert "Validated finite stress audit: passed" not in html


def test_stale_audit_can_be_historically_valid_but_cannot_authorise_current_dispatch(monkeypatch):
    case, episode, plan = specimen()
    plan["assurance_requirement"] = {"schema_version": 1, "protocol_id": "test", "protocol_sha256": "123"}
    plan["assurance"] = {"status": "passed"}
    monkeypatch.setitem(sys.modules, "monsoon.assurance", SimpleNamespace(validate_audit=lambda _: {
        "valid": True, "status": "passed", "approval_allowed": True, "reasons": []}))
    workflow = {"project": {"id": "example", "version": 2, "context_fingerprint": "newer"}}
    html = render_briefing(case, episode, saved_record(plan), workflow=workflow)
    assert "Recorded approval; historical scope only" in html
    assert "cannot authorise further dispatch" in html
    assert "Historical / stale" in html


def test_worst_node_effect_retains_harmful_prefix_and_skipped_reason():
    case, episode, plan = specimen()
    report = {"status": "failed", "cases": [audit_case("S-harm", 40), audit_case("S-final", -8, stage="final")],
              "protocol": {"label": "Finite protocol", "evidence_class": "synthetic development stress"}}
    html = render_briefing(case, episode, plan, assurance=report)
    assert "Worst recorded protected-node effects" in html
    assert "S-harm" in html and "40.000" in html
    assert "J2: insufficient_bound_window" in html
    assert "harmful prefix whose final state later improves" in html


def test_actual_observations_remain_separate_from_planned_schedule_and_saved_bound(tmp_path):
    case, episode, plan = specimen()
    store = TicketStore(tmp_path / "workflow.sqlite3")
    try:
        store.ensure_project(case["id"], case["jobs"])
        state = store.set_context(case["id"], plan["context_fingerprint"], plan["provenance"])
        plan["state_version"] = state["version"]
        saved = store.save_plan(case["id"], plan)
        store.review(saved["id"], "Synthetic reviewer")
        store.approve(saved["id"], "Synthetic supervisor")
        ticket = store.create_ticket(saved["id"], "J1", "Dispatcher")
        store.assign(ticket["id"], "Crew A", "Dispatcher")
        store.start(ticket["id"], 5, "Crew A")
        store.report_completion(ticket["id"], 28, "Synthetic report; no field visit", "Crew A")
        store.verify(ticket["id"], True, "Synthetic verified restoration", "Inspector")
        store.close(ticket["id"], "Supervisor")
        workflow = store.export_manifest(case["id"])
        html = render_briefing(case, None, workflow["plans"][0], workflow=workflow)
    finally:
        store.disconnect()
    assert "Simulated start" in html and "Reported start" in html
    assert "duration bound exceeded" in html
    assert "23.0" in html and "28.0" in html and "20.0" in html
    assert "Synthetic report; no field visit" in html
    assert "verification_accepted" in html
    assert "Historical / stale" in html


def test_zero_work_plan_is_valid_content_and_not_a_missing_plan():
    case, episode, plan = specimen()
    plan["queue"] = []
    plan["scenario_results"][0]["newly_completed_jobs"] = []
    html = render_briefing(case, episode, plan)
    assert "Priority queue</dt><dd>None" in html
    assert "Synthetic research prototype" in html


def test_other_projects_work_cannot_be_mixed_into_export():
    case, episode, plan = specimen()
    with pytest.raises(ValueError, match="different project"):
        render_briefing(case, episode, saved_record(plan), workflow={"project": {"id": "other-project"}})


def test_missing_or_nonfinite_scores_are_not_silently_zero():
    case, episode, plan = specimen()
    plan["scenario_results"][0]["total_spill_m3"] = float("nan")
    plan["scenario_results"][0]["crew_minutes"] = None
    html = render_briefing(case, None, plan)
    assert "Not resolved" in html
    assert ">nan<" not in html


def test_no_recommendation_requires_an_explicit_plan():
    case, episode, _ = specimen()
    episode["recommended"] = None
    with pytest.raises(ValueError, match="evaluated or saved plan"):
        render_briefing(case, episode)
