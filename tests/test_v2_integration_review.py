"""Independent v0.2 boundary review: source, state, selection and UI binding.

Arithmetic hydraulic fixtures and stub audit payloads below exercise software
contracts only. They are explicitly not SWMM or field-effectiveness evidence.
"""
from copy import deepcopy
import json

import pytest

from monsoon import assurance, service
from monsoon.tickets import TicketStore
from test_assurance import _plain, arithmetic_checked_callback, make_assurance_fixture


@pytest.fixture
def ready(tmp_path, monkeypatch):
    case, store = service.initialise(tmp_path)
    scenarios = [deepcopy(next(s for s in case["scenarios"] if s["id"] == "P1"))]
    frozen_case = deepcopy(case)
    monkeypatch.setattr(service, "run_state", lambda state, scenario, *args, **kwargs:
                        _plain(frozen_case, state, scenario))
    try:
        yield case, scenarios, store, tmp_path
    finally:
        store.disconnect()


def _episode(ready):
    case, scenarios, store, root = ready
    episode = service.rehearse(case, scenarios, 180, store, root)
    return episode, episode["recommended"]


def _audit_double(*args, **kwargs):
    # A payload for orchestration refusal tests; it is never a valid audit.
    return {"origin": "ORCHESTRATION UNIT TEST DOUBLE; NOT AUDIT EVIDENCE"}


def test_rehearsal_runtime_change_is_not_published(ready, monkeypatch):
    case, scenarios, store, root = ready
    identities = iter(("before", "changed-during-rehearsal"))
    monkeypatch.setattr(service, "runtime_identity", lambda: next(identities))
    with pytest.raises(ValueError, match="changed during rehearsal"):
        service.rehearse(case, scenarios, 180, store, root)
    assert not list((root / "episodes").glob("*.json"))


def test_audit_runtime_change_is_not_published(ready, monkeypatch):
    case, _, store, root = ready
    episode, plan = _episode(ready)
    identities = iter(("before", "changed-during-audit"))
    monkeypatch.setattr(service, "runtime_identity", lambda: next(identities))
    monkeypatch.setattr(service, "audit_plan", _audit_double)
    with pytest.raises(ValueError, match="changed during the stress audit"):
        service.audit_selected_plan(case, episode, plan, store, root)
    assert not list((root / "audits").glob("*.json"))


@pytest.mark.parametrize("change", ("clock", "context"))
def test_audit_rejects_concurrent_observation_or_context_commit(ready, monkeypatch, change):
    case, _, store, root = ready
    episode, plan = _episode(ready)
    second = TicketStore(store.db_path)

    def change_during_audit(*args, **kwargs):
        if change == "clock":
            second.record_delay(case["id"], 1, "Independent test", "Concurrent clock observation")
        else:
            second.set_context(case["id"], "changed-context", {"origin": "independent race test"})
        return _audit_double()

    monkeypatch.setattr(service, "audit_plan", change_during_audit)
    try:
        with pytest.raises(ValueError, match="changed during the stress audit"):
            service.audit_selected_plan(case, episode, plan, store, root)
        assert not list((root / "audits").glob("*.json"))
    finally:
        second.disconnect()


@pytest.mark.parametrize("operation", ("rehearse", "audit"))
def test_stale_case_argument_is_rejected_before_calculation(ready, monkeypatch, operation):
    case, scenarios, store, root = ready
    episode, plan = _episode(ready)
    live_case = deepcopy(case)
    live_case["model_version"] = "changed-after-initialise"
    monkeypatch.setattr(service, "load_case", lambda: deepcopy(live_case))
    calls = []
    monkeypatch.setattr(service, "evaluate_episode", lambda *args, **kwargs: calls.append("rehearsal"))
    monkeypatch.setattr(service, "audit_plan", lambda *args, **kwargs: calls.append("audit"))
    with pytest.raises(ValueError, match="(?i)case|model"):
        if operation == "rehearse":
            service.rehearse(case, scenarios, 180, store, root)
        else:
            service.audit_selected_plan(case, episode, plan, store, root)
    assert calls == []
    assert not list((root / "audits").glob("*.json"))


