"""Strict recorded replay guards; no SWMM calculation runs in these tests."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from monsoon import policy_replay
from monsoon.case import load_case
from monsoon.observed_policy import fingerprint, load_protocol

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def study(monkeypatch):
    """Isolate record guards under the original identity; never replay hydraulics.

    The current cache-publication adapter has a different source/engine hash.
    A mocked frozen runner tests downstream record checks only; separate tests
    below retain the real current-runtime refusal required by production.
    """
    protocol = load_protocol()
    saved = json.loads((ROOT / "evidence/v0.3/policy-development.json").read_text())
    freeze = json.loads((ROOT / "evidence/v0.3/policy-freeze.json").read_text())
    monkeypatch.setattr(policy_replay, "source_fingerprints", lambda: deepcopy(freeze["source_sha256"]))
    monkeypatch.setattr(policy_replay, "engine_info", lambda: deepcopy(freeze["engine"]))
    calls = []
    def fake_replay(snapshot, case, event, callback, supplied_protocol):
        calls.append((snapshot, case, event, callback, supplied_protocol))
        return {"review_fixture": True, "event_id": event["id"]}
    monkeypatch.setattr(policy_replay, "_replay", fake_replay)
    def forbidden(*args, **kwargs):
        pytest.fail("These adapter tests must never invoke a hydraulic callback.")
    return saved["policies"], protocol, load_case(), calls, forbidden


def test_exact_frozen_event_reaches_mocked_runner_unchanged(study):
    policies, protocol, case, calls, callback = study
    original = deepcopy((policies["LOW"], case, protocol["evaluation_events"][0]))
    result = policy_replay.replay_frozen_event(*original, callback)
    assert result == {"review_fixture": True, "event_id": "V3-E01"}
    assert len(calls) == 1
    assert calls[0][:3] == original
    assert calls[0][0] is not original[0]
    assert calls[0][2] is not original[2]


def test_canonical_event_ignores_object_key_order(study):
    policies, protocol, case, calls, callback = study
    event = dict(reversed(list(protocol["evaluation_events"][0].items())))
    assert policy_replay.replay_frozen_event(policies["LOW"], case, event, callback)["event_id"] == "V3-E01"
    assert len(calls) == 1


def test_low_policy_cannot_replay_high_observation(study):
    policies, protocol, case, calls, callback = study
    with pytest.raises(ValueError, match="observation_id"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][4], callback)
    assert not calls


@pytest.mark.parametrize("change", [
    lambda event: event.update(id="UNSEALED-REVIEW-SENTINEL"),
    lambda event: event["hydraulic"].update(tailwater_m=99.99),
    lambda event: event["durations"].update(J1=1),
    lambda event: event.update(observation_id="HIGH"),
    lambda event: event.update(phase="planning"),
    lambda event: event.update(unrecognised_future_information=True),
])
def test_unknown_or_modified_event_is_rejected_before_runner(study, change):
    policies, protocol, case, calls, callback = study
    event = deepcopy(protocol["evaluation_events"][0])
    change(event)
    with pytest.raises(ValueError, match="exact canonical member"):
        policy_replay.replay_frozen_event(policies["LOW"], case, event, callback)
    assert not calls


def test_resigned_policy_cannot_masquerade_as_recorded_decision(study):
    policies, protocol, case, calls, callback = study
    edited = deepcopy(policies["LOW"])
    edited["policies"]["observed_robust"]["queue"] = ["J1"]
    edited["snapshot_sha256"] = fingerprint({k: v for k, v in edited.items() if k != "snapshot_sha256"})
    with pytest.raises(ValueError, match="exact recorded policy"):
        policy_replay.replay_frozen_event(edited, case, protocol["evaluation_events"][0], callback)
    assert not calls


def test_modified_case_is_rejected_before_runner(study):
    policies, protocol, case, calls, callback = study
    case["epsilon_m3"] = 1
    with pytest.raises(ValueError, match="case differs"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][0], callback)
    assert not calls


@pytest.mark.parametrize("value", [None, [], {"id": float("nan")}, '{"id":"a","id":"b"}'])
def test_malformed_input_is_rejected_before_runner(study, value):
    policies, protocol, case, calls, callback = study
    with pytest.raises(ValueError):
        policy_replay.replay_frozen_event(policies["LOW"], case, value, callback)
    assert not calls


def test_changed_frozen_source_fails_closed(study, monkeypatch):
    policies, protocol, case, calls, callback = study
    monkeypatch.setattr(policy_replay, "source_fingerprints", lambda: {"changed": "0" * 64})
    with pytest.raises(ValueError, match="Frozen source"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][0], callback)
    assert not calls


def test_changed_engine_fails_closed(study, monkeypatch):
    policies, protocol, case, calls, callback = study
    monkeypatch.setattr(policy_replay, "engine_info", lambda: {"engine": "changed"})
    with pytest.raises(ValueError, match="Engine differs"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][0], callback)
    assert not calls


@pytest.mark.parametrize("record,attribute", [("data/policy_v3_protocol.json", "_PROTOCOL_PATH"), ("evidence/v0.3/policy-freeze.json", "_FREEZE_PATH"), ("evidence/v0.3/policy-development.json", "_DEVELOPMENT_PATH")])
def test_changed_or_missing_record_is_rejected(study, monkeypatch, tmp_path, record, attribute):
    policies, protocol, case, calls, callback = study
    value = json.loads((ROOT / record).read_text())
    if attribute == "_PROTOCOL_PATH":
        value["evaluation_events"][0]["durations"]["J1"] = 1
        value["protocol_sha256"] = fingerprint({k: v for k, v in value.items() if k != "protocol_sha256"})
    elif attribute == "_FREEZE_PATH":
        value["frozen_utc"] = "2099-01-01T00:00:00Z"
        value["freeze_sha256"] = fingerprint({k: v for k, v in value.items() if k != "freeze_sha256"})
    else:
        value["policies"]["LOW"]["policies"]["observed_robust"]["queue"] = ["J1"]
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(value))
    monkeypatch.setattr(policy_replay, attribute, changed)
    with pytest.raises(ValueError, match="Recorded-study binding"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][0], callback)
    changed.unlink()
    with pytest.raises(ValueError, match="Recorded-study binding"):
        policy_replay.replay_frozen_event(policies["LOW"], case, protocol["evaluation_events"][0], callback)
    assert not calls


def test_input_snapshots_survive_caller_mutation_during_validation(study, monkeypatch):
    policies, protocol, case, calls, callback = study
    snapshot, event = deepcopy(policies["LOW"]), deepcopy(protocol["evaluation_events"][0])
    original = deepcopy((snapshot, case, event))
    real_load = policy_replay._load_study
    def mutate_originals():
        snapshot["policies"]["observed_robust"]["queue"] = ["J1"]
        case["epsilon_m3"] = 5
        event["durations"]["J1"] = 1
        return real_load()
    monkeypatch.setattr(policy_replay, "_load_study", mutate_originals)
    policy_replay.replay_frozen_event(snapshot, case, event, callback)
    assert calls[0][:3] == original


def test_current_source_refuses_historical_replay_before_runner_or_callback(monkeypatch):
    """Real installed identities must not inherit the historical study's claim."""
    freeze = json.loads((ROOT / "evidence/v0.3/policy-freeze.json").read_text())
    policies = json.loads((ROOT / "evidence/v0.3/policy-development.json").read_text())["policies"]
    protocol = load_protocol()
    current_sources = policy_replay.source_fingerprints()
    assert current_sources.keys() == freeze["source_sha256"].keys()
    assert {path for path in current_sources if current_sources[path] != freeze["source_sha256"][path]} == {
        "monsoon/hydraulics.py"}

    def forbidden(*args, **kwargs):
        pytest.fail("A changed real source must be rejected before replay or a hydraulic callback.")

    # Neither source_fingerprints nor engine_info is mocked in this control.
    monkeypatch.setattr(policy_replay, "_replay", forbidden)
    with pytest.raises(ValueError, match="Frozen source or protocol differs"):
        policy_replay.replay_frozen_event(policies["LOW"], load_case(), protocol["evaluation_events"][0], forbidden)


def test_current_engine_refused_even_when_original_source_identity_is_isolated(monkeypatch):
    """Reach the second binding guard with the actual installed adapter identity."""
    freeze = json.loads((ROOT / "evidence/v0.3/policy-freeze.json").read_text())
    policies = json.loads((ROOT / "evidence/v0.3/policy-development.json").read_text())["policies"]
    protocol = load_protocol()
    current_engine = policy_replay.engine_info()
    assert current_engine.keys() == freeze["engine"].keys()
    assert {key for key in current_engine if current_engine[key] != freeze["engine"][key]} == {"adapter_sha256"}

    def forbidden(*args, **kwargs):
        pytest.fail("A changed real engine identity must be rejected before replay or a hydraulic callback.")

    # Only the earlier source guard is isolated; engine_info remains real.
    monkeypatch.setattr(policy_replay, "source_fingerprints", lambda: deepcopy(freeze["source_sha256"]))
    monkeypatch.setattr(policy_replay, "_replay", forbidden)
    with pytest.raises(ValueError, match="Engine differs from the recorded implementation freeze"):
        policy_replay.replay_frozen_event(policies["LOW"], load_case(), protocol["evaluation_events"][0], forbidden)