def test_rehearsal_freezes_caller_owned_case_scenarios_and_queue(ready):
    case, scenarios, store, root = ready
    original_case, original_scenarios = deepcopy(case), deepcopy(scenarios)
    queue = ["J2", "J3"]
    invoked = False

    def mutate_callers(*args):
        nonlocal invoked
        if not invoked:
            invoked = True
            case["model_version"] = "externally-mutated"
            case["jobs"][0]["max_minutes"] = 1
            scenarios[0]["hydraulic"]["peak_a_cms"] = 1000
            queue[:] = ["J4"]

    episode = service.rehearse(case, scenarios, 180, store, root,
                               operator_queue=queue, progress=mutate_callers)
    assert invoked
    assert episode["inputs"]["case"]["model_version"] == original_case["model_version"]
    assert episode["inputs"]["case"]["jobs"] == original_case["jobs"]
    assert episode["inputs"]["scenarios"] == original_scenarios
    assert episode["inputs"]["operator_queue"] == ["J2", "J3"]
    assert service.canonical_hash(episode["inputs"]) == episode["context_fingerprint"]
    persisted = json.loads((root / "episodes" / f'{episode["context_fingerprint"]}.json').read_text())
    assert persisted["inputs"] == episode["inputs"]


def test_context_does_not_share_mutable_caller_data(ready):
    case, scenarios, store, _ = ready
    inputs = service.context(case, scenarios, 180, store.project_state(case["id"]))
    original = deepcopy(inputs)
    case["jobs"][0]["title"] = "Changed after context capture"
    scenarios[0]["durations"]["J1"] = 1
    assert inputs == original


def test_selected_plan_change_is_rejected_before_any_audit_callback(ready, monkeypatch):
    case, _, store, root = ready
    episode, plan = _episode(ready)
    altered = deepcopy(plan)
    altered["scenario_results"][0]["total_spill_m3"] = 0
    calls = []
    monkeypatch.setattr(service, "audit_plan", lambda *args, **kwargs: calls.append("called"))
    with pytest.raises(ValueError, match="does not match its frozen rehearsal"):
        service.audit_selected_plan(case, episode, altered, store, root)
    assert calls == []
    assert not list((root / "audits").glob("*.json"))


def test_audit_freezes_caller_owned_episode_and_plan(ready, monkeypatch):
    case, _, store, root = ready
    episode, plan = _episode(ready)
    expected_case, expected_episode, expected_plan = deepcopy(case), deepcopy(episode), deepcopy(plan)

    def inspect_isolation(frozen_case, frozen_episode, frozen_plan, *args, **kwargs):
        case["model_version"] = "changed-outside-service"
        episode["inputs"]["scenarios"][0]["hydraulic"]["peak_a_cms"] = 1000
        plan["queue"].reverse()
        assert frozen_case == expected_case
        assert frozen_episode == expected_episode
        assert frozen_plan == expected_plan
        return _audit_double()

    monkeypatch.setattr(service, "audit_plan", inspect_isolation)
    assert service.audit_selected_plan(case, episode, plan, store, root) == _audit_double()


def test_valid_raw_run_for_wrong_restored_state_cannot_pass(tmp_path):
    case, episode, plan, snapshot, _ = make_assurance_fixture(tmp_path / "original")
    callback = arithmetic_checked_callback(tmp_path / "wrong-state", case)
    audit = assurance.audit_plan(case, episode, plan, lambda state, scenario: callback((), scenario))
    assert audit["status"] == "unresolved"
    assert audit["approval_allowed"] is False
    assert any("different restored state" in error
               for entry in audit["hydraulic_evidence"].values() for error in entry["errors"])
    snapshot["assurance"] = audit
    gate = assurance.validate_audit(snapshot)
    assert gate["valid"] and gate["status"] == "unresolved"
    assert gate["approval_allowed"] is False


@pytest.mark.integration
def test_cached_ui_audit_does_not_follow_a_different_plan_or_stale_inputs(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from test_app import button, use_arithmetic_app_hydraulics

    monkeypatch.setenv("MONSOON_DATA_DIR", str(tmp_path / "app"))
    use_arithmetic_app_hydraulics(monkeypatch, tmp_path)
    app = AppTest.from_file(str(service.ROOT / "app.py"), default_timeout=180).run()
    button(app, "Run rehearsal").click().run()
    assert not app.exception and not app.error
    original = app.session_state["selected_plan"]["id"]
    button(app, "Audit selected plan").click().run()
    assert not app.exception and not app.error
    assert any("Selected queue · required model checks passed" in item.value for item in app.success)
    candidates = [plan["id"] for plan in app.session_state["episode"]["plans"] if plan["admissible"]]
    replacement_index = next(index for index, identifier in enumerate(candidates) if identifier != original)
    app.selectbox(key="inspect_plan_id").select_index(replacement_index).run()
    assert not app.exception
    assert not app.success
    assert any("Planning candidate only · stress audit outstanding" in item.value for item in app.warning)
    app.selectbox(key="inspect_plan_id").select_index(candidates.index(original)).run()
    assert any("Selected queue · required model checks passed" in item.value for item in app.success)
    app.number_input(key="deadline").set_value(150).run()
    assert not app.exception
    assert not app.success
    assert button(app, "Audit selected plan").disabled
    assert button(app, "Save selected plan for review").disabled
